import errno
import json
import os
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from untangle.audio_devices import AudioDeviceError, AudioDevices, handsfree_profile, on_card


def denied(path):
    return PermissionError(errno.EACCES, 'Permission denied', str(path))


class AudioDevicesTests(unittest.TestCase):
    def setUp(self):
        self.card = dict(name='bluez_card.test', index=17, active_profile='a2dp-sink', profiles={
            'headset-head-unit-cvsd': dict(sources=1, available=True),
            'headset-head-unit-msbc': dict(sources=1, available=True),
            'headset-head-unit-lc3-swb': dict(sources=1, available=False)})
        self.mic = dict(name='bluez_input.test.0', index=42, properties={'device.name': 'bluez_card.test'})
        self.data = {'info': dict(default_source_name='brio', default_sink_name='buds'),
                     'cards': [self.card], 'sources': [dict(name='brio', index=1), dict(name='buds.monitor', index=2)],
                     'sinks': [dict(name='buds', index=43, properties={'device.name': 'bluez_card.test'})],
                     'source-outputs': [], 'sink-inputs': []}
        self.calls = []
        self.now = 0
        self.publish = True
        self.earbuds = 'earbuds:bluez_card.test'
        self.devices = AudioDevices(self.command, lambda: self.now, self.sleep)

    def command(self, *args):
        self.calls.append(args)
        if args[0] == 'set-card-profile':
            self.card['active_profile'] = args[2]
            if self.publish:
                self.data['sources'] = [self.mic]
            return ''
        return json.dumps(self.data[args[-1]])

    def sleep(self, duration):
        self.now += duration

    def test_on_card_rejects_conflicting_stable_name_with_reused_index(self):
        source = dict(self.mic, card=self.card['index'],
                      properties={'device.name': 'bluez_card.other'})
        self.assertFalse(on_card(source, self.card))

    def test_on_card_accepts_stable_name_despite_changed_index(self):
        source = dict(self.mic, card=self.card['index'] + 1)
        self.assertTrue(on_card(source, self.card))

    def test_on_card_uses_numeric_index_without_stable_name(self):
        for properties in ({}, {'device.name': ''}, {'device.name': None}):
            with self.subTest(properties=properties):
                source = dict(card=str(self.card['index']), properties=properties)
                self.assertTrue(on_card(source, self.card))
                source['card'] = self.card['index'] + 1
                self.assertFalse(on_card(source, self.card))

    def test_on_card_rejects_missing_identity(self):
        for source in ({}, {'card': None},
                       {'properties': {'device.id': str(self.card['index'])}}):
            with self.subTest(source=source):
                self.assertFalse(on_card(source, self.card))


    def test_default_is_system_not_first_source_and_monitors_excluded(self):
        self.data['sources'].insert(0, dict(name='other', index=9))
        self.assertEqual(self.devices.resolve(), 'brio')
        self.assertEqual(self.devices.microphones(), [
            ('other', 'other'), ('brio (system default)', 'brio'),
            ('bluez_card.test microphone (switches on when recording starts)', self.earbuds)])
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))

    def test_earbud_entry_is_stable_across_profiles_and_old_ids_migrate(self):
        from untangle.audio_devices import earbud_card, earbud_selection
        self.card['properties'] = {'device.description': 'OnePlus Buds 4'}
        entry = ('OnePlus Buds 4 microphone (switches on when recording starts)', self.earbuds)
        self.assertEqual(self.devices.microphones()[-1], entry)
        # In hands-free the raw source appears; the card entry replaces it.
        self.card['active_profile'] = 'headset-head-unit-msbc'
        self.data['sources'].append(self.mic)
        self.assertEqual(self.devices.microphones(), [('brio (system default)', 'brio'), entry])
        self.assertEqual(earbud_card(self.earbuds), 'bluez_card.test')
        self.assertIsNone(earbud_card('brio'))
        self.assertEqual(earbud_selection('bluez_input.AA_BB.0'), 'earbuds:bluez_card.AA_BB')
        self.assertEqual(earbud_selection('bluez_source.AA_BB.handsfree_head_unit'), 'earbuds:bluez_card.AA_BB')
        self.assertIsNone(earbud_selection('dji_receiver'))
        # Earbuds without a hands-free microphone, or disconnected, get no entry.
        self.card['properties']['api.bluez5.connection'] = 'disconnected'
        self.assertNotIn(entry, self.devices.microphones())
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))

    def test_prepares_exact_obs_source_and_restores(self):
        self.assertEqual(self.devices.prepare(self.earbuds), 'bluez_input.test.0')
        self.assertEqual(self.card['active_profile'], 'headset-head-unit-msbc')
        self.assertTrue(self.devices.restore())
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')

    def test_muted_and_zero_volume_rejected_without_changing_gain(self):
        for metadata, message in ((dict(mute=True), 'muted'),
                                  (dict(volume={'mono': {'value': 0}}), 'zero')):
            with self.subTest(metadata=metadata):
                self.mic.update(metadata)
                with self.assertRaisesRegex(AudioDeviceError, message):
                    self.devices.prepare(self.earbuds)
                self.assertFalse(any(c[0] in ('set-source-mute', 'set-source-volume') for c in self.calls))
                self.mic.pop('mute', None)
                self.mic.pop('volume', None)


    def test_automatic_follows_system_default_dji_while_earbuds_play(self):
        # Earbuds are the default output; the DJI receiver is the default input.
        self.data['sources'].append(dict(name='dji_receiver', index=5))
        self.data['info']['default_source_name'] = 'dji_receiver'
        for switch in (True, False):
            self.assertEqual(self.devices.prepare(switch_profile=switch), 'dji_receiver')
        self.assertTrue(self.devices.restore())
        self.assertIsNone(self.devices.lease)
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
        self.assertEqual(self.now, 0)


    def test_real_non_bluetooth_output_keeps_actual_default_microphone(self):
        self.data['sinks'] = [dict(name='buds', index=43)]
        self.assertEqual(self.devices.prepare(), 'brio')
        self.assertIsNone(self.devices.lease)


    def test_headset_source_can_arrive_after_profile(self):
        self.publish = False
        def publish(duration):
            self.sleep(duration)
            self.data['sources'] = [self.mic]
        self.devices.sleep = publish
        self.assertEqual(self.devices.prepare(self.earbuds, timeout=.2), self.mic['name'])

    def test_earbud_switch_waits_ten_seconds_for_the_mic(self):
        self.publish = False
        def publish(duration):
            self.sleep(duration)
            if self.now >= 6:
                self.data['sources'] = [self.mic]
        self.devices.sleep = publish
        self.assertEqual(self.devices.prepare(self.earbuds), self.mic['name'])
        self.devices.restore()
        self.publish, self.now = False, 0
        self.devices.sleep = self.sleep
        self.data['sources'] = []
        with self.assertRaisesRegex(AudioDeviceError, 'did not become available'):
            self.devices.prepare(self.earbuds)
        self.assertGreaterEqual(self.now, 10)
        self.assertLess(self.now, 10.2)


    def test_no_switch_mode_defers_earbud_mic_without_side_effects(self):
        from untangle.audio_devices import EarbudMicDeferred
        for active in ('a2dp-sink', 'headset-head-unit-msbc'):
            with self.subTest(active=active):
                self.card['active_profile'] = active
                with self.assertRaises(EarbudMicDeferred):
                    self.devices.prepare(self.earbuds, switch_profile=False)
                self.assertIsNone(self.devices.lease)
                self.assertEqual(self.card['active_profile'], active)
        # A Bluetooth system default is never opened by idle levels or checks.
        self.data['sources'].append(self.mic)
        self.data['info']['default_source_name'] = self.mic['name']
        with self.assertRaises(EarbudMicDeferred):
            self.devices.prepare(switch_profile=False)
        with self.assertRaises(EarbudMicDeferred):
            self.devices.prepare(self.mic['name'], switch_profile=False)
        # Recording may use it as-is, without owning or changing the profile.
        self.assertEqual(self.devices.prepare(), self.mic['name'])
        self.assertIsNone(self.devices.lease)
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
        # Other microphones and non-Bluetooth outputs are unaffected.
        self.assertEqual(self.devices.prepare('brio', switch_profile=False), 'brio')
        self.data['info']['default_source_name'] = 'brio'
        self.assertEqual(self.devices.prepare(switch_profile=False), 'brio')


    def test_explicit_and_automatic_do_not_switch(self):
        self.assertEqual(self.devices.prepare('brio'), 'brio')
        self.assertEqual(self.devices.prepare(), 'brio')
        self.assertIsNone(self.devices.prepare(None))
        self.assertIsNone(self.devices.lease)
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))

    def test_missing_default_and_disconnected_fail(self):
        self.data['info']['default_source_name'] = 'absent'
        with self.assertRaises(AudioDeviceError):
            self.devices.resolve()
        self.card['properties'] = {'api.bluez5.connection': 'disconnected'}
        with self.assertRaises(AudioDeviceError):
            self.devices.prepare(self.earbuds)
        self.assertIsNone(self.devices.lease)

    def test_timeout_does_not_fall_back_to_brio(self):
        self.publish = False
        with self.assertRaisesRegex(AudioDeviceError, 'did not become available'):
            self.devices.prepare(self.earbuds, timeout=.2)
        self.assertIsNotNone(self.devices.lease)


    def test_restore_defers_only_for_earbud_mic_capture_and_respects_profile_change(self):
        self.devices.prepare(self.earbuds)
        self.data['source-outputs'] = [dict(source=42)]
        with self.assertLogs('recit.audio') as logs:
            self.devices.audio_trace = __import__('untangle.audio_debug', fromlist=['AudioTrace']).AudioTrace()
            self.assertFalse(self.devices.restore())
        self.assertIn('"reason":"earbud_mic_capturing"', ' '.join(logs.output))
        self.assertIsNotNone(self.devices.lease)
        self.data['source-outputs'] = []
        self.card['active_profile'] = 'off'
        self.assertTrue(self.devices.restore())
        self.assertEqual(self.card['active_profile'], 'off')
        self.assertIsNone(self.devices.lease)

    def test_playback_and_output_monitor_capture_never_defer_restore(self):
        # The record-start switch already interrupted playback; restore promptly.
        self.devices.prepare(self.earbuds)
        monitor = dict(name='bluez_output.test.1.monitor', index=44,
                       properties={'device.name': 'bluez_card.test', 'device.class': 'monitor'})
        self.data['sources'].append(monitor)
        self.data['sink-inputs'] = [dict(sink=43)]
        self.data['source-outputs'] = [dict(source=44)]
        self.assertTrue(self.devices.restore())
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        self.assertIsNone(self.devices.lease)


    def test_restore_fence_is_scoped_to_the_earbud_card(self):
        self.devices.prepare(self.earbuds)
        owner = self.devices.hold_capture('bluez_card.test')  # May switch this card: wait.
        self.assertFalse(self.devices.restore())
        self.assertEqual(self.card['active_profile'], 'headset-head-unit-msbc')
        self.devices.release_capture(owner)
        for card in (None, 'bluez_card.other'):  # DJI meter or check; other earbuds.
            with self.subTest(card=card):
                self.devices.prepare(self.earbuds)
                owner = self.devices.hold_capture(card)
                self.assertTrue(self.devices.restore())
                self.assertEqual(self.card['active_profile'], 'a2dp-sink')
                self.devices.release_capture(owner)

    def test_unrelated_capture_owner_never_blocks_restore(self):
        self.devices.prepare(self.earbuds)
        self.devices.hold_capture(None)
        self.assertTrue(self.devices.restore())
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')

    def test_missing_card_keeps_the_lease_and_restores_on_return(self):
        self.devices.prepare(self.earbuds)
        self.data['cards'] = []
        self.assertFalse(self.devices.restore())
        self.assertIsNotNone(self.devices.lease)
        self.data['cards'] = [self.card]
        self.assertTrue(self.devices.restore())
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')

    def test_timed_out_switch_that_lands_late_is_restored(self):
        command = self.devices.command
        def timeout(*args):
            if args[0] == 'set-card-profile' and args[2] == 'headset-head-unit-msbc':
                raise AudioDeviceError('simulated pactl timeout')
            return command(*args)
        self.devices.command = timeout
        with self.assertRaises(AudioDeviceError):
            self.devices.prepare(self.earbuds)
        self.assertFalse(self.devices.restore())  # Still a2dp: the switch may land.
        command('set-card-profile', 'bluez_card.test', 'headset-head-unit-msbc')
        self.assertTrue(self.devices.restore())
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        # A switch that never lands is dropped after the grace period.
        with self.assertRaises(AudioDeviceError):
            self.devices.prepare(self.earbuds)
        self.now += 16
        self.assertTrue(self.devices.restore())
        self.assertIsNone(self.devices.lease)
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')

    def test_restore_never_overwrites_a_profile_changed_during_inspection(self):
        for changed in ('off', 'headset-head-unit-cvsd'):
            with self.subTest(changed=changed):
                self.card['active_profile'] = 'a2dp-sink'
                self.devices.command = self.command
                self.devices.prepare(self.earbuds)
                def change_during_inspection(*args):
                    if args[-1] == 'source-outputs':
                        self.card['active_profile'] = changed
                    return self.command(*args)
                self.devices.command = change_during_inspection
                self.assertTrue(self.devices.restore())
                self.assertEqual(self.card['active_profile'], changed)
                self.assertIsNone(self.devices.lease)


    def test_exit_restores_listening_profile_while_music_is_playing(self):
        self.devices.prepare(self.earbuds)
        self.data['sink-inputs'] = [dict(sink=43)]
        self.assertTrue(self.devices.restore(exiting=True))
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        self.assertIsNone(self.devices.lease)
        self.assertEqual(self.now, 0)

    def test_exit_waits_for_microphone_stream_to_disappear(self):
        self.devices.prepare(self.earbuds)
        self.data['source-outputs'] = [dict(source=42)]
        def release(duration):
            self.assertEqual(self.card['active_profile'], 'headset-head-unit-msbc')
            self.sleep(duration)
            self.data['source-outputs'] = []
        self.devices.sleep = release
        self.assertTrue(self.devices.restore(exiting=True))
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        self.assertGreater(self.now, 0)

    def test_exit_preserves_active_microphone_and_capture_owner(self):
        self.devices.prepare(self.earbuds)
        owner = self.devices.hold_capture()
        self.assertFalse(self.devices.restore(exiting=True))
        self.assertEqual(self.now, 0)
        self.devices.release_capture(owner)
        self.data['source-outputs'] = [dict(source=42)]
        self.assertFalse(self.devices.restore(exiting=True))
        self.assertGreaterEqual(self.now, 2)
        self.assertLess(self.now, 2.2)
        self.assertEqual(self.card['active_profile'], 'headset-head-unit-msbc')
        self.assertIsNotNone(self.devices.lease)

    def test_profile_failure_and_removal(self):
        command = self.devices.command
        def fail(*args):
            if args[0] == 'set-card-profile':
                raise AudioDeviceError('switch failed')
            return command(*args)
        self.devices.command = fail
        with self.assertRaisesRegex(AudioDeviceError, 'switch failed'):
            self.devices.prepare(self.earbuds)
        self.devices.command = command
        self.devices.lease = None
        self.publish = False
        def unplug(duration):
            self.data['cards'] = []
            self.sleep(duration)
        self.devices.sleep = unplug
        with self.assertRaisesRegex(AudioDeviceError, 'disconnected'):
            self.devices.prepare(self.earbuds)

    def test_wideband_only_when_advertised(self):
        self.assertEqual(handsfree_profile(self.card), 'headset-head-unit-msbc')
        self.card['profiles']['headset-head-unit-lc3-swb']['available'] = True
        self.assertEqual(handsfree_profile(self.card), 'headset-head-unit-lc3-swb')
        del self.card['profiles']['headset-head-unit-lc3-swb']
        del self.card['profiles']['headset-head-unit-msbc']
        self.assertEqual(handsfree_profile(self.card), 'headset-head-unit-cvsd')


    def intent_devices(self):
        import tempfile
        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, root, True)
        path = root / 'state' / 'bluetooth-profile.json'
        return AudioDevices(self.command, lambda: self.now, self.sleep, intent_path=path), path

    def test_intent_is_persisted_before_switch_and_cleared_after_restore(self):
        import os
        devices, path = self.intent_devices()
        seen = []
        def command(*args):
            if args[0] == 'set-card-profile' and args[2] != 'a2dp-sink':
                seen.append(json.loads(path.read_text()))
            return self.command(*args)
        devices.command = command
        devices.prepare(self.earbuds)
        self.assertEqual(len(seen), 1)
        self.assertEqual({k: seen[0][k] for k in ('card', 'previous', 'target', 'pid')},
                         dict(card='bluez_card.test', previous='a2dp-sink',
                              target='headset-head-unit-msbc', pid=os.getpid()))
        self.assertIsInstance(seen[0]['time'], float)
        self.data['cards'] = []
        self.assertFalse(devices.restore())
        self.assertTrue(path.exists())  # Missing card: keep the record.
        self.data['cards'] = [self.card]
        self.assertTrue(devices.restore())
        self.assertFalse(path.exists())
        # A deliberate skip (newer profile choice) also clears it.
        devices.prepare(self.earbuds)
        self.card['active_profile'] = 'off'
        self.assertTrue(devices.restore())
        self.assertFalse(path.exists())
        # Already hands-free: nothing owned, nothing persisted.
        self.card['active_profile'] = 'headset-head-unit-msbc'
        devices.prepare(self.earbuds)
        self.assertFalse(path.exists())
        self.assertIsNone(devices.lease)

    def stale_intent(self, **overrides):
        devices, path = self.intent_devices()
        path.parent.mkdir(parents=True)
        record = dict(card='bluez_card.test', previous='a2dp-sink', target='headset-head-unit-msbc',
                      pid=999999, boot=None, time=0.)
        record.update(overrides)
        path.write_text(json.dumps(record))
        self.card['active_profile'] = 'headset-head-unit-msbc'
        self.data['sources'].append(self.mic)
        return devices, path

    def test_launch_recovery_restores_earbuds_left_by_a_dead_process(self):
        devices, path = self.stale_intent()
        with patch('untangle.audio_devices.os.kill', side_effect=ProcessLookupError), \
                self.assertLogs('recit.audio') as logs:
            self.assertTrue(devices.recover())
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        self.assertFalse(path.exists())
        self.assertIn('recovery.restored', ' '.join(logs.output))
        self.assertFalse(devices.recover())  # Nothing left to do.

    def test_launch_recovery_adopts_pending_restore_until_it_is_safe(self):
        import os
        def server_down(devices):
            def command(*args):
                raise AudioDeviceError('Cannot contact audio server')
            devices.command = command
        def busctl_fails(devices):
            self.card.setdefault('properties', {})['api.bluez5.path'] = '/org/bluez/hci0/dev_X'
        cases = (('card_missing', lambda devices: self.data.update(cards=[])),
                 ('earbud_mic_capturing',
                  lambda devices: self.data.update({'source-outputs': [dict(source=42)]})),
                 ('server_error', server_down), ('busctl_error', busctl_fails))
        for reason, arrange in cases:
            with self.subTest(reason=reason):
                devices, path = self.stale_intent()
                self.data.update({'cards': [self.card], 'source-outputs': []})
                self.card.pop('properties', None)
                arrange(devices)
                self.calls.clear()
                with patch('untangle.audio_devices.subprocess.run') as run:
                    run.return_value.returncode = 1
                    try:
                        self.assertFalse(devices.recover())
                    except AudioDeviceError:
                        self.assertIn(reason, ('server_error', 'busctl_error'))
                # Kept and adopted by this process; nothing switched yet.
                self.assertEqual(json.loads(path.read_text())['pid'], os.getpid())
                self.assertEqual(devices.lease, ('bluez_card.test', 'a2dp-sink', 'headset-head-unit-msbc'))
                self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
                # The card returns, still hands-free and released: the app's retry restores it.
                self.card.pop('properties', None)
                devices.command = self.command
                self.data.update({'cards': [self.card], 'source-outputs': []})
                with self.assertLogs('recit.audio') as logs:
                    self.assertTrue(devices.restore())
                self.assertIn('recovery.restored', ' '.join(logs.output))
                self.assertEqual(self.card['active_profile'], 'a2dp-sink')
                self.assertFalse(path.exists())
                self.assertIsNone(devices.lease)

    def test_launch_recovery_drops_a_profile_changed_outside_untangle(self):
        devices, path = self.stale_intent()
        self.card['active_profile'] = 'off'
        with self.assertLogs('recit.audio') as logs:
            self.assertFalse(devices.recover())
        self.assertIn('"reason":"external_change"', ' '.join(logs.output))
        self.assertFalse(path.exists())
        self.assertIsNone(devices.lease)
        self.assertEqual(self.card['active_profile'], 'off')
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))

    def test_launch_recovery_carries_the_late_switch_grace_across_restart(self):
        import time
        # Killed 5 s after requesting the switch; the server applies it late.
        devices, path = self.stale_intent(time=time.time() - 5)
        self.card['active_profile'] = 'a2dp-sink'
        self.assertFalse(devices.recover())
        self.assertTrue(path.exists())
        self.command('set-card-profile', self.card['name'], 'headset-head-unit-msbc')
        self.assertTrue(devices.restore())
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        self.assertFalse(path.exists())
        # With the grace spent, a switch that never landed is dropped.
        devices, path = self.stale_intent(time=time.time() - 60)
        self.card['active_profile'] = 'a2dp-sink'
        self.assertFalse(devices.recover())
        self.assertFalse(path.exists())
        self.assertIsNone(devices.lease)

    def test_launch_recovery_treats_any_recorded_pid_as_stale_and_bad_records_as_unreadable(self):
        import os
        # Under the instance lock no other Untangle is alive, even if the pid was reused.
        for pid in (1, os.getpid(), os.getppid()):
            with self.subTest(pid=pid):
                devices, path = self.stale_intent(pid=pid, boot='original-boot')
                with patch('untangle.audio_devices.boot_id', return_value=None):
                    self.assertTrue(devices.recover())
                self.assertEqual(self.card['active_profile'], 'a2dp-sink')
                self.assertFalse(path.exists())
        for pid in (10**30, True, '12', 0, -5, None, 1.5):
            with self.subTest(pid=pid):
                devices, path = self.stale_intent(pid=pid)
                self.calls.clear()
                with self.assertLogs('recit.audio') as logs:
                    self.assertFalse(devices.recover())
                self.assertIn('"reason":"unreadable"', ' '.join(logs.output))
                self.assertFalse(path.exists())
                self.assertEqual(self.card['active_profile'], 'headset-head-unit-msbc')
                self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
        devices, path = self.stale_intent()
        path.write_text('{not json')
        with self.assertLogs('recit.audio') as logs:
            self.assertFalse(devices.recover())
        self.assertIn('"reason":"unreadable"', ' '.join(logs.output))
        self.assertFalse(path.exists())
        # An in-memory lease means this process owns the earbuds; leave the file.
        devices, path = self.stale_intent()
        devices.lease = ('bluez_card.test', 'a2dp-sink', 'headset-head-unit-msbc')
        self.assertFalse(devices.recover())
        self.assertTrue(path.exists())

    def test_launch_recovery_logs_restored_only_after_a_real_write(self):
        devices, path = self.stale_intent()
        reads = []
        def command(*args):
            if args[-1] == 'cards':
                reads.append(1)
                if len(reads) == 2:  # Changed between the check and the write.
                    self.card['active_profile'] = 'off'
            return self.command(*args)
        devices.command = command
        with self.assertLogs('recit.audio') as logs:
            self.assertFalse(devices.recover())
        output = ' '.join(logs.output)
        self.assertIn('restore.skipped', output)
        self.assertNotIn('recovery.restored', output)
        self.assertFalse(path.exists())
        self.assertEqual(self.card['active_profile'], 'off')

    def test_failed_intent_write_refuses_the_switch(self):
        devices, path = self.intent_devices()
        with patch('untangle.audio_devices.os.replace', side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(AudioDeviceError, 'did not switch'):
                devices.prepare(self.earbuds)
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        self.assertFalse(path.exists())
        self.assertIsNone(devices.lease)
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
        # Other microphones are unaffected, and the earbuds work once the write does.
        self.assertEqual(devices.prepare('brio'), 'brio')
        self.assertEqual(devices.prepare(self.earbuds), self.mic['name'])
        self.assertTrue(devices.restore())

    def test_automatic_classifies_the_exact_default_it_resolves(self):
        from untangle.audio_devices import EarbudMicDeferred
        self.data['sources'].append(self.mic)
        self.card['active_profile'] = 'headset-head-unit-msbc'
        reads = []
        def default_flips(*args):
            result = self.command(*args)
            if args[-1] == 'info':
                reads.append(1)
                self.data['info']['default_source_name'] = self.mic['name']
            return result
        self.devices.command = default_flips
        self.assertEqual(self.devices.prepare('default', switch_profile=False), 'brio')
        self.assertEqual(len(reads), 1)
        with self.assertRaises(EarbudMicDeferred):
            self.devices.prepare('default', switch_profile=False)
        # No system default input is an error, never a silent "microphone off".
        self.devices.command = self.command
        for missing in (None, ''):
            self.data['info']['default_source_name'] = missing
            for switch in (True, False):
                with self.subTest(missing=missing, switch=switch), \
                        self.assertRaisesRegex(AudioDeviceError, 'unavailable'):
                    self.devices.prepare('default', switch_profile=switch)

    def test_pending_restore_of_one_pair_allows_a_second_pair_without_a_switch(self):
        self.devices.prepare(self.earbuds)
        lease = self.devices.lease
        other = dict(self.card, name='bluez_card.other', index=19, active_profile='headset-head-unit-msbc')
        self.data['cards'] = [other]  # First pair gone; second already hands-free.
        self.data['sources'] = [dict(name='bluez_input.other.0', index=55, card=19)]
        self.assertFalse(self.devices.restore())
        self.assertEqual(self.devices.prepare('earbuds:bluez_card.other'), 'bluez_input.other.0')
        self.assertEqual(self.devices.lease, lease)
        # A second pair that needs a switch is refused accurately, without touching it.
        other['active_profile'] = 'a2dp-sink'
        self.calls.clear()
        with self.assertRaises(AudioDeviceError) as raised:
            self.devices.prepare('earbuds:bluez_card.other')
        self.assertNotIn('explicitly', str(raised.exception))
        self.assertIn('other earbuds', str(raised.exception))
        self.assertEqual(other['active_profile'], 'a2dp-sink')
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
        self.assertEqual(self.devices.lease, lease)

    def test_valid_record_survives_a_transient_read_error_and_is_retried(self):
        devices, path = self.stale_intent()
        with self.unreadable(path, OSError(errno.EIO, 'Input/output error', str(path))):
            self.assertFalse(devices.recover())
            self.assertTrue(devices.record_unread)
            self.assertFalse(devices.restore())  # Still unreadable: kept, and retried later.
            # An unread record may name other earbuds: never overwrite it with a new switch.
            self.card['active_profile'] = 'a2dp-sink'
            with self.assertRaisesRegex(AudioDeviceError, 'did not switch'):
                devices.prepare(self.earbuds)
            self.card['active_profile'] = 'headset-head-unit-msbc'
        self.assertTrue(path.exists(), 'valid intent was deleted after a read failure')
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
        self.assertTrue(devices.restore())  # The app's retry reads it now.
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        self.assertFalse(path.exists())
        self.assertFalse(devices.record_unread)

    def test_completed_restore_with_unlink_error_never_replays(self):
        devices, path = self.intent_devices()
        devices.prepare(self.earbuds)
        unlink = Path.unlink
        def forbid(target, *args, **kwargs):
            if target == path:
                raise PermissionError('read-only state directory')
            return unlink(target, *args, **kwargs)
        with patch.object(Path, 'unlink', forbid):
            self.assertTrue(devices.restore())
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        self.assertIsNone(devices.lease)
        self.assertEqual(json.loads(path.read_text()), {'done': True})
        # The user then picks hands-free themselves; the next launch must leave it.
        self.card['active_profile'] = 'headset-head-unit-msbc'
        self.calls.clear()
        later = AudioDevices(self.command, lambda: self.now, self.sleep, intent_path=path)
        self.assertFalse(later.recover())
        self.assertIsNone(later.lease)
        self.assertEqual(self.card['active_profile'], 'headset-head-unit-msbc')
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
        self.assertFalse(path.exists())
        # A truncated record is retired too.
        path.write_text('')
        self.assertFalse(later.recover())
        self.assertFalse(path.exists())

    def blocked_record_writes(self, path, truncate=False):
        """Patch the atomic retire, the in-place truncation and the delete to fail."""
        import contextlib, os
        open_file = os.open
        def deny_truncate(target, flags, *args, **kwargs):
            if Path(target) == path and flags & os.O_ACCMODE != os.O_RDONLY:
                raise denied(path)
            return open_file(target, flags, *args, **kwargs)
        stack = contextlib.ExitStack()
        stack.enter_context(patch('untangle.audio_devices.os.replace', side_effect=denied(path)))
        stack.enter_context(patch.object(Path, 'unlink', side_effect=denied(path)))
        if not truncate:
            stack.enter_context(patch('untangle.audio_devices.os.open', deny_truncate))
        return stack

    def test_retire_and_unlink_both_failing_is_logged_loudly_and_retried(self):
        devices, path = self.intent_devices()
        devices.prepare(self.earbuds)
        with self.blocked_record_writes(path), self.assertLogs('recit.audio', 'ERROR') as logs:
            self.assertTrue(devices.restore())
            self.assertTrue(devices.cleanup_pending)
            devices.restore()  # A retry that fails again does not log ERROR again.
        self.assertEqual(sum('intent.stuck' in line for line in logs.output), 1)
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        self.assertTrue(path.exists())
        devices.restore()  # The app's next retry, once storage works again.
        self.assertFalse(devices.cleanup_pending)
        self.assertFalse(path.exists())
        # The user then picks hands-free themselves; a later launch leaves it.
        self.card['active_profile'] = 'headset-head-unit-msbc'
        later = AudioDevices(self.command, lambda: self.now, self.sleep, intent_path=path)
        self.assertFalse(later.recover())
        self.assertEqual(self.card['active_profile'], 'headset-head-unit-msbc')

    def test_failed_retire_falls_back_to_truncating_the_record_in_place(self):
        from untangle.audio_debug import AudioTrace
        devices, path = self.intent_devices()
        devices.audio_trace = AudioTrace()
        devices.prepare(self.earbuds)
        with self.blocked_record_writes(path, truncate=True), self.assertLogs('recit.audio', 'WARNING') as logs:
            self.assertTrue(devices.restore())
        output = ' '.join(logs.output)
        self.assertIn('"reason":"retire_failed"', output)
        self.assertNotIn('intent.stuck', output)
        self.assertFalse(devices.cleanup_pending)
        self.assertEqual(path.read_text(), '')  # Empty reads as done.
        self.card['active_profile'] = 'headset-head-unit-msbc'
        later = AudioDevices(self.command, lambda: self.now, self.sleep, intent_path=path)
        self.assertFalse(later.recover())
        self.assertEqual(self.card['active_profile'], 'headset-head-unit-msbc')
        self.assertFalse(path.exists())
        # A failed retire alone is logged; the delete still removes the record.
        devices.prepare(self.earbuds)
        with patch('untangle.audio_devices.os.replace', side_effect=PermissionError('denied')):
            self.assertTrue(devices.restore())
        self.assertFalse(path.exists())

    def test_unwritable_state_directory_never_replays_a_finished_restore(self):
        import os
        if os.geteuid() == 0:
            self.skipTest('root ignores directory permissions')
        for file_mode, stuck in ((0o600, False), (0o400, True)):
            with self.subTest(file_mode=oct(file_mode)):
                self.card['active_profile'] = 'a2dp-sink'
                devices, path = self.intent_devices()
                devices.prepare(self.earbuds)
                self.addCleanup(path.parent.chmod, 0o700)
                path.chmod(file_mode)
                path.parent.chmod(0o500)
                if stuck:
                    with self.assertLogs('recit.audio', 'ERROR') as logs:
                        self.assertTrue(devices.restore())
                    self.assertIn('intent.stuck', ' '.join(logs.output))
                else:
                    self.assertTrue(devices.restore())
                    self.assertEqual(path.read_text(), '')
                self.assertEqual(devices.cleanup_pending, stuck)
                self.assertEqual(self.card['active_profile'], 'a2dp-sink')
                path.parent.chmod(0o700)
                devices.restore()
                self.assertFalse(devices.cleanup_pending)
                self.card['active_profile'] = 'headset-head-unit-msbc'
                later = AudioDevices(self.command, lambda: self.now, self.sleep, intent_path=path)
                self.assertFalse(later.recover())
                self.assertEqual(self.card['active_profile'], 'headset-head-unit-msbc')
                self.assertFalse(path.exists())

    def test_second_pair_never_cancels_the_first_pairs_late_switch_grace(self):
        devices, path = self.intent_devices()
        other = dict(self.card, name='bluez_card.other', index=19,
                     active_profile='headset-head-unit-cvsd')
        self.data['cards'].append(other)
        self.data['sources'].append(dict(name='bluez_input.other.0', index=55, card=19))
        delayed = []
        def timeout(*args):
            if args[:3] == ('set-card-profile', 'bluez_card.test', 'headset-head-unit-msbc'):
                delayed.append(args)
                raise AudioDeviceError('simulated pactl timeout')
            return self.command(*args)
        devices.command = timeout
        with self.assertRaisesRegex(AudioDeviceError, 'timeout'):
            devices.prepare(self.earbuds)
        self.assertFalse(devices.restore())  # Still a2dp: the switch may land.
        self.assertEqual(devices.prepare('earbuds:bluez_card.other'), 'bluez_input.other.0')
        self.now += 3
        self.assertFalse(devices.restore())  # The first pair's grace still holds.
        self.assertTrue(path.exists())
        self.command(*delayed[0])  # The late switch lands.
        self.assertTrue(devices.restore())
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        self.assertEqual(other['active_profile'], 'headset-head-unit-cvsd')
        self.assertFalse(path.exists())

    def unreadable(self, path, error=None):
        """Fail read-only opens of the record; writes and other files still work."""
        error = error or denied(path)
        open_file = os.open
        def fail_open(target, flags, *args, **kwargs):
            if Path(target) == path and flags & os.O_ACCMODE == os.O_RDONLY:
                raise error
            return open_file(target, flags, *args, **kwargs)
        return patch('untangle.audio_devices.os.open', fail_open)

    def test_unread_record_allows_earbuds_already_usable_in_handsfree(self):
        devices, path = self.stale_intent()
        self.card['active_profile'] = 'headset-head-unit-cvsd'  # mSBC is advertised too.
        with self.unreadable(path):
            self.assertFalse(devices.recover())
            self.assertEqual(devices.prepare(self.earbuds), self.mic['name'])
            self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
            self.assertIsNone(devices.lease)
            # A take that needs a switch stays refused, with the read error and a way out.
            self.card['active_profile'] = 'a2dp-sink'
            with self.assertRaises(AudioDeviceError) as raised:
                devices.prepare(self.earbuds)
        message = str(raised.exception)
        self.assertIn('did not switch', message)
        self.assertIn('(PermissionError: Permission denied)', message)
        self.assertEqual(message.count(str(path)), 1)  # Named once, not twice.
        self.assertIn("If you can't fix its permissions, quit Untangle, delete "
                      '~/.local/state/glint/bluetooth-profile.json, then relaunch.', message)
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
        self.assertTrue(path.is_file())

    def test_exit_does_not_wait_on_an_unread_record(self):
        devices, path = self.stale_intent()
        with self.unreadable(path):
            self.assertFalse(devices.recover())
            self.assertFalse(devices.restore(exiting=True))
        self.assertEqual(self.now, 0)
        self.assertTrue(path.is_file())

    def test_classification_and_resolution_share_one_source_listing(self):
        # Reconnect race: info names the earbud mic, the first listing omits
        # it and a second would include it. It must never be opened.
        self.data['info']['default_source_name'] = self.mic['name']
        self.card['active_profile'] = 'headset-head-unit-msbc'
        def appears_after_first_listing(*args):
            value = self.command(*args)
            if args[-1] == 'sources' and self.mic not in self.data['sources']:
                self.data['sources'].append(self.mic)
            return value
        self.devices.command = appears_after_first_listing
        from untangle.audio_devices import EarbudMicDeferred
        with self.assertRaises(EarbudMicDeferred):
            self.devices.prepare('default', switch_profile=False)
        self.assertEqual(sum(1 for c in self.calls if c[-1] == 'sources'), 1)
        # Same race for a wired default that leaves: no second listing reached.
        self.data['sources'] = [dict(name='buds.monitor', index=2)]
        self.data['info']['default_source_name'] = 'brio'
        self.calls.clear()
        def wired_returns(*args):
            value = self.command(*args)
            if args[-1] == 'sources':
                self.data['sources'].append(dict(name='brio', index=1))
            return value
        self.devices.command = wired_returns
        with self.assertRaisesRegex(AudioDeviceError, 'unavailable'):
            self.devices.prepare('default', switch_profile=False)
        self.assertEqual(sum(1 for c in self.calls if c[-1] == 'sources'), 1)

    def test_second_pair_already_on_cvsd_is_used_without_a_switch(self):
        devices, path = self.stale_intent()
        other = dict(self.card, name='bluez_card.other', index=19,
                     active_profile='headset-head-unit-cvsd')
        self.data['cards'] = [other]
        self.data['sources'] = [dict(name='bluez_input.other.0', index=55, card=19)]
        self.assertFalse(devices.recover())
        self.assertEqual(devices.prepare('earbuds:bluez_card.other'), 'bluez_input.other.0')
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
        self.assertEqual(devices.lease[0], 'bluez_card.test')
        self.assertTrue(path.is_file())
        # A hands-free profile without a microphone is not usable as is.
        other['profiles'] = dict(other['profiles'],
                                 **{'headset-head-unit-cvsd': dict(sources=0, available=True)})
        with self.assertRaisesRegex(AudioDeviceError, 'other earbuds'):
            devices.prepare('earbuds:bluez_card.other')
        self.assertEqual(other['active_profile'], 'headset-head-unit-cvsd')
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))

    def test_refusal_says_how_to_clear_earbuds_that_are_gone(self):
        devices, path = self.stale_intent()
        self.data['cards'] = []
        self.assertFalse(devices.recover())
        self.data['cards'] = [dict(self.card, name='bluez_card.other', index=19, active_profile='a2dp-sink')]
        with self.assertRaisesRegex(AudioDeviceError, 'If those earbuds are gone, quit Untangle, delete '
                                    r'~/\.local/state/glint/bluetooth-profile\.json, then relaunch\.'):
            devices.prepare('earbuds:bluez_card.other')

    def test_recovery_rejects_records_for_non_bluetooth_cards_or_profiles(self):
        for overrides in (dict(card='alsa_card.usb-DJI'), dict(target='a2dp-sink'),
                          dict(target='off'), dict(card='bluez_card.')):
            with self.subTest(**overrides):
                devices, path = self.stale_intent(**overrides)
                self.data['cards'] = [dict(self.card, name=overrides.get('card', self.card['name']))]
                self.calls.clear()
                with self.assertLogs('recit.audio') as logs:
                    self.assertFalse(devices.recover())
                self.assertIn('"reason":"unreadable"', ' '.join(logs.output))
                self.assertIsNone(devices.lease)
                self.assertFalse(path.exists())
                self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
        self.data['cards'] = [self.card]
        for target in ('headset-head-unit', 'handsfree_head_unit'):
            with self.subTest(target=target):
                devices, path = self.stale_intent(target=target)
                self.card['active_profile'] = target
                self.assertTrue(devices.recover())
                self.assertEqual(self.card['active_profile'], 'a2dp-sink')

    # Round 5: record safety. Directory permissions need a non-root uid.
    def skip_root(self):
        if os.geteuid() == 0:
            self.skipTest('root ignores directory permissions')

    def marked_devices(self, path, marker=None):
        marker = marker or path.parent.parent / 'config' / 'retired.json'
        return AudioDevices(self.command, lambda: self.now, self.sleep, intent_path=path,
                            retired_path=marker), marker

    def stuck_after_restore(self, devices, path):
        """Finish a restore while neither the record nor its directory is writable."""
        devices.prepare(self.earbuds)
        self.addCleanup(path.parent.chmod, 0o700)
        path.chmod(0o400)
        path.parent.chmod(0o500)
        with self.assertLogs('recit.audio', 'ERROR') as logs:
            self.assertTrue(devices.restore())
            self.assertTrue(devices.restore(exiting=True))  # Quit.
        self.assertTrue(devices.cleanup_pending)
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        return logs

    def test_truncate_fallback_never_follows_a_symlink_or_a_hard_link(self):
        self.skip_root()
        for kind in ('symlink', 'hardlink'):
            with self.subTest(kind=kind):
                self.card['active_profile'] = 'a2dp-sink'
                devices, path = self.intent_devices()
                devices.prepare(self.earbuds)
                other = path.parent.parent / 'unrelated.txt'
                if kind == 'symlink':
                    other.write_text('user data')
                    path.unlink()
                    path.symlink_to(other)
                else:
                    os.link(path, other)
                before = other.read_text()
                self.addCleanup(path.parent.chmod, 0o700)
                path.parent.chmod(0o500)  # The atomic retire and the removal both fail.
                with self.assertLogs('recit.audio', 'ERROR'):
                    self.assertTrue(devices.restore())
                self.assertEqual(other.read_text(), before)
                self.assertTrue(devices.cleanup_pending)  # Refused: cleanup still owed.
                path.parent.chmod(0o700)
                self.assertTrue(devices.restore())
                self.assertFalse(devices.cleanup_pending)
                self.assertFalse(path.exists() or path.is_symlink())
                self.assertEqual(other.read_text(), before)

    def test_a_symlinked_record_is_invalid_and_never_followed(self):
        devices, path = self.stale_intent()
        elsewhere = path.parent.parent / 'elsewhere.json'
        path.rename(elsewhere)
        path.symlink_to(elsewhere)
        record = elsewhere.read_text()
        self.assertFalse(devices.recover())
        self.assertIsNone(devices.lease)
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
        self.assertEqual(self.card['active_profile'], 'headset-head-unit-msbc')
        self.assertFalse(path.exists() or path.is_symlink())
        self.assertEqual(elsewhere.read_text(), record)

    def test_a_fifo_record_never_blocks_a_read_or_the_truncate_fallback(self):
        devices, path = self.intent_devices()
        path.parent.mkdir(parents=True)
        os.mkfifo(path)
        done = []
        def recover():
            done.append(devices.recover())  # Invalid: replaced by a retired record.
            os.mkfifo(path)
            done.append(devices._truncate_record())  # Refused: not a regular file.
        worker = threading.Thread(target=recover, daemon=True)
        worker.start()
        worker.join(2)
        self.assertFalse(worker.is_alive(), 'opening a FIFO record blocked')
        self.assertEqual(done, [False, False])
        self.assertIsNone(devices.lease)
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))

    def test_a_planted_temporary_symlink_is_replaced_not_followed(self):
        devices, path = self.intent_devices()
        path.parent.mkdir(parents=True)
        other = path.parent.parent / 'unrelated.txt'
        other.write_text('user data')
        path.with_name(path.name + '.tmp').symlink_to(other)
        self.assertEqual(devices.prepare(self.earbuds), self.mic['name'])
        self.assertEqual(other.read_text(), 'user data')
        self.assertEqual(json.loads(path.read_text())['target'], 'headset-head-unit-msbc')
        self.assertFalse(path.with_name(path.name + '.tmp').is_symlink())

    def test_stuck_record_never_replays_after_quit_once_a_retirement_is_marked(self):
        self.skip_root()
        devices, path = self.intent_devices()
        devices, marker = self.marked_devices(path)
        logs = self.stuck_after_restore(devices, path)
        self.assertEqual(sum('intent.stuck' in line for line in logs.output), 1)
        self.assertTrue(marker.is_file())
        self.assertFalse(devices.warn_unretired())  # The marker saved it: no exit ERROR.
        # After quitting, the user picks hands-free; storage is repaired; relaunch.
        self.card['active_profile'] = 'headset-head-unit-msbc'
        path.parent.chmod(0o700)
        self.calls.clear()
        later, _ = self.marked_devices(path, marker)
        self.assertFalse(later.recover())
        self.assertEqual([c for c in self.calls if c[0] == 'set-card-profile'], [])
        self.assertEqual(self.card['active_profile'], 'headset-head-unit-msbc')
        self.assertIsNone(later.lease)
        self.assertFalse(later.cleanup_pending)
        self.assertFalse(path.exists())
        self.assertFalse(marker.exists())  # Cleared once the record is gone.

    def test_marker_survives_a_relaunch_that_still_cannot_remove_the_record(self):
        self.skip_root()
        devices, path = self.intent_devices()
        devices, marker = self.marked_devices(path)
        self.stuck_after_restore(devices, path)
        self.card['active_profile'] = 'headset-head-unit-msbc'
        later, _ = self.marked_devices(path, marker)
        self.assertFalse(later.recover())  # Storage still broken at the next launch.
        self.assertTrue(later.cleanup_pending)
        self.assertIsNone(later.lease)
        self.assertTrue(marker.is_file())
        path.parent.chmod(0o700)
        self.assertTrue(later.restore())  # The retry finishes the cleanup only.
        self.assertFalse(later.cleanup_pending)
        self.assertFalse(path.exists() or marker.exists())
        self.assertEqual([c for c in self.calls if c[0] == 'set-card-profile'][-1][2],
                         'a2dp-sink')  # The original restore; nothing after it.
        self.assertEqual(self.card['active_profile'], 'headset-head-unit-msbc')

    def test_marker_only_matches_its_own_intent(self):
        self.skip_root()
        devices, path = self.intent_devices()
        devices, marker = self.marked_devices(path)
        self.stuck_after_restore(devices, path)
        path.parent.chmod(0o700)
        path.chmod(0o600)
        # A later take's record for the same pair (another switch) still restores.
        record = json.loads(path.read_text())
        path.write_text(json.dumps(dict(record, time=record['time'] + 60, id='later-take')))
        self.card['active_profile'] = 'headset-head-unit-msbc'
        later, _ = self.marked_devices(path, marker)
        self.assertTrue(later.recover())
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')

    def test_unwritable_marker_too_logs_one_error_at_exit(self):
        self.skip_root()
        devices, path = self.intent_devices()
        devices, marker = self.marked_devices(path)
        marker.parent.mkdir(parents=True)
        self.addCleanup(marker.parent.chmod, 0o700)
        marker.parent.chmod(0o500)
        self.stuck_after_restore(devices, path)
        self.assertFalse(marker.exists())
        with self.assertLogs('recit.audio', 'ERROR') as logs:
            self.assertTrue(devices.warn_unretired())
            self.assertTrue(devices.warn_unretired())
        self.assertEqual(len(logs.output), 1)
        self.assertIn('intent.unretired', logs.output[0])
        path.parent.chmod(0o700)
        marker.parent.chmod(0o700)
        devices.restore()
        self.assertFalse(devices.cleanup_pending)
        with patch('untangle.audio_debug.logger.log') as log:
            self.assertFalse(devices.warn_unretired())
        log.assert_not_called()

    def test_untraced_cleanup_retry_logs_intent_cleared(self):
        self.skip_root()
        devices, path = self.stale_intent()
        self.addCleanup(path.parent.chmod, 0o700)
        path.chmod(0o400)
        path.parent.chmod(0o500)
        with self.assertLogs('recit.audio', 'ERROR'):
            self.assertTrue(devices.recover())
        self.assertTrue(devices.cleanup_pending)
        self.assertIsNone(devices.audio_trace)
        path.parent.chmod(0o700)
        with self.assertLogs('recit.audio') as logs:
            self.assertTrue(devices.restore())
        self.assertFalse(devices.cleanup_pending)
        self.assertFalse(path.exists())
        self.assertIn('intent.cleared', ' '.join(logs.output))

    def test_release_capture_never_waits_on_a_parked_restore(self):
        devices, path = self.intent_devices()
        devices.prepare(self.earbuds)
        owner = devices.hold_capture(None)  # A DJI take: it never fences this pair.
        entered, resume = threading.Event(), threading.Event()
        def park(*args):
            if args[0] == 'set-card-profile' and args[2] == 'a2dp-sink':
                entered.set()
                resume.wait(3)
            return self.command(*args)
        devices.command = park
        restore = threading.Thread(target=devices.restore, daemon=True)
        restore.start()
        timer = threading.Timer(1, resume.set)
        self.addCleanup(timer.cancel)
        self.addCleanup(resume.set)
        try:
            self.assertTrue(entered.wait(1))
            started = time.monotonic()
            devices.release_capture(owner)
            self.assertLess(time.monotonic() - started, .2)
            timer.start()
        finally:
            resume.set()
            restore.join(3)
        self.assertFalse(restore.is_alive())
        self.assertIsNone(devices._capture_owner)  # The restore applied the release.
        self.assertIsNone(devices.lease)
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        # A newer capture held after a deferred release is never cleared by it.
        owner = devices.hold_capture(None)
        devices.release_capture(object())
        devices.restore()
        self.assertIs(devices._capture_owner, owner)

    def test_unsaved_record_uses_earbuds_already_usable_in_handsfree(self):
        devices, path = self.intent_devices()
        self.card['active_profile'] = 'headset-head-unit-cvsd'  # mSBC would be a switch.
        self.data['sources'].append(self.mic)
        with patch('untangle.audio_devices.os.replace', side_effect=denied(path)):
            self.assertEqual(devices.prepare(self.earbuds), self.mic['name'])
            self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
            self.assertIsNone(devices.lease)
            self.assertFalse(path.exists())
            self.card['active_profile'] = 'a2dp-sink'  # A real switch is still refused.
            with self.assertRaisesRegex(AudioDeviceError, 'did not switch'):
                devices.prepare(self.earbuds)
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))
        self.assertIsNone(devices.lease)

    def load_recorded_headset(self):
        # pactl snapshot taken read-only on PipeWire 1.0.3; address sanitized.
        self.data = json.loads((Path(__file__).parent / 'fixtures/oneplus-a2dp.json').read_text())
        self.card = self.data['cards'][0]
        self.mic.update(properties=dict(self.card['properties']))
        self.mic['name'] = 'bluez_input.AA_BB_CC_DD_EE_FF.0'
        self.mic['sample_specification'] = 's16le 1ch 16000Hz'
        self.earbuds = 'earbuds:' + self.card['name']

    def test_recorded_stale_disconnected_metadata_roundtrip(self):
        self.load_recorded_headset()
        with patch('untangle.audio_devices.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = self.data['bluez_connected']
            self.assertEqual(self.devices.prepare(self.earbuds), self.mic['name'])
            self.assertEqual(self.devices.resolve(self.mic['name']), self.mic['name'])
            # The live hands-free source is offered through its card's stable entry.
            self.assertIn(self.earbuds, [name for _, name in self.devices.microphones()])
            self.assertTrue(self.devices.restore())
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
        self.assertIsNone(self.devices.lease)

    def test_recorded_phantom_nodes_never_override_bluez_disconnect(self):
        self.load_recorded_headset()
        self.data['sources'] = [self.mic]
        self.card['properties']['api.bluez5.connection'] = 'connected'
        with patch('untangle.audio_devices.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = 'b false\n'
            with self.assertRaises(AudioDeviceError):
                self.devices.prepare(self.earbuds, timeout=.2)
            with self.assertRaises(AudioDeviceError):
                self.devices.resolve(self.mic['name'])
        self.assertIsNone(self.devices.lease)
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))

    def test_recorded_reconnect_before_and_during_profile_transition(self):
        self.load_recorded_headset()
        with patch('untangle.audio_devices.subprocess.run') as run:
            # Reconnect before switching, then a brief gap as HFP appears.
            run.side_effect = [SimpleNamespace(returncode=0, stdout=value) for value in
                ['b false', 'b true', 'b false', 'b true', 'b true', 'b true']]
            self.assertEqual(self.devices.prepare(self.earbuds, timeout=.5), self.mic['name'])
        self.assertAlmostEqual(self.now, .2)

    def test_recorded_already_handsfree_needs_no_profile_change(self):
        self.load_recorded_headset()
        self.card['active_profile'] = 'headset-head-unit-msbc'
        self.data['sources'] = [self.mic]
        with patch('untangle.audio_devices.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = 'b true'
            self.assertEqual(self.devices.prepare(self.earbuds), self.mic['name'])
        self.assertIsNone(self.devices.lease)
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))

    def test_bluez_query_failure_never_trusts_stale_metadata(self):
        self.load_recorded_headset()
        with patch('untangle.audio_devices.subprocess.run') as run:
            run.return_value.returncode = 1
            with self.assertRaisesRegex(AudioDeviceError, 'Cannot verify Bluetooth'):
                self.devices.prepare(self.earbuds)
            self.devices.lease = (self.card['name'], 'a2dp-sink', 'headset-head-unit-msbc')
            with self.assertRaises(AudioDeviceError):
                self.devices.restore()
            self.assertIsNotNone(self.devices.lease)
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))


    def cards_time_out(self, *args):
        if args[-1] == 'cards':
            raise AudioDeviceError('pactl list cards timed out')
        return self.command(*args)

    def test_card_lookup_failure_still_lists_other_microphones(self):
        # Main lists every input without reading cards; a card timeout must not hide them.
        self.data['sources'].append(dict(name='dji_receiver', index=5, description='DJI receiver'))
        self.devices.command = self.cards_time_out
        listed = self.devices.microphones()
        self.assertIn(('DJI receiver', 'dji_receiver'), listed)
        self.assertIn(('brio (system default)', 'brio'), listed)
        self.assertFalse(any(source.startswith('earbuds:') for _, source in listed))
        self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))

    def test_card_lookup_failure_omits_only_earbud_inputs_and_logs_it(self):
        self.data['sources'] += [self.mic, dict(name='dji_receiver', index=5, description='DJI receiver')]
        self.devices.command = self.cards_time_out
        with self.assertLogs('recit.audio', 'WARNING') as logs:
            listed = self.devices.microphones()
        self.assertEqual(listed, [('brio (system default)', 'brio'), ('DJI receiver', 'dji_receiver')])
        self.assertTrue(any('devices.cards_unavailable' in line for line in logs.output))

    def test_release_of_the_current_owner_survives_a_later_stale_release(self):
        devices, _ = self.intent_devices()
        devices.prepare(self.earbuds)
        stale = devices.hold_capture(self.card['name'])
        devices.release_capture(stale)
        current = devices.hold_capture(self.card['name'])
        entered, resume = threading.Event(), threading.Event()
        def holder():
            with devices._locked():
                entered.set()
                resume.wait(2)
        thread = threading.Thread(target=holder, daemon=True)
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            devices.release_capture(current)
            devices.release_capture(stale)  # Must not overwrite the pending release.
        finally:
            resume.set()
            thread.join(2)
        self.assertIsNone(devices._capture_owner)
        self.assertTrue(devices.restore())
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')

    def test_unreadable_marker_keeps_the_record_pending_and_never_replays(self):
        from untangle.audio_devices import read_regular
        self.skip_root()
        devices, path = self.intent_devices()
        devices, marker = self.marked_devices(path)
        self.stuck_after_restore(devices, path)
        path.parent.chmod(0o700)
        self.card['active_profile'] = 'headset-head-unit-msbc'  # Chosen after quitting.
        later, _ = self.marked_devices(path, marker)
        def marker_fails(target):
            if Path(target) == marker:
                raise OSError(errno.EIO, 'Input/output error')
            return read_regular(target)
        self.calls.clear()
        with patch('untangle.audio_devices.read_regular', marker_fails):
            self.assertFalse(later.recover())
            self.assertFalse(later.restore())  # The retry still cannot check it.
            self.card['active_profile'] = 'a2dp-sink'  # A switch is refused, naming the marker.
            with self.assertRaisesRegex(AudioDeviceError, str(marker)):
                later.prepare(self.earbuds)
            self.card['active_profile'] = 'headset-head-unit-msbc'
        self.assertTrue(later.record_unread)
        self.assertIsNone(later.lease)
        self.assertTrue(path.exists() and marker.exists())
        self.assertTrue(later.restore())  # Readable again: skipped as retired.
        self.assertEqual([c for c in self.calls if c[0] == 'set-card-profile'], [])
        self.assertEqual(self.card['active_profile'], 'headset-head-unit-msbc')
        self.assertFalse(later.record_unread)
        self.assertFalse(path.exists())

    def test_recovery_retry_logs_under_its_own_trace_not_a_later_check(self):
        from untangle.audio_debug import AudioTrace
        from untangle.audio_devices import read_regular
        devices, path = self.stale_intent()
        def intent_fails(target):
            if Path(target) == path:
                raise OSError(errno.EIO, 'Input/output error')
            return read_regular(target)
        with patch('untangle.audio_devices.read_regular', intent_fails), self.assertLogs('recit.audio'):
            self.assertFalse(devices.recover())
        self.assertTrue(devices.record_unread)
        check = devices.audio_trace = AudioTrace('check')
        with self.assertLogs('recit.audio') as logs:
            self.assertTrue(devices.restore())
        events = [json.loads(line.split('recit.audio ', 1)[1]) for line in logs.output]
        adopted = next(e for e in events if e['event'] == 'recovery.adopted')
        self.assertEqual(adopted['purpose'], 'recovery')
        self.assertNotEqual(adopted['session'], check.session)
        self.assertFalse(any(e['session'] == check.session for e in events))
        self.assertIs(devices.audio_trace, check)
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')

    def test_take_retrying_an_unread_recovery_adopts_it_under_the_recovery_trace(self):
        from untangle.audio_debug import AudioTrace
        from untangle.audio_devices import read_regular
        devices, path = self.stale_intent()
        def intent_fails(target):
            if Path(target) == path:
                raise OSError(errno.EIO, 'Input/output error')
            return read_regular(target)
        with patch('untangle.audio_devices.read_regular', intent_fails), self.assertLogs('recit.audio'):
            self.assertFalse(devices.recover())
        take = devices.audio_trace = AudioTrace('record')
        with self.assertLogs('recit.audio') as logs:
            devices.prepare(self.earbuds)
        events = [json.loads(line.split('recit.audio ', 1)[1]) for line in logs.output]
        adopted = next(e for e in events if e['event'] == 'recovery.adopted')
        self.assertEqual(adopted['purpose'], 'recovery')
        self.assertNotEqual(adopted['session'], take.session)
        selected = next(e for e in events if e['event'] == 'profile.selected')
        self.assertEqual(selected['session'], take.session)
        self.assertIs(devices.audio_trace, take)

if __name__ == '__main__':
    unittest.main()
