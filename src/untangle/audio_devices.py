"""Pulse device selection. Enumeration never opens capture or changes profiles.

prepare() is used by authorized preview, check, and recording lifecycles.
Automatic follows the system default input. Only recording with the explicit
earbud-mic entry may switch Bluetooth earbuds to hands-free; live levels and
checks never trade away playback quality. Release OBS audio sources before
restore(); it defers only while a client captures from the earbud mic.

The switch intent is persisted before the request, and a failed write refuses
the switch, so a crashed or killed Untangle can restore the earbuds on its next
launch (recover()). A finished record is retired as {"done": true} before it is
removed, so a failed removal can never replay an old restore.
"""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from .audio_debug import AudioTrace, emit, traced

# Selection prefix for a Bluetooth card's mic. The source exists only in
# hands-free mode, so the card is the stable identity.
EARBUDS = 'earbuds:'
# A switch request that failed or timed out may still land on the server.
SWITCH_GRACE = 15
HANDSFREE = ('headset-head-unit', 'handsfree_head_unit')
_ANY_CARD = object()


class AudioDeviceError(RuntimeError):
    pass


class AudioStreamPending(AudioDeviceError):
    """The new OBS stream has not been published by the audio server yet."""


class EarbudMicDeferred(AudioDeviceError):
    """The earbud mic needs hands-free mode, which only recording may enable."""
    message = 'Earbud mic switches on when recording starts.'
    expected = True

    def __init__(self):
        super().__init__(self.message)


def pactl(*args):
    try:
        result = subprocess.run(['pactl', *args], capture_output=True, text=True, timeout=2)
        if result.returncode:
            raise AudioDeviceError(result.stderr.strip() or 'PulseAudio command failed.')
        return result.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioDeviceError(f'Cannot contact audio server: {exc}') from exc


def is_microphone(source):
    return (not source['name'].endswith('.monitor')
            and source.get('properties', {}).get('device.class') != 'monitor'
            and source.get('monitor_of_sink') in (None, 4294967295, '4294967295'))


def connected(device, trace=None):
    properties = device.get('properties', {})
    name = device.get('name', '')
    identity = {'card': name} if name.startswith('bluez_card.') else {'source': name}
    path = properties.get('api.bluez5.path')
    if path:
        # PipeWire 1.0.3 can export the initial connection=disconnected and
        # bluez5.profile=off on live cards AND their nodes. Query the owner of
        # the connection, not those inherited snapshot properties.
        try:
            result = subprocess.run(['busctl', '--system', '--timeout=1',
                'get-property', 'org.bluez', path, 'org.bluez.Device1', 'Connected'],
                capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.TimeoutExpired) as exc:
            if trace:
                trace.event('connection.failed', level='warning', **identity,
                            exception_type=type(exc).__name__, connection_signal='org.bluez.Device1.Connected')
            raise AudioDeviceError(f'Cannot verify Bluetooth headset connection: {exc}') from exc
        if result.returncode or result.stdout.strip() not in ('b true', 'b false'):
            if trace:
                trace.event('connection.failed', level='warning', **identity,
                            exception_type='AudioDeviceError', reason='invalid_bluez_response')
            raise AudioDeviceError('Cannot verify Bluetooth headset connection. Reconnect it or choose another microphone.')
        live = result.stdout.strip() == 'b true'
        if trace:
            trace.event('connection.checked', every=5,
                        **identity, connected=live,
                        connection_signal='org.bluez.Device1.Connected',
                        stale_connection=properties.get('api.bluez5.connection'))
        return live
    live = properties.get('api.bluez5.connection') != 'disconnected'
    if trace:
        trace.event('connection.checked', every=5, **identity,
                    connected=live, connection_signal='pulse_property',
                    stale_connection=properties.get('api.bluez5.connection'))
    return live


