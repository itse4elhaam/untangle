"""Recorder themes and inline audio-check ownership with mocked devices only."""
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPalette
from untangle.theme import THEMES
import test_app


class RecorderThemeChecks(unittest.TestCase):
    setUp = test_app.AppChecks.setUp
    tearDown = test_app.AppChecks.tearDown

    def test_theme_persists_and_restyles_existing_library_and_meter(self):
        w = self.window
        w.open_recordings()
        for name in ('dark', 'light'):
            w.recordings.theme_choice.setCurrentIndex(w.recordings.theme_choice.findData(name))
            self.assertEqual(w.prefs.value('theme'), name)
            self.assertEqual(w.theme_choice.currentData(), name)
            self.assertEqual(test_app.qt.property('untangleTheme'), name)
            self.assertEqual(test_app.qt.palette().color(QPalette.Window).name(), THEMES[name]['canvas'].lower())
            w.microphone_meter.show_status(dict(state='silent', peak_db=float('-inf')), 'Synthetic input')
            self.assertIn(THEMES[name]['warning'], w.microphone_meter.level.styleSheet())
        self.assertIn('Silent', w.microphone_meter.message.text())
        w.back_to_recorder()
        w.set_theme('invalid preference')
        self.assertEqual(w.theme_choice.currentData(), 'light')

    def test_summary_changes_and_meter_survives_camera_expansion(self):
        w = self.window
        self.assertTrue(all(not edit.isChecked() for edit in w.setup_sections))
        w.set_mode('camera', configure=False)
        self.assertIn('Camera only', w.capture_caption.text())
        w.desktop_audio.setChecked(True)
        self.assertTrue(w.desktop_audio.isChecked())
        w.show()
        w.focus_button.setChecked(True)
        test_app.qt.processEvents()
        self.assertTrue(w.controls_panel.isHidden())
        self.assertTrue(w.microphone_meter.isVisible())
        w.set_mode('screen', configure=False)
        self.assertFalse(w.focus_button.isChecked())
        self.assertIn('Entire screen', w.capture_caption.text())

    def test_output_options_can_open_for_zoom_while_recording(self):
        w = self.window
        w.set_mode('screen', configure=False)
        w.show()
        w.lock_controls(True)
        w.recording = True
        w.zoom_button.setEnabled(True)
        w.setup_sections[-1].click()
        test_app.qt.processEvents()
        self.assertTrue(w.zoom_button.isVisible())
        self.assertFalse(w.quality.isEnabled())
        self.assertFalse(w.camera.isEnabled())
        w.zoom_button.click()
        self.assertTrue(w.zoom_motion.enabled)
        w.zoom_timer.stop()

    def test_inline_audio_check_keeps_setup_and_does_not_reparent_preview_or_start_capture(self):
        w = self.window
        w.show()
        parent = w.preview.parentWidget()
        with patch('untangle.audio_check.QMediaPlayer'):
            w.open_audio_check()
            sheet = w.audio_check_dialog
            for name in ('light', 'dark'):
                w.set_theme(name)
                for size in ((960, 760), (1120, 840)):
                    w.resize(*size)
                    test_app.qt.processEvents()
                    self.assertTrue(sheet.isVisible())
                    self.assertFalse(sheet.isWindow())
                    self.assertEqual(sheet.windowFlags() & Qt.WindowType_Mask, Qt.Widget)
                    self.assertIs(w.preview.parentWidget(), parent)
                    self.assertGreaterEqual(w.preview.height(), 220)
                    self.assertTrue(w.controls_panel.isVisible())
                    self.assertTrue(w.rect().contains(sheet.mapTo(w, sheet.rect().bottomRight())))
                    self.assertTrue(w.rect().contains(w.library_button.mapTo(w, QPoint())))
            w.engine.begin_audio_check.assert_not_called()
            sheet.player.play.assert_not_called()
            sheet.done_button.click()
            test_app.qt.processEvents()
        self.assertIsNone(w.audio_check_dialog)
        self.assertFalse(w.busy)
        self.assertTrue(w.controls_panel.isVisible())
        self.assertIs(w.preview.parentWidget(), parent)
