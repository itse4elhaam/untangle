"""Microphone checks use synthetic OBS float planes and mocked playback only."""
import ctypes as C
import math
from pathlib import Path
import tempfile
import time
import unittest
import wave
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QUrl
from untangle.audio_check import AudioCheck, AudioData, AudioSample
from untangle.engine import Engine
import test_app


def feed(sample, value=.25, muted=False, frames=4800):
    left = (C.c_float * frames)(*[value * math.sin(i / 7) for i in range(frames)])
    right = (C.c_float * frames)(*[value / 2 for i in range(frames)])
    data = AudioData()
    data.frames = frames
    data.data[0] = C.cast(left, C.POINTER(C.c_ubyte))
    data.data[1] = C.cast(right, C.POINTER(C.c_ubyte))
    sample.callback(None, None, C.pointer(data), muted)


class SampleChecks(unittest.TestCase):
    def test_real_callback_to_wave_samples_and_mute(self):
        for muted in (False, True):
            with tempfile.TemporaryDirectory() as root:
                sample = AudioSample(MagicMock(), 123)
                feed(sample, muted=muted)
                sample.detach()
                path = Path(root) / 'sample.wav'
                peak = sample.save(path)
                with wave.open(str(path), 'rb') as audio:
                    self.assertEqual((audio.getnchannels(), audio.getframerate(), audio.getnframes()), (2, 48000, 4800))
                    data = audio.readframes(4800)
                    self.assertEqual(any(data), not muted)
                self.assertEqual(peak == 0, muted)

    def test_bounded_and_empty(self):
        sample = AudioSample(MagicMock(), 123)
        with self.assertRaisesRegex(RuntimeError, 'No microphone signal'):
            sample.save('unused.wav')
        for _ in range(60):
            feed(sample)
        self.assertEqual(sample.frames, 240000)
        sample.detach()

    def test_engine_only_opens_microphone_and_same_filters(self):
        engine = Engine.__new__(Engine)
        engine._closed = False
        engine._output = None
        engine._obs = MagicMock()
        engine._sources = []
        engine.release_audio = MagicMock()
        engine._source = MagicMock(return_value=123)
        engine._microphone_filters = MagicMock()
        engine.verify_audio_route = MagicMock(return_value='exact.headset.source')
        engine.begin_audio_check('exact.headset.source', False)
        engine._source.assert_called_once_with('pulse_input_capture', 'RecIt microphone check', {'device_id': 'exact.headset.source'})
        engine._microphone_filters.assert_called_once_with(123, False)
        engine.end_audio_check()
        engine._obs.obs_source_remove_audio_capture_callback.assert_called_once()


