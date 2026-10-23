"""Camera-off controls without opening capture devices."""
import unittest
from unittest.mock import Mock
from untangle.engine import Engine, EngineError
import test_app as fixture


class CameraToggleTests(unittest.TestCase):
    setUp = fixture.AppChecks.setUp
    tearDown = fixture.AppChecks.tearDown

    def test_camera_off_releases_camera_mode_without_screen_capture(self):
        w = self.window
        w.set_mode('camera', configure=False)
        previous = w.camera.currentData()
        w.engine.reset_mock()
        w.camera_toggle.click()
        self.assertIsNone(w.camera.currentData())
        self.assertEqual(w.camera_toggle.text(), 'Off')
        self.assertEqual(w.mode, 'camera')
        self.assertFalse(w.configure_timer.isActive())
        self.assertFalse(w.record_button.isEnabled())
        w.engine.clear_video.assert_called_once_with()
        w.engine.configure.assert_not_called()
        w.engine.detach_camera_preview.assert_called()
        self.assertFalse(w.camera_zoom.isEnabled())
        self.assertEqual(w.prefs.value('camera'), 'Camera off')
        w.camera_toggle.click()
        self.assertEqual(w.camera.currentData(), previous)
        self.assertEqual(w.camera_toggle.text(), 'On')
        self.assertTrue(w.configure_timer.isActive())

    def test_screen_capture_continues_without_camera(self):
        w = self.window
        w.set_mode('screen', configure=False)
        w.engine.reset_mock()
        w.camera_toggle.click()
        self.assertEqual(w.mode, 'screen')
        self.assertTrue(w.record_button.isEnabled())
        self.assertIsNone(w.engine.configure.call_args.kwargs['camera'])
        self.assertFalse(w.engine.configure.call_args.kwargs['floating_camera'])

    def test_camera_off_restores_preference_and_blocks_toggle_while_recording(self):
        w = self.window
        w.camera_toggle.click()
        w.camera.setCurrentIndex(1)
        w.prefs.setValue('camera', 'Camera off')
        w.restore_preferences()
        self.assertIsNone(w.camera.currentData())
        self.assertFalse(w.camera_toggle.isChecked())
        w.recording = True
        w.lock_controls(True)
        self.assertFalse(w.camera_toggle.isEnabled())
        w.toggle_camera(True)
        self.assertIsNone(w.camera.currentData())


class ClearVideoTests(unittest.TestCase):
    def test_clears_sources_preserving_audio_and_rejects_active_output(self):
        engine = Engine.__new__(Engine)
        engine._closed = False
        engine._output = None
        engine._clear_scene = Mock()
        engine.clear_video()
        engine._clear_scene.assert_called_once_with(preserve_audio=True)
        engine._clear_scene.reset_mock()
        engine._output = object()
        with self.assertRaises(EngineError):
            engine.clear_video()
        engine._clear_scene.assert_not_called()
