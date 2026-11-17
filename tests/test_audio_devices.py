import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from untangle.audio_devices import AudioDeviceError, AudioDevices, handsfree_profile, on_card


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
        read_text = Path.read_text
        def fail(target, *args, **kwargs):
            if target == path:
                raise OSError('transient I/O error')
            return read_text(target, *args, **kwargs)
        with patch.object(Path, 'read_text', fail):
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

    def test_retire_and_unlink_both_failing_is_logged_loudly(self):
        devices, path = self.intent_devices()
        devices.prepare(self.earbuds)
        with patch('untangle.audio_devices.os.replace', side_effect=PermissionError('denied')), \
                patch.object(Path, 'unlink', side_effect=PermissionError('denied')), \
                self.assertLogs('recit.audio', 'WARNING') as logs:
            self.assertTrue(devices.restore())
        self.assertIn('intent.stuck', ' '.join(logs.output))

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


if __name__ == '__main__':
    unittest.main()