def on_card(device, card):
    # PipeWire device.id is NOT pactl's card index. device.name is inherited by
    # nodes and wins over reused indices; native PulseAudio exposes a card index.
    name = device.get('properties', {}).get('device.name')
    if name:
        return name == card['name']
    return device.get('card') is not None and str(device['card']) == str(card['index'])


def earbud_card(selection):
    """Return the Bluetooth card named by an earbud-mic selection, else None."""
    if isinstance(selection, str) and selection.startswith(EARBUDS):
        return selection[len(EARBUDS):] or None
    return None


def earbud_selection(source):
    """Map an old saved hands-free source id to its card's earbud entry."""
    for prefix in ('bluez_input.', 'bluez_source.'):
        if isinstance(source, str) and source.startswith(prefix):
            address = source[len(prefix):].split('.')[0]
            if address:
                return EARBUDS + 'bluez_card.' + address
    return None


def is_bluetooth(device):
    properties = device.get('properties', {})
    return (device.get('name', '').startswith(('bluez_', 'bluez.'))
            or properties.get('device.api') == 'bluez5'
            or str(properties.get('device.name') or '').startswith('bluez_card.'))


def card_label(card):
    properties = card.get('properties', {})
    return properties.get('device.alias') or properties.get('device.description') or card['name']


def boot_id():
    try:
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        return None


def switch_grace(record):
    """Seconds of a recorded switch's late-apply grace left after a restart."""
    switched = record.get('time')
    if type(switched) not in (int, float):
        return 0.
    boot, recorded = boot_id(), record.get('boot')
    if boot and recorded and boot != recorded:
        return 0.  # A reboot cannot apply an old request.
    remaining = SWITCH_GRACE - (time.time() - switched)
    return min(remaining, SWITCH_GRACE) if remaining > 0 else 0.


def usable_handsfree(card, name):
    profile = card.get('profiles', {}).get(name)
    return (isinstance(name, str) and name.startswith(HANDSFREE) and isinstance(profile, dict)
            and profile.get('available') not in (False, 'no') and bool(profile.get('sources', 0)))


def handsfree_profile(card):
    candidates = []
    for name, profile in card.get('profiles', {}).items():
        if not usable_handsfree(card, name):
            continue
        quality = 4 if 'lc3' in name else 3 if 'msbc' in name else 1 if 'cvsd' in name else 2
        candidates.append((quality, profile.get('priority', 0), name))
    return max(candidates)[2] if candidates else None


