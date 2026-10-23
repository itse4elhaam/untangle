"""Synthetic offscreen name prompts, without app, device or network access."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from pathlib import Path
import unittest
from unittest.mock import Mock

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from untangle.naming import editable_recording_title
from untangle.naming_dialog import RecordingNameDialog, prompt_recording_name
from untangle.theme import stylesheet


class EditableTitleTests(unittest.TestCase):
    def test_generated_names_and_fallbacks(self):
        cases = {
            'Camera recording - 2026-10-22 at 11.30.mkv': 'Camera recording',
            'Résumé 演示 - 2026-10-22 at 11.30 (2).mp4': 'Résumé 演示',
            'RecIt-2026-10-22-113059-123456.mkv': 'Recording',
            'Glint-2026-10-22-113059.mp4': 'Recording',
            'My custom title (2).mp4': 'My custom title (2)',
            'RecIt-2026-99-22-113059.mp4': 'RecIt-2026-99-22-113059',
            'Demo - 2026-10-22 at 99.30.mkv': 'Demo - 2026-10-22 at 99.30',
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(editable_recording_title(Path(filename)), expected)


class NamingDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def make_dialog(self, rename=None, **kwargs):
        rename = rename if rename is not None else Mock(return_value=Path('/synthetic/Résumé.mp4'))
        dialog = RecordingNameDialog(None, Path('/synthetic/Screen recording - 2026-10-22 at 11.30.mp4'),
                                     rename, **kwargs)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        dialog.show()
        dialog.activateWindow()
        self.qt.processEvents()
        return dialog, rename

    def test_prefill_selection_copy_and_theme_layout(self):
        for new_recording in (False, True):
            dialog, rename = self.make_dialog(new_recording=new_recording)
            self.assertEqual(dialog.windowTitle(), 'Name your recording' if new_recording else 'Rename recording')
            self.assertEqual(dialog.cancel_button.text(), 'Keep current name' if new_recording else 'Cancel')
            self.assertEqual(dialog.save_button.text(), 'Save name')
            self.assertEqual(dialog.name_edit.selectedText(), 'Screen recording')
            self.assertTrue(dialog.name_edit.hasFocus())
            for theme in ('light', 'dark'):
                dialog.setStyleSheet(stylesheet(theme))
                dialog.resize(420, dialog.sizeHint().height())
                self.qt.processEvents()
                self.assertEqual(dialog.width(), 420)
                self.assertTrue(dialog.rect().contains(dialog.save_button.geometry()))
                self.assertTrue(dialog.rect().contains(dialog.name_edit.geometry()))
                self.assertFalse(dialog.grab().isNull())
            rename.assert_not_called()
            dialog.close()

    def test_save_button_and_enter_return_callback_path_once(self):
        for enter in (False, True):
            dialog, rename = self.make_dialog()
            dialog.name_edit.setText('  Résumé  ')
            if enter:
                QTest.keyClick(dialog.name_edit, Qt.Key_Return)
            else:
                QTest.mouseClick(dialog.save_button, Qt.LeftButton)
            self.assertEqual(dialog.result(), QDialog.Accepted)
            self.assertEqual(dialog.saved_path, Path('/synthetic/Résumé.mp4'))
            self.assertFalse(dialog.isVisible())
            dialog.accept()
            rename.assert_called_once_with('Résumé')

    def test_blank_disables_save_and_explains_validation(self):
        dialog, rename = self.make_dialog()
        for text in ('', '  ', '\t'):
            dialog.name_edit.setText(text)
            self.assertFalse(dialog.save_button.isEnabled())
            self.assertTrue(dialog.error_label.isVisible())
            self.assertIn('Enter a recording name', dialog.error_label.text())
            QTest.keyClick(dialog.name_edit, Qt.Key_Return)
            dialog.accept()
        rename.assert_not_called()
        self.assertTrue(dialog.isVisible())
        dialog.name_edit.setText('A title')
        self.assertTrue(dialog.save_button.isEnabled())
        self.assertFalse(dialog.error_label.isVisible())

    def test_errors_preserve_input_and_allow_retry(self):
        for error in (OSError('Permission denied'), ValueError('Use a name without / folders')):
            rename = Mock(side_effect=[error, Path('/synthetic/fixed.mkv')])
            dialog, _ = self.make_dialog(rename)
            dialog.name_edit.setText('My exact title')
            QTest.keyClick(dialog.name_edit, Qt.Key_Return)
            self.assertEqual(rename.call_count, 1)
            self.assertTrue(dialog.isVisible())
            self.assertEqual(dialog.name_edit.text(), 'My exact title')
            self.assertIn(str(error), dialog.error_label.text())
            self.assertTrue(dialog.error_label.isVisible())
            self.assertTrue(dialog.save_button.isEnabled())
            self.assertIsNone(dialog.saved_path)
            dialog.name_edit.setText('fixed')
            self.assertFalse(dialog.error_label.isVisible())
            QTest.mouseClick(dialog.save_button, Qt.LeftButton)
            self.assertEqual(dialog.saved_path, Path('/synthetic/fixed.mkv'))
            self.assertEqual(rename.call_count, 2)

    def test_reentrant_save_does_not_call_callback_twice(self):
        def rename(title):
            self.assertFalse(dialog.save_button.isEnabled())
            dialog.accept()
            return Path('/synthetic/result.mp4')
        callback = Mock(side_effect=rename)
        dialog, _ = self.make_dialog(callback)
        dialog.accept()
        callback.assert_called_once()
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_wrapped_error_fits_without_clipping(self):
        rename = Mock(side_effect=PermissionError(
            'The folder is read-only. Choose Cancel to keep the current name.'))
        dialog, _ = self.make_dialog(rename)
        dialog.setStyleSheet(stylesheet('dark'))
        dialog.accept()
        self.qt.processEvents()
        label = dialog.error_label
        self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
        self.assertTrue(dialog.rect().contains(dialog.save_button.geometry()))

    def test_cancel_escape_and_window_close_never_rename(self):
        for action in ('cancel', 'escape', 'close'):
            dialog, rename = self.make_dialog(new_recording=True)
            dialog.name_edit.setText('Unsaved edit')
            if action == 'cancel':
                QTest.mouseClick(dialog.cancel_button, Qt.LeftButton)
            elif action == 'escape':
                QTest.keyClick(dialog.name_edit, Qt.Key_Escape)
            else:
                dialog.close()
            self.assertFalse(dialog.isVisible())
            self.assertEqual(dialog.result(), QDialog.Rejected)
            self.assertIsNone(dialog.saved_path)
            dialog.accept()
            rename.assert_not_called()

    def test_prompt_modal_return_contract(self):
        for save in (True, False):
            rename = Mock(return_value=Path('/synthetic/result.mp4'))
            def respond():
                dialog = self.qt.activeModalWidget()
                if save:
                    dialog.name_edit.setText('result')
                    dialog.save_button.click()
                else:
                    dialog.reject()
            QTimer.singleShot(0, respond)
            result = prompt_recording_name(None, Path('/synthetic/original.mp4'), rename)
            self.assertEqual(result, Path('/synthetic/result.mp4') if save else None)
            self.assertEqual(rename.call_count, int(save))
