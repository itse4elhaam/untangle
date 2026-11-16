"""Synthetic Drive UI only. No rclone, network or scheduler process is used."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from untangle.drive_dialog import DriveDialog


class DriveDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_partial_results_keep_destination_success_and_retry_warning(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch('untangle.drive_dialog.DriveClient') as client, \
                patch('untangle.archive_status.archive_status', return_value='Scheduler observed: Not checked.'):
            client.return_value.legacy_sign_in.return_value = []
            dialog = DriveDialog([Path('good.mp4'), Path('<bad>.mp4')])
            try:
                dialog.show_upload_results([
                    {'name': 'good.mp4', 'status': 'uploaded', 'remote_id': 'one'},
                    {'name': '<bad>.mp4', 'status': 'unconfirmed'}], 'Chosen archive folder')
                text = dialog.status.text()
                self.assertIn('1 of 2 uploaded to Chosen archive folder', text)
                self.assertIn('good.mp4: Uploaded', text)
                self.assertIn('<bad>.mp4: Failed or unconfirmed', text)
                self.assertIn('Copies are checksum-verified', text)
                self.assertIn('Retries reuse the saved archive copy', text)
                client.return_value.copy.assert_not_called()
                client.return_value.folders.assert_not_called()
            finally:
                dialog.close()

    def test_read_only_refresh_uses_operation_specific_feedback(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch('untangle.drive_dialog.DriveClient') as client, \
                patch('untangle.archive_status.archive_status', return_value='Separate archive states'):
            client.return_value.legacy_sign_in.return_value = []
            dialog = DriveDialog([])
            try:
                self.assertFalse(dialog.upload.isEnabled())
                with patch.object(dialog, 'start') as start:
                    dialog.refresh_archive_status()
                self.assertIn('Reading archive scheduler status', start.call_args.kwargs['message'])
                self.assertIn('No scheduler settings changed', start.call_args.kwargs['completed'])
                self.assertNotIn('browser', start.call_args.kwargs['message'])
            finally:
                dialog.close()

    def test_missing_remote_and_rclone_errors_show_setup_steps(self):
        from untangle.drive_dialog import DriveTask
        from untangle.rclone import RcloneMissing, NoDriveRemote
        with patch('untangle.drive_dialog.DriveClient') as client, \
                patch('untangle.archive_status.archive_status', return_value='Status'):
            client.return_value.legacy_sign_in.return_value = []
            dialog = DriveDialog([Path('a.mp4')])
            try:
                dialog.show_remotes([])
                self.assertIn('rclone config', dialog.status.text())
                dialog.show_remotes(['work:', 'gdrive:'])
                self.assertEqual(dialog.remotes.currentData(), 'gdrive:')
                with patch('untangle.archive.config', return_value={'folder': 'deep-id'}):
                    dialog.show_folders([('My Drive', 'root'), ('b', '2'), ('A', '1')])
                self.assertEqual([dialog.folders.itemData(i) for i in range(4)], ['root', '1', '2', 'deep-id'])
                # A saved folder missing from the listing stays selected instead of My Drive.
                self.assertEqual(dialog.folders.currentData(), 'deep-id')
                self.assertTrue(dialog.upload.isEnabled())
                dialog.remote_changed()
                self.assertEqual(dialog.folders.count(), 0)
                self.assertFalse(dialog.upload.isEnabled())
            finally:
                dialog.close()
        for error in (RcloneMissing(), NoDriveRemote()):
            task = DriveTask(Mock(side_effect=error), None)
            messages = []
            task.failed.connect(messages.append)
            task.run()
            self.assertIn('rclone config', messages[0])
            task.deleteLater()

    def test_cancel_reaches_client_and_old_sign_in_is_only_reported(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch('untangle.drive_dialog.DriveClient') as client, \
                patch('untangle.archive_status.archive_status', return_value='Status'):
            token = Path(directory) / 'token.json'
            token.write_text('synthetic')
            client.return_value.legacy_sign_in.return_value = [token]
            dialog = DriveDialog([])
            try:
                self.assertFalse(dialog.cancel_button.isEnabled())
                dialog.task = Mock()
                dialog.cancel_task()
                client.return_value.cancel.assert_called_once_with()
                dialog.task = None
                self.assertTrue(token.exists())
                labels = [label.text() for label in dialog.findChildren(type(dialog.status))]
                self.assertTrue(any(str(token) in text for text in labels))
            finally:
                dialog.close()