class AudioDevices:
    def __init__(self, command=pactl, clock=time.monotonic, sleep=time.sleep, intent_path=None):
        self.command, self.clock, self.sleep = command, clock, sleep
        self.intent_path = Path(intent_path) if intent_path else None
        self.lease = None
        self.audio_trace = None
        self._lease_trace = None
        self._unconfirmed_until = None
        self._recovered = False
        # A record exists but could not be read; keep it and retry (app tick).
        self.record_unread = False
        self.source_label = None
        self._capture_lock = threading.RLock()
        self._capture_owner = None
        self._capture_card = None

    def hold_capture(self, card=_ANY_CARD):
        """Fence deferred restores before preparing a new capture session.

        Pass the earbud card this capture may switch, or None when it never
        touches Bluetooth profiles; only a matching lease waits for it.
        """
        with self._capture_lock:
            self._capture_owner = object()
            self._capture_card = card
            return self._capture_owner

    def release_capture(self, owner):
        with self._capture_lock:
            if owner is self._capture_owner:
                self._capture_owner = self._capture_card = None

    def _fenced(self):
        return (self._capture_owner is not None and self.lease is not None
                and self._capture_card in (_ANY_CARD, self.lease[0]))

    def verify_stream(self, source, media_name, stream_index=None, pid=None):
        """Verify the server's attachment, never OBS's requested device setting."""
        pid = os.getpid() if pid is None else pid
        streams = [s for s in self.read('source-outputs')
                   if str(s.get('properties', {}).get('application.process.id')) == str(pid)
                   and s.get('properties', {}).get('application.name') in ('OBS', 'OBS Studio', 'RecIt', 'Untangle')
                   and s.get('properties', {}).get('media.name') == media_name]
        if not streams and stream_index is None:
            raise AudioStreamPending('Cannot verify Untangle microphone stream. Retry the microphone check.')
        if len(streams) != 1:
            emit(self, 'route.rejected', level='warning', requested_source=source,
                 reason='missing_or_ambiguous_stream', exception_type='AudioDeviceError')
            raise AudioDeviceError('Cannot verify Untangle microphone stream. Retry the microphone check.')
        stream = streams[0]
        actual = next((s for s in self.read('sources')
                       if str(s['index']) == str(stream.get('source'))), None)
        if (not actual or actual['name'] != source or not is_microphone(actual)
                or (stream_index is not None and str(stream['index']) != str(stream_index))):
            name = actual['name'] if actual else 'unavailable source'
            emit(self, 'route.mismatch', level='warning', requested_source=source, actual_source=name,
                 stream_index=stream.get('index'), reason='source_or_stream_changed',
                 exception_type='AudioDeviceError')
            raise AudioDeviceError(f'Microphone stream changed: requested {source}, attached to {name}. '
                                   'Choose the microphone and retry.')
        self.resolve(source)
        emit(self, 'route.verified', every=5, requested_source=source, actual_source=actual['name'],
             stream_index=stream['index'])
        return stream['index']

    def read(self, kind):
        try:
            return json.loads(self.command('-f', 'json', *(['info'] if kind == 'info' else ['list', kind])))
        except (ValueError, TypeError) as exc:
            raise AudioDeviceError('Audio server returned invalid device information.') from exc

    def microphones(self):
        """Inputs plus one stable entry per connected earbud card, even in A2DP."""
        default = self.read('info').get('default_source_name')
        cards = []
        for card in self.read('cards'):
            if card['name'].startswith('bluez_card.') and handsfree_profile(card):
                try:
                    if connected(card):
                        cards.append(card)
                except AudioDeviceError:
                    pass  # Unverifiable earbuds are not offered; other inputs still are.
        sources = [(s.get('description', s['name']) + (' (system default)' if s['name'] == default else ''), s['name'])
                   for s in self.read('sources') if is_microphone(s) and connected(s)
                   and not any(on_card(s, card) for card in cards)]
        return sources + [(card_label(card) + ' microphone (switches on when recording starts)',
                           EARBUDS + card['name']) for card in cards]

    @traced('resolve', every=5)
    def resolve(self, selection='default', sources=None):
        if not selection:
            return None
        name = self.read('info').get('default_source_name') if selection == 'default' else selection
        sources = self.read('sources') if sources is None else sources
        source = next((s for s in sources if s['name'] == name and is_microphone(s)), None)
        if not source or not connected(source, self.audio_trace):
            emit(self, 'source.rejected', level='warning', source=name, reason='missing_or_disconnected')
            raise AudioDeviceError('Selected microphone is unavailable. Reconnect it or choose another microphone.')
        self.source_label = (source.get('properties', {}).get('device.alias')
            or source.get('properties', {}).get('device.description')
            or source.get('description') or name)
        emit(self, 'source.resolved', every=5, source=name, label=self.source_label,
             card=source.get('properties', {}).get('device.name', source.get('card')),
             muted=source.get('mute'),
             gain=','.join(str(v.get('value')) for v in source.get('volume', {}).values()),
             sample_specification=source.get('sample_specification'), obs_rate=48000)
        if source.get('mute') is True:
            emit(self, 'source.rejected', level='warning', reason='muted', source=name)
            raise AudioDeviceError('Selected microphone is muted. Unmute it in system sound settings and try again.')
        volumes = [v.get('value') for v in source.get('volume', {}).values()]
        if volumes and all(v == 0 for v in volumes):
            emit(self, 'source.rejected', level='warning', reason='zero_gain', source=name)
            raise AudioDeviceError('Selected microphone volume is zero. Raise its input volume in system sound settings and try again.')
        return name

    @traced('prepare')
    def prepare(self, selection='default', *, switch_profile=True, timeout=10):
        """Return an exact OBS device_id, never the OBS default sentinel.

        Automatic follows the system default input and never switches. Only
        the explicit earbud entry switches its card, and only with
        switch_profile (recording). Without it, any Bluetooth mic raises
        EarbudMicDeferred instead of opening: idle levels and checks must not
        lower playback quality or extend a pending restore. timeout bounds
        the earbud switch-and-wait path only.
        """
        emit(self, 'selection.chosen', selection=selection, switch_profile=switch_profile)
        if not selection:
            return None
        name = earbud_card(selection)
        if name is None:
            # Read the default and the sources once, then classify and open
            # that exact source: a default or a reconnecting Bluetooth mic
            # changing in between must not reach OBS unchecked.
            source = self.read('info').get('default_source_name') if selection == 'default' else selection
            if not source:
                emit(self, 'source.rejected', level='warning', source=source, reason='no_default_input')
                raise AudioDeviceError('Selected microphone is unavailable. Reconnect it or choose another microphone.')
            sources = self.read('sources')
            if not switch_profile and self.bluetooth_input(source, sources):
                emit(self, 'profile.deferred', reason='bluetooth_mic')
                raise EarbudMicDeferred()
            return self.resolve(source, sources=sources)
        if not switch_profile:
            emit(self, 'profile.deferred', card=name, reason='switch_on_record')
            raise EarbudMicDeferred()
        return self._prepare_earbuds(name, timeout)

    def bluetooth_input(self, selection, sources=None):
        """Whether a selection uses a Bluetooth mic now. Reads only; untraced.

        A source not listed yet is judged by its name: a reconnecting earbud
        mic can be the default before it is listed.
        """
        if earbud_card(selection):
            return True
        name = self.read('info').get('default_source_name') if selection == 'default' else selection
        sources = self.read('sources') if sources is None else sources
        source = next((s for s in sources if s['name'] == name), None)
        if source is None:
            return is_bluetooth({'name': name or ''})
        return is_microphone(source) and is_bluetooth(source)

    def _card(self, name):
        return next((c for c in self.read('cards') if c['name'] == name), None)

    def _prepare_earbuds(self, name, timeout):
        deadline = self.clock() + timeout
        card = self._card(name)
        if card is None:
            raise AudioDeviceError('Earbuds are not connected. Connect them or choose another microphone.')
        while not connected(card, self.audio_trace):
            if self.clock() >= deadline:
                emit(self, 'prepare.timeout', level='warning', phase='connection', exception_type='TimeoutError')
                raise AudioDeviceError('Bluetooth headset is disconnected. Reconnect it or choose another microphone.')
            self.sleep(.1)
            card = self._card(name)
            if card is None:
                raise AudioDeviceError('Bluetooth headset disconnected while preparing its microphone.')
        with self._capture_lock:
            if not self.lease and self.record_unread:
                self._adopt_intent()
        # One restore is tracked at a time. Another pair still owed a restore
        # only blocks earbuds that would need a switch themselves.
        owned = self.lease if self.lease and self.lease[0] == name else None
        profile = owned[2] if owned else handsfree_profile(card)
        if profile is None:
            raise AudioDeviceError('Earbuds have no available hands-free microphone. Choose another microphone.')
        active = card.get('active_profile')
        if self.lease and not owned and active != profile and usable_handsfree(card, active):
            profile = active  # Already hands-free with a mic: use it as is.
        emit(self, 'profile.selected', card=name, prior_profile=active,
             target_profile=profile, changed=active != profile)
        if active != profile:
            if self.lease and not owned:
                emit(self, 'profile.refused', level='warning', card=name, reason='other_card_pending',
                     pending_card=self.lease[0])
                raise AudioDeviceError('Untangle is still waiting to switch your other earbuds back to '
                                       'high-quality playback. Connect them once so Untangle can restore '
                                       'them, then record with these earbuds. If those earbuds are gone, '
                                       'quit Untangle, delete ~/.local/state/glint/bluetooth-profile.json, '
                                       'then relaunch.')
            if self.record_unread:
                # It may name other earbuds; a new record would overwrite it.
                emit(self, 'profile.refused', level='warning', card=name, reason='record_unread')
                raise AudioDeviceError('Cannot read the earbud restore record, so Untangle did not switch '
                                       f'the earbuds. Check that {self.intent_path} is readable, '
                                       'or choose another microphone.')
            if owned and active != owned[1]:
                raise AudioDeviceError('Headset profile changed outside Untangle. Choose a microphone again.')
            lease = owned or (name, active, profile)
            try:
                # Never switch without a record the next launch can restore from.
                self._write_intent(lease, time.time())
            except OSError as exc:
                emit(self, 'intent.failed', level='warning', card=name, exception_type=type(exc).__name__)
                raise AudioDeviceError(f'Cannot save the earbud restore record ({type(exc).__name__}: {exc}), '
                                       'so Untangle did not switch the earbuds. Check that '
                                       f'{self.intent_path.parent} is writable and the disk has free space, '
                                       'or choose another microphone.') from exc
            if not owned:
                # Retain ownership even on a timeout: the server may apply it late.
                self.lease = lease
                self._lease_trace = self.audio_trace
            self._unconfirmed_until = self.clock() + SWITCH_GRACE
            emit(self, 'profile.requested', card=name, target_profile=profile)
            try:
                self.command('set-card-profile', name, profile)
            except Exception as exc:
                emit(self, 'profile.failed', level='warning', card=name,
                     target_profile=profile, exception_type=type(exc).__name__)
                raise
        while True:
            current = self._card(name)
            if not current:
                raise AudioDeviceError('Bluetooth headset disconnected while preparing its microphone.')
            sources = [s for s in self.read('sources') if is_microphone(s) and on_card(s, current) and connected(s, self.audio_trace)] if connected(current, self.audio_trace) else []
            if current.get('active_profile') == profile and sources:
                self._unconfirmed_until = None
                emit(self, 'profile.ready', card=name, target_profile=profile)
                source = max(sources, key=lambda s: int(s.get('properties', {}).get('priority.session', 0)))['name']
                resolved = self.resolve(source)
                self.source_label = card_label(current)
                return resolved
            if self.clock() >= deadline:
                emit(self, 'prepare.timeout', level='warning', phase='profile_source', exception_type='TimeoutError')
                raise AudioDeviceError('Headset microphone did not become available. Reconnect it or select another microphone.')
            self.sleep(.1)

    def restore(self, *, exiting=False):
        with self._capture_lock:
            # A later capture can begin before a deferred profile restore.
            # Keep restoration evidence with the session that changed it.
            trace = self.audio_trace
            if self.lease and self._lease_trace is not None:
                self.audio_trace = self._lease_trace
            try:
                deadline = self.clock() + (2 if exiting else 0)
                while True:
                    restored = self._restore_traced()
                    if restored or self._fenced() or self.clock() >= deadline:
                        return restored
                    self.sleep(.1)
            finally:
                self.audio_trace = trace

    @traced('restore', every=5)
    def _restore_traced(self):
        if not self.lease and self.record_unread:
            self._adopt_intent()  # Retry a record that could not be read yet.
        if self._fenced():
            emit(self, 'restore.deferred', every=5, reason='capture_owned')
            return False
        return self._restore_idle() != 'deferred'

    def _restore_idle(self):
        """After releasing capture, restore only a profile still owned by us.

        Playback never defers: the record-start switch already interrupted it.
        Only a client capturing from the earbud mic does. A missing card keeps
        the lease, since it may return still in hands-free. Inspection
        failures leave the lease intact, as does a record that could not be
        read. Returns 'restored', 'skipped', 'deferred' or 'idle' (nothing
        owned).
        """
        if not self.lease:
            return 'deferred' if self.record_unread else 'idle'
        name, previous, selected = self.lease
        card = self._card(name)
        if not card or not connected(card, self.audio_trace):
            emit(self, 'restore.deferred', every=5, card=name, reason='card_missing',
                 prior_profile=selected, target_profile=previous)
            return 'deferred'
        active = card.get('active_profile')
        if active != selected:
            if (active == previous and self._unconfirmed_until is not None
                    and self.clock() < self._unconfirmed_until):
                emit(self, 'restore.deferred', every=5, card=name, reason='switch_pending',
                     prior_profile=selected, target_profile=previous)
                return 'deferred'
            emit(self, 'restore.skipped', card=name, prior_profile=selected, target_profile=previous,
                 reason='switch_not_applied' if active == previous else 'external_change')
            self._drop_lease()
            return 'skipped'
        if self._mic_capturing(card):
            emit(self, 'restore.deferred', every=5, card=name, reason='earbud_mic_capturing',
                 prior_profile=selected, target_profile=previous)
            return 'deferred'
        wrote = self._write_restore(name, previous, selected)
        if wrote is None:
            return 'deferred'
        recovered = self._recovered
        self._drop_lease()
        if not wrote:
            return 'skipped'
        if recovered:
            emit(self, 'recovery.restored', card=name, prior_profile=selected, target_profile=previous)
        return 'restored'

    def _mic_capturing(self, card):
        # Monitors of the earbud output are playback capture, not the mic.
        mics = {str(s['index']) for s in self.read('sources') if on_card(s, card) and is_microphone(s)}
        return any(str(s.get('source')) in mics for s in self.read('source-outputs'))

    def _write_restore(self, name, previous, selected):
        """Re-read at the write boundary so a newer profile choice always wins.

        Returns True when it requested the restore, False when it skipped a
        newer choice, and None when the card vanished and the restore retries.
        """
        card = self._card(name)
        if card is None:
            emit(self, 'restore.deferred', card=name, reason='card_missing',
                 prior_profile=selected, target_profile=previous)
            return None
        if card.get('active_profile') != selected:
            emit(self, 'restore.skipped', card=name, reason='external_change',
                 prior_profile=selected, target_profile=previous)
            return False
        if previous:
            self.command('set-card-profile', name, previous)
            emit(self, 'restore.requested', card=name, prior_profile=selected,
                 target_profile=previous, changed=previous != selected)
        return True

    def _drop_lease(self):
        self.lease = None
        self._unconfirmed_until = None
        self._recovered = False
        self._clear_intent()

    def _write_intent(self, lease, switched):
        """Atomically persist a lease and its switch time. Raises OSError."""
        if not self.intent_path:
            return
        name, previous, target = lease
        self._write_record(dict(card=name, previous=previous, target=target, pid=os.getpid(),
                                boot=boot_id(), time=switched))

    def _write_record(self, record):
        temporary = self.intent_path.with_name(self.intent_path.name + '.tmp')
        try:
            self.intent_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(record))
            os.replace(temporary, self.intent_path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _read_intent(self):
        """Return ('missing' | 'unread' | 'invalid' | 'done', None) or ('valid', record).

        'unread' means the file could not be read: keep it and retry. Only a
        record that was read and found bad is 'invalid' and dropped.
        """
        if not self.intent_path:
            return 'missing', None
        try:
            text = self.intent_path.read_text()
        except FileNotFoundError:
            return 'missing', None
        except OSError as exc:
            return 'unread', exc
        except ValueError:
            return 'invalid', None  # Not text.
        try:
            record = json.loads(text) if text.strip() else {'done': True}
        except ValueError:
            return 'invalid', None
        if not isinstance(record, dict):
            return 'invalid', None
        if record.get('done') is True:
            return 'done', None
        values = tuple(record.get(key) for key in ('card', 'previous', 'target'))
        pid = record.get('pid')
        if not all(isinstance(value, str) and value for value in values):
            return 'invalid', None
        card, _, target = values
        # Only ever restore a Bluetooth card Untangle switched to hands-free.
        if (not card.startswith('bluez_card.') or card == 'bluez_card.'
                or not target.startswith(HANDSFREE)):
            return 'invalid', None
        if type(pid) is not int or not 0 < pid < 2 ** 31:
            return 'invalid', None
        return 'valid', record

    def _clear_intent(self):
        """Retire the record durably, then remove it.

        A launch ignores a done record, so a failed removal can never replay
        a finished restore against a profile chosen later.
        """
        if not self.intent_path:
            return
        retired = None
        try:
            self._write_record({'done': True})
        except OSError as exc:
            retired = exc
            emit(self, 'intent.failed', level='warning', exception_type=type(exc).__name__,
                 reason='retire_failed')
        try:
            self.intent_path.unlink(missing_ok=True)
        except OSError as exc:
            if retired is None:
                emit(self, 'intent.failed', level='warning', exception_type=type(exc).__name__)
            else:
                # The next launch may replay this restore. Log it even untraced.
                trace = self.audio_trace if isinstance(self.audio_trace, AudioTrace) else AudioTrace('restore')
                trace.event('intent.stuck', level='error', exception_type=type(exc).__name__,
                            reason='retire_and_remove_failed')

    def _adopt_intent(self):
        """Take over a valid record as this process's lease. Caller holds the lock."""
        status, value = self._read_intent()
        self.record_unread = status == 'unread'
        if status == 'unread':
            emit(self, 'recovery.deferred', level='warning', every=5, reason='read_failed',
                 exception_type=type(value).__name__)
            return False
        if status == 'missing':
            return False
        if status == 'invalid':
            emit(self, 'recovery.skipped', reason='unreadable')
            self._clear_intent()
            return False
        if status == 'done':
            try:
                self.intent_path.unlink(missing_ok=True)
            except OSError as exc:
                emit(self, 'intent.failed', level='warning', exception_type=type(exc).__name__)
            return False
        record = value
        grace = switch_grace(record)
        self.lease = (record['card'], record['previous'], record['target'])
        self._lease_trace = self.audio_trace
        self._recovered = True
        self._unconfirmed_until = self.clock() + grace if grace else None
        try:
            self._write_intent(self.lease, record.get('time') if grace else None)
        except OSError as exc:
            # The old record stays: any pid in it is stale at next launch.
            emit(self, 'intent.failed', level='warning', card=record['card'],
                 exception_type=type(exc).__name__)
        emit(self, 'recovery.adopted', card=record['card'], prior_profile=record['target'],
             target_profile=record['previous'], grace_s=round(grace, 1))
        return True

    def recover(self):
        """At launch, take over a restore a crashed or killed Untangle still owed.

        The caller holds the instance lock, so whoever wrote the record is
        gone, even if its pid was reused. A valid record becomes this
        process's lease, rewritten with this pid and the remaining late-switch
        grace, before any device call. A missing card, an app using the earbud
        mic, or an audio-server error therefore leaves it pending for the
        app's restore retry. A record that cannot be read is kept, and
        restore() retries reading it. Only invalid contents, a profile changed
        outside Untangle, or a switch that never landed within its grace drop
        it; a done record is just removed. Returns True if restored now.
        """
        if not self.intent_path or self.lease:
            return False
        trace, self.audio_trace = self.audio_trace, AudioTrace('recovery')
        try:
            with self._capture_lock:
                if not self._adopt_intent():
                    return False
                return self._restore_idle() == 'restored'
        finally:
            self.audio_trace = trace
