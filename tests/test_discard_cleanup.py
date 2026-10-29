"""Discarding takes and cleaning up the library, with synthetic files only."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from untangle.naming import has_automatic_name
from untangle.naming_dialog import RecordingNameDialog
from untangle.recordings import Recordings
from untangle.upload_store import UploadStore
import test_app

qt = QApplication.instance() or QApplication([])
YES = patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.Yes)
CANCEL = patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.Cancel)


class AutomaticNameTests(unittest.TestCase):
    def test_dated_names_are_automatic_and_chosen_names_are_not(self):
        for name in ('Camera recording - 2026-10-29 at 16.09.mp4', 'Screen recording - 2026-10-23 at 12.32 (2).mkv',
                     'Mozilla Firefox - 2026-10-23 at 12.32.mp4', 'RecIt-2026-10-22-103300-692857.mp4'):
            self.assertTrue(has_automatic_name(name), name)
        for name in ('A1R Reel.mp4', 'how we work take 6 (last).mp4', 'test.mp4'):
            self.assertFalse(has_automatic_name(name), name)


class LibraryCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.named = [self.root / 'A1R Reel.mp4', self.root / 'how we work take 2.mp4']
        self.unnamed = [self.root / 'Camera recording - 2026-10-29 at 16.09.mp4',
                        self.root / 'RecIt-2026-10-22-103300-692857.mp4']
        for index, path in enumerate(self.named + self.unnamed):
            path.write_bytes(b'synthetic')
            os.utime(path, (index + 1, index + 1))
        self.store = UploadStore(self.root / 'uploads.json')
        self.library = Recordings(self.root, upload_store=self.store)
        self.library.player.setAudioOutput(None)
        self.deleted = []
        self.library.recording_deleted.connect(self.deleted.append)

    def tearDown(self):
        self.library.reject()
        self.library.deleteLater()
        qt.processEvents()
        self.temp.cleanup()

    def select(self, *paths):
        self.library.files.clearSelection()
        for index in range(self.library.files.count()):
            item = self.library.files.item(index)
            if Path(item.data(Qt.UserRole)) in paths:
                self.library.files.setCurrentItem(item, QItemSelectionModel.Select)

    def test_delete_unnamed_keeps_everything_you_named(self):
        self.assertEqual(self.library.delete_unnamed_button.text(), 'Delete unnamed (2)…')
        with CANCEL:
            self.library.delete_unnamed_button.click()
        self.assertTrue(all(path.exists() for path in self.unnamed))
        with YES as confirm:
            self.library.delete_unnamed_button.click()
        for path in self.unnamed:
            self.assertIn(path.name, confirm.call_args.args[2])
        self.assertFalse(any(path.exists() for path in self.unnamed))
        self.assertTrue(all(path.exists() for path in self.named))
        self.assertEqual(sorted(self.deleted), sorted(map(str, self.unnamed)))
        self.assertEqual(self.library.files.count(), 2)
        self.assertIn('Deleted 2 recordings', self.library.message.text())
        self.assertFalse(self.library.delete_unnamed_button.isEnabled())

    def test_delete_unnamed_ignores_search_filter(self):
        self.library.search.setText('A1R')
        with YES:
            self.library.delete_unnamed()
        self.assertFalse(any(path.exists() for path in self.unnamed))

    def test_multi_select_deletes_all_selected(self):
        self.select(self.named[1], self.unnamed[0])
        self.assertEqual(self.library.delete.text(), 'Delete 2')
        with YES as confirm:
            self.library.delete.click()
        self.assertIn('2 recordings', confirm.call_args.args[1])
        self.assertFalse(self.named[1].exists())
        self.assertFalse(self.unnamed[0].exists())
        self.assertTrue(self.named[0].exists())
        self.assertEqual(self.library.delete.text(), 'Delete')

    def test_bulk_delete_reports_partial_failure(self):
        self.select(*self.unnamed)
        unlink = Path.unlink
        def flaky(path, *args, **kwargs):
            if path == self.unnamed[0]:
                raise PermissionError('protected fixture')
            unlink(path, *args, **kwargs)
        with YES, patch.object(Path, 'unlink', flaky):
            self.library.delete_selected()
        self.assertTrue(self.unnamed[0].exists())
        self.assertFalse(self.unnamed[1].exists())
        self.assertIn('Could not delete 1', self.library.message.text())

    def test_busy_blocks_bulk_delete(self):
        self.library.deletion_blocked = lambda path: True
        self.library.update_actions()
        self.select(*self.unnamed)
        self.assertFalse(self.library.delete.isEnabled())
        with patch('PySide6.QtWidgets.QMessageBox.question') as confirm:
            self.library.delete_unnamed()
        confirm.assert_not_called()
        self.assertTrue(all(path.exists() for path in self.unnamed))


class NameDialogDiscardTests(unittest.TestCase):
    def test_discard_button_confirms_then_deletes(self):
        calls = []
        dialog = RecordingNameDialog(None, Path('/tmp/Camera recording.mp4'), lambda title: None,
                                     new_recording=True, discard=lambda: calls.append(True))
        self.assertFalse(dialog.discard_button.isHidden())
        with CANCEL:
            dialog.discard_button.click()
        self.assertEqual(calls, [])
        with YES:
            dialog.discard_button.click()
        self.assertEqual(calls, [True])
        self.assertTrue(dialog.discarded)
        dialog.deleteLater()

    def test_rename_only_dialog_has_no_discard(self):
        dialog = RecordingNameDialog(None, Path('/tmp/x.mp4'), lambda title: None)
        self.assertTrue(dialog.discard_button.isHidden())
        dialog.deleteLater()


class RecorderDiscardTests(unittest.TestCase):
    def setUp(self):
        self.case = test_app.AppChecks('test_visible_identity_uses_untangle_and_bundled_mark')
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.window, self.root = self.case.window, self.case.root

    def test_discard_while_recording_deletes_instead_of_saving(self):
        w = self.window
        w.recording = True
        take = self.root / 'Camera recording - 2026-10-29 at 16.09.mkv'
        take.write_bytes(b'synthetic take')
        with CANCEL, patch.object(w, 'stop') as stop:
            w.discard_recording()
        stop.assert_not_called()
        with YES, patch.object(w, 'stop') as stop:
            w.discard_recording()
        stop.assert_called_once_with()
        self.assertTrue(w._discarding)
        with patch.object(w, 'remux') as remux, patch.object(test_app.glint, 'prompt_recording_name') as prompt:
            w.stopped(str(take), '')
        remux.assert_not_called()
        prompt.assert_not_called()
        self.assertFalse(take.exists())
        self.assertFalse(w.busy)
        self.assertFalse(w._discarding)
        self.assertIn('discarded', w.status.text())
        self.assertTrue(w.discard_saved_button.isHidden())

    def test_discard_from_name_prompt_skips_auto_upload(self):
        w = self.window
        path = self.root / 'Camera recording - 2026-10-29 at 16.09.mp4'
        path.write_bytes(b'saved')
        w.prefs.setValue('auto_upload', True)
        def prompt(parent, original, rename, *, new_recording, discard):
            discard()
            return None
        with patch.object(test_app.glint, 'prompt_recording_name', side_effect=prompt), \
                patch.object(w, 'upload') as upload:
            w.finish_save(path, '')
        upload.assert_not_called()
        self.assertFalse(path.exists())
        self.assertIn('discarded', w.status.text())
        self.assertTrue(w.discard_saved_button.isHidden())

    def test_discard_after_save_follows_the_saved_file(self):
        w = self.window
        path = self.root / 'Camera recording - 2026-10-29 at 16.09.mp4'
        path.write_bytes(b'saved')
        w.finish_save(path, '')
        self.assertFalse(w.discard_saved_button.isHidden())
        with CANCEL:
            w.discard_saved_button.click()
        self.assertTrue(path.exists())
        with YES:
            w.discard_saved_button.click()
        self.assertFalse(path.exists())
        self.assertTrue(w.discard_saved_button.isHidden())
        self.assertIsNone(w.last_file)

    def test_discard_after_save_is_refused_during_upload(self):
        w = self.window
        path = self.root / 'kept.mp4'
        path.write_bytes(b'saved')
        w.finish_save(path, '')
        w._upload_active = True
        with patch('PySide6.QtWidgets.QMessageBox.question') as confirm:
            w.discard_saved_recording()
        confirm.assert_not_called()
        self.assertTrue(path.exists())
        w._upload_active = False


if __name__ == '__main__':
    unittest.main()
