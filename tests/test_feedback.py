"""Feedback regressions with real Qt widgets and synthetic recording data."""
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

import test_ui_clickthrough as ui
from untangle import app


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.case = ui.ClearlineClickthrough()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.w = self.case.window

    def test_settings_can_be_inspected_during_a_take_without_changing_capture(self):
        w = self.w
        w.recording = True
        w.lock_controls(True)
        w.engine.reset_mock()
        self.case.open_settings()
        self.assertTrue(w.settings_lock_notice.isVisible())
        for control in (w.quality, w.shape, w.position, w.microphone,
                        w.audio_check_button, w.storage_settings_button):
            self.assertFalse(control.isEnabled())
        self.case.close_settings()
        w.engine.configure.assert_not_called()
        w.engine.start.assert_not_called()
        w.engine.stop.assert_not_called()
        w.recording = False
        w.lock_controls(False)
        self.case.open_settings()
        self.assertTrue(w.quality.isEnabled())
        self.assertFalse(w.settings_lock_notice.isVisible())

    def test_closed_dropdown_wheel_scrolls_settings_without_changing_choice(self):
        self.case.open_settings()
        scroll = self.w.settings_dialog.findChild(QScrollArea)
        self.w.settings_dialog.resize(560, 480)
        for focused in (False, True):
            self.case.reveal_setting(self.w.quality)
            combo = self.w.quality
            if focused:
                combo.setFocus()
            else:
                self.w.settings_dialog.setFocus()
            index = combo.currentIndex()
            before = scroll.verticalScrollBar().value()
            point = combo.rect().center()
            QTest.wheelEvent(self.w.settings_dialog.windowHandle(),
                combo.mapTo(self.w.settings_dialog, point), QPoint(0, 120))
            QApplication.processEvents()
            self.assertEqual(combo.currentIndex(), index)
            self.assertLess(scroll.verticalScrollBar().value(), before)
        # Intentional popup/keyboard selection must still work.
        self.case.reveal_setting(combo)
        self.case.choose(combo, (1920, 1080))

    def snapshot_take(self, upload):
        self.w.upload_this_take.setChecked(upload)
        self.case.click(self.w.record_button)
        self.assertTrue(self.w.counting)
        self.assertFalse(self.w.upload_this_take.isEnabled())
        self.w.count_timer.stop()
        # Synthetic save below stands in for capture; never start the engine.
        self.w.counting = False

    def test_upload_choice_is_per_take_and_uses_the_saved_file_after_naming(self):
        w = self.w
        for consent in (False, True):
            with self.subTest(consent=consent):
                w.prefs.setValue('auto_upload', not consent)
                self.snapshot_take(consent)
                path = self.case.root / f'take-{consent}.mp4'
                path.write_bytes(b'synthetic take')
                unrelated = self.case.root / 'another.mp4'
                unrelated.write_bytes(b'other take')
                def name(parent, original, rename, **kwargs):
                    w.set_last(unrelated)
                    w.prefs.setValue('auto_upload', not consent)
                    return rename(f'Named {consent}')
                with patch.object(app, 'prompt_recording_name', side_effect=name), \
                        patch.object(w, 'upload') as upload:
                    w.finish_save(path, '')
                    self.assertEqual(upload.call_count, int(consent))
                    if consent:
                        self.assertEqual(w.last_file.name, f'Named {consent}.mp4')
                self.assertEqual(w.upload_this_take.isChecked(), not consent)

    def test_changed_file_cannot_inherit_take_upload_consent(self):
        self.snapshot_take(True)
        path = self.case.root / 'take.mp4'
        path.write_bytes(b'synthetic take')
        def replace_file(*args, **kwargs):
            path.write_bytes(b'a different recording replaced this take')
        with patch.object(app, 'prompt_recording_name', side_effect=replace_file), \
                patch.object(self.w, 'upload') as upload:
            self.w.finish_save(path, '')
            upload.assert_not_called()

    def test_ticking_upload_is_remembered_for_later_takes(self):
        self.w.prefs.setValue('auto_upload', False)
        self.w.upload_this_take.setChecked(True)
        self.assertTrue(self.w.prefs.value('auto_upload', type=bool))
        self.case.click(self.w.record_button)
        QTest.keyClick(self.w, Qt.Key_Escape)
        self.case.wait_for(lambda: not self.w.counting, 'Countdown did not cancel')
        self.assertTrue(self.w.upload_this_take.isChecked())
        self.w.ready_after_save()
        self.assertTrue(self.w.upload_this_take.isChecked())

    def test_unticking_upload_keeps_later_takes_local(self):
        self.w.prefs.setValue('auto_upload', True)
        self.w.upload_this_take.setChecked(True)
        self.w.upload_this_take.setChecked(False)
        self.assertFalse(self.w.prefs.value('auto_upload', type=bool))
        self.w.lock_controls(True)
        self.w.lock_controls(False)
        self.assertFalse(self.w.upload_this_take.isChecked())
        self.snapshot_take(False)
        path = self.case.root / 'local-only.mp4'
        path.write_bytes(b'synthetic take')
        with patch.object(app, 'prompt_recording_name', return_value=None), \
                patch.object(self.w, 'upload') as upload:
            self.w.finish_save(path, '')
            upload.assert_not_called()
        self.assertFalse(self.w.upload_this_take.isChecked())

    def test_camera_take_warns_when_upload_is_on(self):
        for mode, upload, warned in (('camera', True, True), ('camera', False, False), ('screen', True, False)):
            with self.subTest(mode=mode, upload=upload):
                self.w.mode = mode
                self.w._take_auto_upload = upload
                self.assertEqual('Upload to Loom is on for this camera take' in self.w.preflight_summary(), warned)
        self.w._take_auto_upload = False
