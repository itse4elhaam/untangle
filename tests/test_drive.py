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

    def test_manual_upload_verifies_archive_copy_and_keeps_partial_failure(self):
        import sys
        from untangle.archive import checksum, has_remote_copy
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = DriveClient(root / 'state')
            good, bad = root / 'good.mp4', root / 'bad.mp4'
            good.write_bytes(b'good synthetic recording')
            bad.write_bytes(b'bad synthetic recording')
            service = Mock()
            files = service.files.return_value
            files.generateIds.return_value.execute.side_effect = [{'ids': ['uploaded']}, {'ids': ['failed']}]
            successful = Mock()
            successful.next_chunk.return_value = (None, {'id': 'uploaded'})
            files.create.side_effect = [successful, RuntimeError('offline')]
            missing = Exception('not found')
            missing.resp = Mock(status=404)
            metadata = {'size': str(good.stat().st_size), 'md5Checksum': checksum(good), 'trashed': False}
            files.get.return_value.execute.side_effect = [missing, metadata, missing, metadata]
            with patch.dict(sys.modules, {'googleapiclient.http': Mock()}), \
                    patch.object(client, 'service', return_value=service), \
                    patch('untangle.archive.DriveClient', return_value=client):
                outcomes = client.upload([good, bad], 'chosen-folder', Mock())
                self.assertTrue(has_remote_copy(good, state=client.state))
            self.assertEqual(outcomes, [
                {'name': 'good.mp4', 'status': 'uploaded', 'remote_id': 'uploaded'},
                {'name': 'bad.mp4', 'status': 'unconfirmed'}])
            self.assertEqual(files.create.call_args_list[0].kwargs['body']['parents'], ['chosen-folder'])
            self.assertTrue(good.exists() and bad.exists())

    def test_excluded_files_never_contact_drive_manually_or_in_background(self):
        from untangle.drive_policy import DrivePolicy
        from untangle.archive import configure, run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'private.mp4'
            video.write_bytes(b'private fixture')
            client = DriveClient(root / 'state')
            DrivePolicy.set_blocked([video], True, client.state)
            configure(True, 'chosen', client.state)
            with patch.object(client, 'service') as service, \
                    patch('untangle.archive.DriveClient', return_value=client), \
                    patch.dict('os.environ', {'XDG_RUNTIME_DIR': str(root)}):
                self.assertEqual(client.upload([video], 'chosen', Mock()),
                                 [{'name': 'private.mp4', 'status': 'excluded'}])
                run(root, client.state)
                service.assert_not_called()
            # An unreadable policy must never silently permit a private upload.
            (client.state / 'upload-exclusions.json').write_text('invalid')
            with patch.object(client, 'service') as service:
                with self.assertRaises(OSError):
                    client.upload([video], 'chosen', Mock())
                service.assert_not_called()

    def test_checksum_mismatch_never_starts_retention(self):
        import sys
        from untangle.upload_store import UploadStore
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'test.mp4'
            video.write_bytes(b'synthetic recording')
            client = DriveClient(root / 'state')
            service = Mock()
            files = service.files.return_value
            files.generateIds.return_value.execute.return_value = {'ids': ['reserved']}
            files.get.return_value.execute.return_value = {
                'size': str(video.stat().st_size), 'md5Checksum': 'wrong', 'trashed': False}
            files.create.return_value.next_chunk.return_value = (None, {'id': 'reserved'})
            with patch.object(client, 'service', return_value=service), \
                    patch.dict(sys.modules, {'googleapiclient.http': Mock()}):
                result = client.upload([video], 'chosen', Mock())
            self.assertEqual(result[0]['status'], 'unconfirmed')
            self.assertNotIn('verified_at', UploadStore(client.state / 'archive-uploads.json').get(video))
            self.assertTrue(video.exists())