class DialogChecks(unittest.TestCase):
    def setUp(self):
        self.engine, self.devices = MagicMock(), MagicMock()
        self.devices.prepare.return_value = 'exact.headset.source'
        self.devices.restore.return_value = True
        self.sample = AudioSample(MagicMock(), 123)
        feed(self.sample)
        self.engine.begin_audio_check.return_value = self.sample
        # Every playback call is mocked, so synthetic samples cannot reach speakers.
        self.player_patch = patch('untangle.audio_check.QMediaPlayer')
        self.player_type = self.player_patch.start()
        self.dialog = AudioCheck(self.engine, self.devices, 'default', True, 'Default microphone')

    def wait(self):
        deadline = time.monotonic() + 4
        while self.dialog.worker and time.monotonic() < deadline:
            test_app.qt.processEvents()
            time.sleep(.001)
        test_app.qt.processEvents()
        self.assertIsNone(self.dialog.worker)

    def tearDown(self):
        self.wait()
        self.dialog.reject()
        self.wait()
        self.dialog.deleteLater()
        self.player_patch.stop()

    def capture(self):
        self.dialog.start_check()
        self.wait()
        self.assertTrue(self.dialog.capturing)
        self.dialog.finish_capture()
        self.wait()

    def test_prepare_capture_release_then_explicit_play(self):
        order = []
        self.engine.end_audio_check.side_effect = lambda: order.append('release')
        self.devices.restore.side_effect = lambda: order.append('restore') or True
        self.dialog.player.play.side_effect = lambda: order.append('play')
        self.capture()
        self.devices.prepare.assert_called_once_with('default', switch_profile=False)
        self.engine.begin_audio_check.assert_called_once_with('exact.headset.source', True)
        self.assertEqual(order, ['release'])
        self.dialog.player.play.assert_not_called()
        self.dialog.prepare_playback()
        self.wait()
        # The check never switches earbuds; the app's retry owns any restore.
        self.assertEqual(order, ['release', 'play'])
        self.assertTrue(self.dialog.path.is_file())
        self.dialog.reject()
        self.assertFalse(self.dialog.path.exists())

    def test_friendly_label_tooltip_correlated_summaries_and_retry_session(self):
        from untangle.audio_debug import AudioTrace
        from test_audio_debug import records
        self.devices.source_label = 'OnePlus Buds 4'
        self.engine.audio_status.return_value = dict(source='exact.headset.source', packets=3,
            nonzero_packets=2, packet_age=.01, peak_db=-18., input_peak_db=-18., state='signal')
        with self.assertLogs('recit.audio') as logs:
            self.capture()
        rows = records(logs)
        names = [row['event'] for row in rows]
        expected = ['session.start', 'check.started', 'check.health', 'check.telemetry',
                    'check.stopped', 'check.validation']
        self.assertEqual([names.index(name) for name in expected],
                         sorted(names.index(name) for name in expected))
        trace = self.dialog.audio_trace
        self.assertIsInstance(trace, AudioTrace)
        self.assertIs(self.devices.audio_trace, trace)
        self.assertIs(self.engine.audio_trace, trace)
        self.assertEqual({row['session'] for row in rows}, {trace.session})
        self.assertEqual(self.dialog.device.text(), 'Microphone: OnePlus Buds 4')
        self.assertEqual(self.dialog.device.toolTip(), 'exact.headset.source')
        self.assertFalse(self.dialog.summary_timer.isActive())
        self.assertEqual([r['outcome'] for r in rows if r['event'] == 'check.telemetry'], [None, 'finished'])
        self.capture()
        self.assertNotEqual(self.dialog.audio_trace.session, trace.session)

    def test_sample_save_and_play_never_wait_on_an_earlier_earbud_restore(self):
        # The app's retry owns an earlier earbud take's restore; the check never calls it.
        self.capture()
        self.assertFalse(self.dialog.failed_capture)
        self.assertTrue(self.dialog.path.is_file())
        self.assertIn('Play sample', self.dialog.status.text())
        self.dialog.prepare_playback()
        self.dialog.player.play.assert_called_once()
        self.devices.restore.assert_not_called()

    def test_dji_check_never_waits_on_a_background_earbud_restore(self):
        # A prior earbud take is owed a restore; the app's background retry is
        # parked inside a slow pactl call while it holds the restore lock.
        import threading
        import test_audio_devices
        pulse = test_audio_devices.AudioDevicesTests()
        pulse.setUp()
        pulse.devices.prepare(pulse.earbuds)
        pulse.data['sources'].append(dict(name='dji_receiver', index=5))
        pulse.data['info']['default_source_name'] = 'dji_receiver'
        self.dialog.devices = pulse.devices
        entered, allow = threading.Event(), threading.Event()
        self.addCleanup(allow.set)
        restorer = threading.Thread(target=pulse.devices.restore)
        def parked(*args):
            if threading.current_thread() is restorer and args[-1] == 'cards':
                entered.set()
                allow.wait(3)
            return pulse.command(*args)
        pulse.devices.command = parked
        restorer.start()
        self.assertTrue(entered.wait(1))
        started = time.monotonic()
        self.dialog.start_check()
        self.assertLess(time.monotonic() - started, .5, 'Quick check start waited on the restore')
        self.wait()
        self.assertTrue(self.dialog.capturing)
        self.dialog.finish_capture()
        self.wait()
        self.assertTrue(self.dialog.path.is_file(), 'sample save waited on the restore')
        self.assertTrue(restorer.is_alive())
        self.assertEqual(pulse.card['active_profile'], 'headset-head-unit-msbc')
        allow.set()
        restorer.join(2)
        self.assertEqual(pulse.card['active_profile'], 'a2dp-sink')
        self.assertIsNone(pulse.devices.lease)

    def test_dji_sample_plays_when_a_prior_earbud_take_left_its_card_disconnected(self):
        import test_audio_devices
        pulse = test_audio_devices.AudioDevicesTests()
        pulse.setUp()
        pulse.devices.prepare(pulse.earbuds)
        pulse.data['cards'] = []
        pulse.data['sources'] = [dict(name='dji_receiver', index=5)]
        pulse.data['info']['default_source_name'] = 'dji_receiver'
        self.dialog.devices = pulse.devices
        self.capture()
        self.assertTrue(self.dialog.path.is_file())
        self.assertNotIn('Another app', self.dialog.status.text())
        self.dialog.prepare_playback()
        self.wait()
        self.dialog.player.play.assert_called_once()
        self.assertIsNotNone(pulse.devices.lease)  # Still owed; the app retries it.
        self.assertFalse([c for c in pulse.calls if c[0] == 'set-card-profile' and c[2] == 'a2dp-sink'])

    def test_silence_guidance_without_automatic_playback(self):
        self.sample.blocks.clear()
        self.sample.frames = 0
        feed(self.sample, muted=True)
        self.capture()
        self.assertIn('Check mute', self.dialog.status.text())
        self.dialog.player.play.assert_not_called()

    def test_empty_sample_can_retry_and_stop_clears_playback(self):
        self.sample.blocks.clear()
        self.sample.frames = 0
        self.capture()
        self.assertIn('No microphone signal', self.dialog.status.text())
        self.assertTrue(self.dialog.record.isEnabled())
        self.assertFalse(self.dialog.failed_capture)
        feed(self.sample)
        self.capture()
        self.dialog.stop_check()
        self.dialog.player.stop.assert_called()


    def test_earbud_mic_shows_deferred_explanation_and_retry_never_switches(self):
        from untangle.audio_devices import EarbudMicDeferred
        self.devices.prepare.side_effect = EarbudMicDeferred()
        for _ in range(2):  # A later Retry gets the same answer; nothing is sticky.
            self.dialog.start_check()
            self.wait()
            self.engine.begin_audio_check.assert_not_called()
            self.assertIn('Earbud mic switches on when recording starts.', self.dialog.status.text())
            self.assertIn('cannot test this microphone', self.dialog.status.text())
            self.assertEqual(self.dialog.record.text(), 'Record sample')
            self.assertTrue(self.dialog.record.isEnabled())
            self.assertFalse(self.dialog.failed_capture)
        self.assertEqual([c.kwargs for c in self.devices.prepare.call_args_list],
                         [dict(switch_profile=False)] * 2)
        # The check never fences restores: it never opens a Bluetooth mic.
        self.devices.hold_capture.assert_not_called()
        self.devices.release_capture.assert_not_called()

    def test_dji_sample_with_fake_devices_never_touches_earbud_card(self):
        # Earbuds are the default output; the DJI receiver is the chosen input.
        from test_audio_devices import AudioDevicesTests
        pulse = AudioDevicesTests()
        pulse.setUp()
        pulse.data['sources'].append(dict(name='dji_receiver', index=5))
        for selection, default in (('dji_receiver', 'brio'), ('default', 'dji_receiver')):
            with self.subTest(selection=selection):
                pulse.data['info']['default_source_name'] = default
                self.dialog.reject()
                self.wait()
                self.dialog.deleteLater()
                self.dialog = AudioCheck(self.engine, pulse.devices, selection, True, 'DJI receiver')
                self.engine.begin_audio_check.reset_mock()
                sample = AudioSample(MagicMock(), 123)
                feed(sample)
                self.engine.begin_audio_check.return_value = sample
                self.capture()
                self.engine.begin_audio_check.assert_called_once_with('dji_receiver', True)
                self.assertIn('Sample contains sound', self.dialog.status.text())
                self.dialog.prepare_playback()
                self.wait()
                self.dialog.player.play.assert_called()
        self.assertEqual(pulse.card['active_profile'], 'a2dp-sink')
        self.assertIsNone(pulse.devices.lease)
        self.assertFalse([c for c in pulse.calls if c[0] == 'set-card-profile'])

    def test_prepare_error_releases_without_waiting_on_restore(self):
        self.devices.prepare.side_effect = RuntimeError('Headset disconnected')
        self.dialog.start_check()
        self.wait()
        self.assertIn('Headset disconnected', self.dialog.status.text())
        self.engine.end_audio_check.assert_called_once()
        self.devices.release_capture.assert_not_called()
        self.devices.restore.assert_not_called()  # The check never switches; the app retries.
        self.dialog.player.play.assert_not_called()

    def test_close_during_preparation_waits_and_never_plays(self):
        import threading
        ready = threading.Event()
        self.devices.prepare.side_effect = lambda *_, **__: ready.wait(2) and 'exact'
        self.dialog.start_check()
        self.dialog.reject()
        self.assertTrue(self.dialog.closing)
        ready.set()
        self.wait()
        self.engine.end_audio_check.assert_called_once()
        self.devices.restore.assert_not_called()
        self.dialog.player.play.assert_not_called()
        self.assertFalse(self.dialog.path.parent.exists())

    def test_idle_and_off_never_open_microphone(self):
        self.engine.begin_audio_check.assert_not_called()
        self.devices.prepare.assert_not_called()
        self.dialog.selection = None
        self.dialog.start_check()
        self.devices.prepare.assert_not_called()
        self.assertIn('off', self.dialog.status.text())


