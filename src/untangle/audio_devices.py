"""Pulse device selection. Enumeration never opens capture or changes profiles.

prepare() is used by authorized preview, check, and recording lifecycles.
Automatic follows the system default input. Only recording with the explicit
earbud-mic entry may switch Bluetooth earbuds to hands-free; live levels and
checks never trade away playback quality. Release OBS audio sources before
restore(); it defers only while a client captures from the earbud mic.

The switch intent is persisted before the request so a crashed or killed
Untangle can restore the earbuds on its next launch (recover()).
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


def owner_alive(record):
    """A pid from an earlier boot is dead even if the number was reused."""
    boot = boot_id()
    if record.get('boot') and boot and record['boot'] != boot:
        return False
    pid = record.get('pid')
    if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def handsfree_profile(card):
    candidates = []
    for name, profile in card.get('profiles', {}).items():
        if not name.startswith(('headset-head-unit', 'handsfree_head_unit')):
            continue
        if profile.get('available') in (False, 'no') or not profile.get('sources', 0):
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
    def resolve(self, selection='default'):
        if not selection:
            return None
        name = self.read('info').get('default_source_name') if selection == 'default' else selection
        source = next((s for s in self.read('sources') if s['name'] == name and is_microphone(s)), None)
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
            if not switch_profile and self.bluetooth_input(selection):
                emit(self, 'profile.deferred', reason='bluetooth_mic')
                raise EarbudMicDeferred()
            return self.resolve(selection)
        if not switch_profile:
            emit(self, 'profile.deferred', card=name, reason='switch_on_record')
            raise EarbudMicDeferred()
        return self._prepare_earbuds(name, timeout)

    def bluetooth_input(self, selection):
        """Whether a selection uses a Bluetooth mic now. Reads only; untraced."""
        if earbud_card(selection):
            return True
        name = self.read('info').get('default_source_name') if selection == 'default' else selection
        source = next((s for s in self.read('sources') if s['name'] == name), None)
        return bool(source and is_microphone(source) and is_bluetooth(source))

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
        if self.lease and self.lease[0] != name:
            raise AudioDeviceError('Previous headset profile still needs restoration. Choose a microphone explicitly.')
        profile = self.lease[2] if self.lease else handsfree_profile(card)
        if profile is None:
            raise AudioDeviceError('Earbuds have no available hands-free microphone. Choose another microphone.')
        active = card.get('active_profile')
        emit(self, 'profile.selected', card=name, prior_profile=active,
             target_profile=profile, changed=active != profile)
        if active != profile:
            if self.lease and active != self.lease[1]:
                raise AudioDeviceError('Headset profile changed outside Untangle. Choose a microphone again.')
            if not self.lease:
                # Retain ownership even on a timeout: the server may apply it late.
                self.lease = (name, active, profile)
                self._lease_trace = self.audio_trace
                self._write_intent()
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
        if self._fenced():
            emit(self, 'restore.deferred', every=5, reason='capture_owned')
            return False
        return self._restore_idle()

    def _restore_idle(self):
        """After releasing capture, restore only a profile still owned by us.

        Playback never defers: the record-start switch already interrupted it.
        Only a client capturing from the earbud mic does. A missing card keeps
        the lease, since it may return still in hands-free. Inspection
        failures leave the lease intact.
        """
        if not self.lease:
            return True
        name, previous, selected = self.lease
        card = self._card(name)
        if not card or not connected(card, self.audio_trace):
            emit(self, 'restore.deferred', every=5, card=name, reason='card_missing',
                 prior_profile=selected, target_profile=previous)
            return False
        active = card.get('active_profile')
        if active != selected:
            if (active == previous and self._unconfirmed_until is not None
                    and self.clock() < self._unconfirmed_until):
                emit(self, 'restore.deferred', every=5, card=name, reason='switch_pending',
                     prior_profile=selected, target_profile=previous)
                return False
            emit(self, 'restore.skipped', card=name, prior_profile=selected, target_profile=previous,
                 reason='switch_not_applied' if active == previous else 'external_change')
            self._drop_lease()
            return True
        if self._mic_capturing(card):
            emit(self, 'restore.deferred', every=5, card=name, reason='earbud_mic_capturing',
                 prior_profile=selected, target_profile=previous)
            return False
        if not self._write_restore(name, previous, selected):
            return False
        self._drop_lease()
        return True

    def _mic_capturing(self, card):
        # Monitors of the earbud output are playback capture, not the mic.
        mics = {str(s['index']) for s in self.read('sources') if on_card(s, card) and is_microphone(s)}
        return any(str(s.get('source')) in mics for s in self.read('source-outputs'))

    def _write_restore(self, name, previous, selected):
        """Re-read at the write boundary so a newer profile choice always wins.

        Returns False only when the card vanished and the restore should retry.
        """
        card = self._card(name)
        if card is None:
            emit(self, 'restore.deferred', card=name, reason='card_missing',
                 prior_profile=selected, target_profile=previous)
            return False
        if card.get('active_profile') != selected:
            emit(self, 'restore.skipped', card=name, reason='external_change',
                 prior_profile=selected, target_profile=previous)
            return True
        if previous:
            self.command('set-card-profile', name, previous)
            emit(self, 'restore.requested', card=name, prior_profile=selected,
                 target_profile=previous, changed=previous != selected)
        return True

    def _drop_lease(self):
        self.lease = None
        self._unconfirmed_until = None
        self._clear_intent()

    def _write_intent(self):
        if not self.intent_path or not self.lease:
            return
        name, previous, target = self.lease
        record = dict(card=name, previous=previous, target=target, pid=os.getpid(),
                      boot=boot_id(), time=time.time())
        temporary = self.intent_path.with_name(self.intent_path.name + '.tmp')
        try:
            self.intent_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(record))
            os.replace(temporary, self.intent_path)
        except OSError as exc:
            # Recording still restores in-process; only crash recovery is lost.
            emit(self, 'intent.failed', level='warning', card=name, exception_type=type(exc).__name__)

    def _clear_intent(self):
        if not self.intent_path:
            return
        try:
            self.intent_path.unlink(missing_ok=True)
        except OSError as exc:
            emit(self, 'intent.failed', level='warning', exception_type=type(exc).__name__)

    def recover(self):
        """At launch, restore earbuds a crashed or killed Untangle left switched.

        The caller holds the instance lock. Restore only when the recorded
        process is gone, the card is present and still on the profile
        Untangle set, and nothing captures from the earbud mic. Any other
        outcome drops the record and logs why. Returns True if restored.
        """
        if not self.intent_path or self.lease or not self.intent_path.exists():
            return False
        trace, self.audio_trace = self.audio_trace, AudioTrace('recovery')
        name = None
        try:
            try:
                record = json.loads(self.intent_path.read_text())
                name, previous, target = record['card'], record['previous'], record['target']
                if not all(isinstance(value, str) and value for value in (name, previous, target)):
                    raise ValueError('incomplete')
            except (OSError, ValueError, KeyError, TypeError):
                reason = 'unreadable'
            else:
                alive = owner_alive(record)
                card = None if alive else self._card(name)
                if alive:
                    reason = 'owner_alive'
                elif not card or not connected(card, self.audio_trace):
                    reason = 'card_missing'
                elif card.get('active_profile') != target:
                    reason = 'profile_changed'
                elif self._mic_capturing(card):
                    reason = 'earbud_mic_capturing'
                elif self._write_restore(name, previous, target):
                    self._clear_intent()
                    emit(self, 'recovery.restored', card=name, prior_profile=target, target_profile=previous)
                    return True
                else:
                    reason = 'card_missing'
            emit(self, 'recovery.skipped', card=name, reason=reason)
            self._clear_intent()
            return False
        finally:
            self.audio_trace = trace
