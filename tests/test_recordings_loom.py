"""Loom library fixtures with mocked media, browser, dialogs, and no network."""
from contextlib import ExitStack
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt, QUrl, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from untangle.recordings import Recordings
from untangle.upload_store import UploadStore


qt = QApplication.instance() or QApplication([])
LOOM_URL = 'https://www.loom.com/share/0123456789abcdef0123456789abcdef'


class LoomLibraryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.root = Path(self.temp)
        self.directory = self.root / 'recordings'
        self.directory.mkdir()
        self.path = self.directory / 'Local project title.mp4'
        self.path.write_bytes(b'synthetic recording placeholder')
        self.state_path = self.root / 'state' / 'uploads.json'
        self.store = UploadStore(self.state_path)
        self.blocked = False
        self.player = MagicMock()
        self.player.source.return_value = QUrl()
        self.player.position.return_value = self.player.duration.return_value = 0
        self.audio = MagicMock()
        self.audio.volume.return_value = .5
        self.audio.isMuted.return_value = False
        self.stack.enter_context(patch('untangle.recordings.QMediaPlayer', return_value=self.player))
        self.stack.enter_context(patch('untangle.recordings.QAudioOutput', return_value=self.audio))
        self.stack.enter_context(patch('untangle.recordings.shutil.which', return_value=None))
        self.browser = self.stack.enter_context(patch('untangle.recordings.QDesktopServices.openUrl'))
        self.dialogs = []
        self.stack.callback(self.close_dialogs)
        self.dialog = self.new_dialog()

    def close_dialogs(self):
        for dialog in self.dialogs:
            dialog.reject()
            dialog.close()
            dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qt.processEvents()

    def new_dialog(self, store=None):
        dialog = Recordings(self.directory, deletion_blocked=lambda path: self.blocked,
            upload_store=self.store if store is None else store)
        self.dialogs.append(dialog)
        dialog.files.setCurrentRow(0)
        return dialog

    def uploaded(self, **fields):
        self.store.update(self.path, status='uploaded', url=LOOM_URL,
            title='Upstream Loom title', **fields)
        self.dialog.update_actions()

    def test_persisted_link_and_upstream_title_survive_reload_without_renaming_local_file(self):
        self.uploaded(visibility_warning='Loom workspace visibility applies.')
        restored = self.new_dialog(UploadStore(self.state_path))
        self.assertEqual(restored.selected_path(), self.path)
        self.assertEqual(restored.selected_title.text(), 'Local project title')
        self.assertEqual(restored.loom_title.text(), 'Loom title: Upstream Loom title')
        self.assertIn('Uploaded to Loom', restored.files.currentItem().text())
        self.assertIn('Loom workspace visibility applies.', restored.loom_status.text())
        self.assertTrue(restored.open_loom.isEnabled())
        self.assertTrue(restored.copy_loom.isEnabled())
        restored.refresh()
        self.assertEqual(restored.selected_path(), self.path)
        self.assertEqual(restored.files.currentItem().text().count('Uploaded to Loom'), 1)
        self.assertNotIn('Uploaded to Loom', restored.metadata.text())
        self.player.play.assert_not_called()

    def test_interrupted_upload_restores_as_uncertain_with_retry_and_duplicate_warning(self):
        self.store.update(self.path, status='processing', url=LOOM_URL)
        restored = self.new_dialog(UploadStore(self.state_path))
        self.assertIn('Loom upload needs checking', restored.files.currentItem().text())
        self.assertIn('duplicate', restored.loom_status.text())
        self.assertEqual(restored.upload.text(), 'Retry upload')
        self.assertTrue(restored.upload.isEnabled())
        self.assertTrue(restored.check_loom.isEnabled())

    def test_click_open_copy_and_check_link_emit_only_the_selected_path(self):
        self.uploaded()
        checked = []
        self.dialog.check_remote_requested.connect(checked.append)
        self.dialog.open_loom.click()
        self.browser.assert_called_once_with(QUrl(LOOM_URL))
        self.dialog.copy_loom.click()
        self.assertEqual(qt.clipboard().text(), LOOM_URL)
        self.dialog.check_loom.click()
        self.assertEqual(checked, [str(self.path)])
        self.assertEqual(self.store.get(self.path)['status'], 'uploaded')
        self.dialog.copy.click()
        self.assertEqual(qt.clipboard().text(), str(self.path))

    def test_missing_or_filtered_selection_and_remote_deletion_never_use_stale_link(self):
        self.uploaded()
        qt.clipboard().setText('unchanged')
        self.dialog.search.setText('no matching local filename')
        self.dialog.open_selected_loom()
        self.dialog.copy_selected_loom()
        self.assertFalse(self.dialog.open_loom.isEnabled())
        self.assertEqual(qt.clipboard().text(), 'unchanged')
        self.dialog.search.clear()
        self.dialog.files.setCurrentRow(0)
        self.store.mark_remote_deleted(self.path)
        self.dialog.update_actions()
        self.assertIn('Deleted from Loom', self.dialog.files.currentItem().text())
        self.assertIn('still on this computer', self.dialog.loom_status.text())
        self.dialog.open_selected_loom()
        self.dialog.copy_selected_loom()
        self.assertTrue(self.path.is_file())
        self.assertFalse(self.dialog.open_loom.isEnabled())
        self.assertTrue(self.dialog.upload.isEnabled())
        self.uploaded()
        self.path.unlink()
        self.dialog.open_selected_loom()
        self.dialog.copy_selected_loom()
        self.dialog.check_selected_loom()
        self.assertFalse(self.dialog.open_loom.isEnabled())
        self.assertFalse(self.dialog.copy_loom.isEnabled())
        self.assertEqual(self.dialog.loom_status.text(), '')
        self.assertEqual(qt.clipboard().text(), 'unchanged')
        self.path.write_bytes(b'a different local recording at the same filename')
        self.dialog.update_actions()
        self.assertFalse(self.dialog.open_loom.isEnabled())
        self.assertIn('Not uploaded to Loom', self.dialog.files.currentItem().text())
        self.browser.assert_not_called()

    def test_only_safe_loom_links_are_opened_or_copied(self):
        for url in ('file:///tmp/local', 'javascript:alert(1)', 'http://loom.com/share/id',
                'https://loom.com.evil.example/share/id', 'https://user@loom.com/share/id',
                'https://loom.com:8443/share/id', 'https://loom.com/share/', '<a href="evil">'):
            with self.subTest(url=url):
                self.store.update(self.path, status='uploaded', url=url)
                qt.clipboard().setText('unchanged')
                self.dialog.update_actions()
                self.dialog.open_selected_loom()
                self.dialog.copy_selected_loom()
                self.assertFalse(self.dialog.open_loom.isEnabled())
                self.assertFalse(self.dialog.copy_loom.isEnabled())
                self.assertEqual(qt.clipboard().text(), 'unchanged')
        self.browser.assert_not_called()

    def test_upload_states_update_rows_and_selected_details_without_playback(self):
        other = self.directory / 'Other local recording.mkv'
        other.touch()
        self.dialog.refresh(self.path)
        for status, text in (('uploading', 'Uploading to Loom'), ('processing', 'Processing in Loom'),
                ('uploaded', 'Uploaded to Loom'), ('failed', 'Loom upload failed'),
                ('uncertain', 'Loom upload needs checking'), ('deleted', 'Deleted from Loom')):
            with self.subTest(status=status):
                self.store.update(self.path, status=status, error='Useful fixture detail')
                self.store.update(other, status='failed')
                self.dialog.update_actions()
                self.assertIn(text, self.dialog.files.currentItem().text())
                self.assertIn(text, self.dialog.loom_status.text())
                self.assertIn('Useful fixture detail', self.dialog.loom_status.text())
                row = next(self.dialog.files.item(i) for i in range(self.dialog.files.count())
                    if self.dialog.files.item(i).data(Qt.UserRole) == str(other))
                self.assertIn('Loom upload failed', row.text())
                self.assertEqual(self.dialog.upload.isEnabled(), status not in ('uploading', 'processing'))
        self.player.play.assert_not_called()

    def test_failed_retry_and_repeat_upload_confirmation(self):
        requested = []
        self.dialog.upload_requested.connect(requested.append)
        self.store.update(self.path, status='failed', error='Synthetic failure')
        self.dialog.update_actions()
        self.assertEqual(self.dialog.upload.text(), 'Retry upload')
        self.dialog.upload.click()
        self.assertEqual(requested, [str(self.path)])
        for status in ('uploaded', 'uncertain'):
            self.store.update(self.path, status=status, url=LOOM_URL)
            with patch('untangle.recordings.QMessageBox.question', return_value=QMessageBox.Cancel) as confirm:
                self.dialog.upload_selected()
                self.assertIn('another copy', confirm.call_args.args[2])
            self.assertEqual(len(requested), 1 if status == 'uploaded' else 2)
            with patch('untangle.recordings.QMessageBox.question', return_value=QMessageBox.Yes):
                self.dialog.upload_selected()
        self.assertEqual(requested, [str(self.path)] * 3)

    def test_forget_confirms_local_only_effect_and_persists_without_deleting_recording(self):
        self.uploaded()
        with patch('untangle.recordings.QMessageBox.question', return_value=QMessageBox.Cancel):
            self.dialog.forget_loom.click()
        self.assertEqual(self.store.get(self.path)['url'], LOOM_URL)
        with patch('untangle.recordings.QMessageBox.question', return_value=QMessageBox.Yes) as confirm:
            self.dialog.forget_loom.click()
        self.assertIn('on Loom is unchanged', confirm.call_args.args[2])
        self.assertTrue(self.path.is_file())
        self.assertEqual(UploadStore(self.state_path).get(self.path), {})
        self.assertFalse(self.dialog.open_loom.isEnabled())
        self.assertIn('on Loom is unchanged', self.dialog.message.text())
        self.browser.assert_not_called()

    def test_local_rename_moves_link_and_delete_removes_metadata(self):
        self.uploaded()
        renamed = self.directory / 'Renamed locally.mp4'
        with patch('untangle.recordings.prompt_recording_name', side_effect=lambda parent, path, rename: rename('Renamed locally')):
            self.dialog.rename_selected()
        self.assertEqual(self.dialog.selected_path(), renamed)
        restored = UploadStore(self.state_path)
        self.assertEqual(restored.get(self.path), {})
        self.assertEqual(restored.get(renamed)['url'], LOOM_URL)
        self.assertEqual(self.dialog.loom_title.text(), 'Loom title: Upstream Loom title')
        with patch('untangle.recordings.QMessageBox.question', return_value=QMessageBox.Cancel):
            self.dialog.delete_selected()
        self.assertTrue(renamed.is_file())
        self.assertEqual(self.store.get(renamed)['url'], LOOM_URL)
        with patch('untangle.recordings.QMessageBox.question', return_value=QMessageBox.Yes):
            self.dialog.delete_selected()
        self.assertFalse(renamed.exists())
        self.assertEqual(UploadStore(self.state_path).get(renamed), {})
        self.assertFalse(self.dialog.copy_loom.isEnabled())

    def test_busy_blocks_all_metadata_actions_and_modal_state_changes(self):
        self.uploaded()
        requested, checked = [], []
        self.dialog.upload_requested.connect(requested.append)
        self.dialog.check_remote_requested.connect(checked.append)
        self.blocked = True
        self.dialog.update_actions()
        for button in (self.dialog.upload, self.dialog.rename, self.dialog.delete,
                self.dialog.check_loom, self.dialog.forget_loom):
            self.assertFalse(button.isEnabled())
        with patch('untangle.recordings.QMessageBox.question') as confirm, \
                patch('untangle.recordings.prompt_recording_name') as title:
            self.dialog.upload_selected()
            self.dialog.rename_selected()
            self.dialog.delete_selected()
            self.dialog.forget_selected_loom()
            self.dialog.check_selected_loom()
            confirm.assert_not_called()
            title.assert_not_called()
        self.assertEqual(requested, [])
        self.assertEqual(checked, [])
        def become_busy(*args):
            self.blocked = True
            return QMessageBox.Yes
        for method in (self.dialog.upload_selected, self.dialog.delete_selected,
                self.dialog.forget_selected_loom):
            self.blocked = False
            with patch('untangle.recordings.QMessageBox.question', side_effect=become_busy):
                method()
            self.assertTrue(self.path.is_file())
            self.assertEqual(self.store.get(self.path)['url'], LOOM_URL)
        self.assertEqual(requested, [])

    def test_auth_or_offline_error_keeps_saved_link_and_never_marks_deleted(self):
        self.uploaded(error='Unable to check Loom while offline or signed out.')
        self.dialog.check_loom.click()
        self.assertEqual(self.store.get(self.path)['status'], 'uploaded')
        self.assertIn('offline or signed out', self.dialog.loom_status.text())
        self.assertTrue(self.dialog.open_loom.isEnabled())
        self.assertTrue(self.path.is_file())

    def test_forget_write_error_keeps_link_and_reports_failure(self):
        self.uploaded()
        with patch('untangle.recordings.QMessageBox.question', return_value=QMessageBox.Yes), \
                patch.object(self.store, 'remove', side_effect=PermissionError('read only fixture')):
            self.dialog.forget_selected_loom()
        self.assertEqual(self.store.get(self.path)['url'], LOOM_URL)
        self.assertIn('Could not forget Loom link', self.dialog.message.text())
        self.assertTrue(self.dialog.open_loom.isEnabled())

    def test_metadata_rename_error_reports_actual_filename_and_preserves_saved_data(self):
        self.uploaded()
        before = self.state_path.read_bytes()
        changed = []
        self.dialog.recording_renamed.connect(lambda old, new: changed.append((old, new)))
        with patch('untangle.recordings.prompt_recording_name', side_effect=lambda parent, path, rename: rename('Renamed locally')), \
                patch.object(self.store, 'rename', side_effect=PermissionError('read only fixture')):
            self.dialog.rename_selected()
        renamed = self.directory / 'Renamed locally.mp4'
        self.assertTrue(renamed.is_file())
        self.assertFalse(self.path.exists())
        self.assertEqual(self.dialog.selected_path(), renamed)
        self.assertEqual(changed, [(str(self.path), str(renamed))])
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertFalse(self.dialog.open_loom.isEnabled())
        self.assertIn('could not move its Loom details: read only fixture', self.dialog.message.text())

    def test_metadata_delete_error_reports_local_deletion_without_discarding_saved_data(self):
        self.uploaded()
        before = self.state_path.read_bytes()
        deleted = []
        self.dialog.recording_deleted.connect(deleted.append)
        with patch('untangle.recordings.QMessageBox.question', return_value=QMessageBox.Yes), \
                patch.object(self.store, 'remove', side_effect=PermissionError('read only fixture')):
            self.dialog.delete_selected()
        self.assertFalse(self.path.exists())
        self.assertEqual(deleted, [str(self.path)])
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertFalse(self.dialog.open_loom.isEnabled())
        self.assertIn('could not clear its saved Loom details: read only fixture', self.dialog.message.text())

    def test_failed_local_delete_keeps_recording_and_link(self):
        self.uploaded()
        with patch('untangle.recordings.QMessageBox.question', return_value=QMessageBox.Yes), \
                patch.object(Path, 'unlink', side_effect=PermissionError('local file protected')):
            self.dialog.delete_selected()
        self.assertTrue(self.path.is_file())
        self.assertEqual(self.store.get(self.path)['url'], LOOM_URL)
        self.assertTrue(self.dialog.open_loom.isEnabled())
        self.assertIn('Could not delete', self.dialog.message.text())