class RestoreTraceChecks(unittest.TestCase):
    """A Quick check during a background restore keeps each operation's own trace."""

    def test_dji_check_and_parked_restore_log_to_their_own_sessions(self):
        import json
        import threading
        import test_audio_devices
        from untangle.audio_devices import AudioDeviceError
        pulse = test_audio_devices.AudioDevicesTests()
        pulse.setUp()
        self.addCleanup(pulse.doCleanups)
        devices, _ = pulse.stale_intent()
        pulse.data['sources'].append(dict(name='dji_receiver', index=5))
        pulse.data['info']['default_source_name'] = 'dji_receiver'
        pulse.data['source-outputs'] = [dict(source=42)]
        self.assertFalse(devices.recover())  # Deferred: the earbud mic is in use.
        entered, resume = threading.Event(), threading.Event()
        def park(*args):
            if args[0] == 'set-card-profile':
                entered.set()
                if not resume.wait(3):
                    raise AudioDeviceError('test restore timed out')
            return pulse.command(*args)
        devices.command = park
        engine = MagicMock()
        sample = AudioSample(MagicMock(), 123)
        feed(sample)
        engine.begin_audio_check.return_value = sample
        engine.verify_audio_route.return_value = 'dji_receiver'
        with patch('untangle.audio_check.QMediaPlayer'):
            check = AudioCheck(engine, devices, 'default', True, 'Automatic microphone')
        self.addCleanup(check.deleteLater)
        self.addCleanup(check.reject)
        pulse.data['source-outputs'] = []
        retry = threading.Thread(target=devices.restore, daemon=True)
        retry.start()
        try:
            self.assertTrue(entered.wait(1))
            with self.assertLogs('recit.audio') as logs:
                check.start_check()
                deadline = time.monotonic() + 1
                while check.worker and time.monotonic() < deadline:
                    test_app.qt.processEvents()
                    time.sleep(.001)
                self.assertIsNone(check.worker)
                self.assertTrue(retry.is_alive())
                resume.set()
                retry.join(1)
        finally:
            resume.set()
            retry.join(1)
        self.assertTrue(check.capturing)
        engine.begin_audio_check.assert_called_once_with('dji_receiver', True)
        events = [json.loads(line.split('recit.audio ', 1)[1]) for line in logs.output]
        session = check.audio_trace.session
        self.assertEqual(next(e['session'] for e in events if e['event'] == 'source.resolved'), session)
        restore = [e for e in events if e['event'].startswith(('restore.', 'recovery.'))]
        self.assertTrue(restore)
        self.assertTrue(all(e['session'] != session for e in restore))
        self.assertIs(devices.audio_trace, check.audio_trace)  # The restore left it alone.
        self.assertEqual(pulse.card['active_profile'], 'a2dp-sink')


class EntryChecks(unittest.TestCase):
    setUp = test_app.AppChecks.setUp
    tearDown = test_app.AppChecks.tearDown

    def test_entry_guards_and_lock(self):
        window = self.window
        window.audio_devices = MagicMock()
        window.audio_devices.lease = None
        window.audio_devices.record_unread = False
        window.audio_devices.cleanup_pending = False
        with patch('untangle.audio_check.AudioCheck') as dialog_type:
            for flag in ('recording', 'counting', 'busy', 'preparing_audio'):
                setattr(window, flag, True)
                window.open_audio_check()
                setattr(window, flag, False)
            dialog_type.assert_not_called()
        with patch('untangle.audio_check.QMediaPlayer'):
            window.open_audio_check()
            self.assertTrue(window.busy)
            self.assertFalse(window.audio_check_button.isEnabled())
            self.assertFalse(window.record_button.isEnabled())
            self.assertFalse(window.controls_panel.isHidden())
            self.assertFalse(window.microphone.isEnabled())
            window.audio_check_dialog.reject()
            self.assertIsNone(window.audio_check_dialog)
            self.assertFalse(window.busy)
            self.assertFalse(window.controls_panel.isHidden())


if __name__ == '__main__':
    unittest.main()
