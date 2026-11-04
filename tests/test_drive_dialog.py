"""Synthetic Drive UI only. No sign-in, network or scheduler process is used."""
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
            client.return_value.token_file = Path(directory) / 'no-token'
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
                client.return_value.login.assert_not_called()
                client.return_value.service.assert_not_called()
            finally:
                dialog.close()

    def test_read_only_refresh_uses_operation_specific_feedback(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch('untangle.drive_dialog.DriveClient') as client, \
                patch('untangle.archive_status.archive_status', return_value='Separate archive states'):
            client.return_value.token_file = Path(directory) / 'no-token'
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
