"""Smaller recording files are the default for every mode, with an opt-out. No capture."""
import unittest
from unittest.mock import patch
from untangle import app
import test_app as fixture


class RecordingCompressionTests(unittest.TestCase):
    setUp = fixture.AppChecks.setUp
    tearDown = fixture.AppChecks.tearDown

    def test_default_is_on_and_opt_out_is_preserved(self):
        self.assertTrue(self.window.compact_recordings.isChecked())
        self.window.compact_recordings.setChecked(False)
        self.window.close()
        self.window = app.Window()
        self.assertFalse(self.window.compact_recordings.isChecked())

    def test_screen_and_camera_recordings_follow_the_setting(self):
        w = self.window
        w.selected_source = None
        w.configuration_valid = True
        for mode in ('camera', 'screen'):
            for enabled in (True, False):
                with self.subTest(mode=mode, enabled=enabled):
                    w.mode = mode
                    w.recording = False
                    w.compact_recordings.setChecked(enabled)
                    w.engine.start.reset_mock()
                    w.lock_controls(True)
                    with patch.object(w, 'show_bubble'):
                        w.begin_recording()
                    w.engine.start.assert_called_once()
                    self.assertEqual(w.engine.start.call_args.kwargs['compact'], enabled)
                    self.assertTrue(w.recording)
                    self.assertFalse(w.compact_recordings.isEnabled())

    def test_compressed_camera_recording_can_still_switch_to_screen_presentation(self):
        w = self.window
        w.selected_source = None
        w.configuration_valid = True
        w.mode = 'camera'
        w.compact_recordings.setChecked(True)
        w.lock_controls(True)
        with patch.object(w, 'show_bubble'):
            w.begin_recording()
        self.assertNotIn('original recording mode', w.status.text())
        allowed = not w.wayland_session() and bool(w.camera.currentData())
        self.assertTrue(allowed, 'fixture must offer a camera so the check is not vacuous')
        self.assertTrue(w.presentation_button.isEnabled())
        self.assertTrue(w.tray_presentation.isEnabled())


if __name__ == '__main__':
    unittest.main()
