"""Compression is opt-in and never reaches screen recordings. No capture."""
import unittest
from unittest.mock import patch
from untangle import app
import test_app as fixture


class CameraCompressionTests(unittest.TestCase):
    setUp = fixture.AppChecks.setUp
    tearDown = fixture.AppChecks.tearDown

    def test_default_is_off_and_camera_opt_in_is_preserved(self):
        self.assertFalse(self.window.compact_recordings.isChecked())
        self.window.compact_recordings.setChecked(True)
        self.window.close()
        self.window = app.Window()
        self.assertTrue(self.window.compact_recordings.isChecked())

    def test_only_opted_in_camera_recordings_use_compression(self):
        w = self.window
        w.selected_source = None
        w.configuration_valid = True
        for mode, enabled, expected in (('camera', False, False),
                                        ('camera', True, True),
                                        ('screen', True, False),
                                        ('screen', False, False)):
            with self.subTest(mode=mode, enabled=enabled):
                w.mode = mode
                w.recording = False
                w.compact_recordings.setChecked(enabled)
                w.engine.start.reset_mock()
                w.lock_controls(True)
                with patch.object(w, 'show_bubble'):
                    w.begin_recording()
                w.engine.start.assert_called_once()
                self.assertEqual(w.engine.start.call_args.kwargs['compact'], expected)
                self.assertTrue(w.recording)
                self.assertFalse(w.compact_recordings.isEnabled())
                if expected:
                    self.assertFalse(w.presentation_button.isEnabled())
                    self.assertFalse(w.tray_presentation.isEnabled())
                    w.engine.set_presentation.reset_mock()
                    w.toggle_presentation()
                    w.engine.set_presentation.assert_not_called()
                    self.assertIn('original recording mode', w.status.text())
