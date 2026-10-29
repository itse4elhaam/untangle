import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from untangle.drive import DriveClient


class DriveTests(unittest.TestCase):
    def test_configure_validates_and_protects_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = DriveClient(root / 'state')
            source = root / 'source.json'
            source.write_text('{}')
            with self.assertRaises(ValueError):
                client.configure(source)
            self.assertFalse(client.client_file.exists())
            source.write_text(json.dumps({'installed': {'client_id': 'test', 'client_secret': 'test'}}))
            client.configure(source)
            self.assertEqual(client.client_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(client.state.stat().st_mode & 0o777, 0o700)
            client.save_private(client.token_file, 'test')
            client.disconnect()
            self.assertFalse(client.token_file.exists())

    def test_folders_fetch_every_page(self):
        client = DriveClient()
        service = Mock()
        service.files.return_value.list.return_value.execute.side_effect = [
            {'files': [{'id': 'one', 'name': 'First'}], 'nextPageToken': 'next'},
            {'files': [{'id': 'two', 'name': 'Second'}]}]
        with patch.object(client, 'service', return_value=service):
            self.assertEqual(client.folders(), [('My Drive', 'root'), ('First', 'one'), ('Second', 'two')])
        self.assertEqual(service.files.return_value.list.call_args.kwargs['pageToken'], 'next')

    def test_upload_keeps_destination_and_reports_partial_failure(self):
        import sys
        client = DriveClient()
        service = Mock()
        successful = Mock()
        successful.next_chunk.return_value = (None, {'id': 'uploaded'})
        service.files.return_value.create.side_effect = [successful, RuntimeError('offline')]
        fake_http = Mock()
        with patch.dict(sys.modules, {'googleapiclient': Mock(), 'googleapiclient.http': fake_http}), \
                patch.object(client, 'service', return_value=service):
            with self.assertRaisesRegex(ValueError, 'bad.mp4'):
                client.upload([Path('good.mp4'), Path('bad.mp4')], 'chosen-folder', Mock())
        self.assertEqual(service.files.return_value.create.call_args_list[0].kwargs['body'],
                         {'name': 'good.mp4', 'parents': ['chosen-folder']})
