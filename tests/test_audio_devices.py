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

    def test_launch_recovery_skips_and_drops_unsafe_intents(self):
        cases = (('owner_alive', True, lambda: None),
                 ('profile_changed', False, lambda: self.card.update(active_profile='off')),
                 ('card_missing', False, lambda: self.data.update(cards=[])),
                 ('earbud_mic_capturing', False,
                  lambda: self.data.update({'source-outputs': [dict(source=42)]})))
        for reason, alive, arrange in cases:
            with self.subTest(reason=reason):
                devices, path = self.stale_intent()
                self.data.update({'cards': [self.card], 'source-outputs': []})
                arrange()
                before = self.card['active_profile']
                self.calls.clear()
                kill = patch('untangle.audio_devices.os.kill',
                             side_effect=None if alive else ProcessLookupError)
                with kill, self.assertLogs('recit.audio') as logs:
                    self.assertFalse(devices.recover())
                self.assertIn(f'"reason":"{reason}"', ' '.join(logs.output))
                self.assertFalse(path.exists())
                self.assertEqual(self.card['active_profile'], before)
                self.assertFalse(any(c[0] == 'set-card-profile' for c in self.calls))

    def test_launch_recovery_treats_another_boot_as_dead_and_bad_records_as_unreadable(self):
        devices, path = self.stale_intent(pid=1, boot='an-earlier-boot')
        self.assertTrue(devices.recover())
        self.assertEqual(self.card['active_profile'], 'a2dp-sink')
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
