from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from untangle.archive import (configure, config, cleanup_candidates, checksum,
                              has_remote_copy, verified_drive, RETENTION)
from untangle.upload_store import UploadStore


class ArchiveTests(unittest.TestCase):
    def test_destination_is_required_and_can_be_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with self.assertRaises(ValueError):
                configure(True, '', state)
            configure(True, 'folder-one', state)
            self.assertEqual(config(state)['folder'], 'folder-one')
            configure(False, 'folder-two', state)
            self.assertFalse(config(state)['enabled'])
            self.assertEqual(config(state)['folder'], 'folder-two')

    def test_cleanup_waits_seven_days_from_verified_upload_and_rejects_changed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'test.mp4'
            video.write_bytes(b'recording')
            store = UploadStore(root / 'archive-uploads.json')
            now = time.time()
            store.update(video, verified_at=now)
            self.assertEqual(cleanup_candidates(root, root, now + RETENTION - 1), [])
            self.assertEqual(cleanup_candidates(root, root, now + RETENTION), [video])
            video.write_bytes(b'different recording')
            self.assertEqual(cleanup_candidates(root, root, now + RETENTION), [])

    def test_remote_copy_must_exist_match_and_not_be_trashed(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / 'test.mp4'
            video.write_bytes(b'recording')
            row = {'remote_id': 'remote', 'checksum': checksum(video)}
            client = Mock()
            response = client.service.return_value.files.return_value.get.return_value.execute
            response.return_value = {'size': str(video.stat().st_size),
                                     'md5Checksum': row['checksum'], 'trashed': False}
            self.assertTrue(verified_drive(video, row, client))
            response.return_value['trashed'] = True
            self.assertFalse(verified_drive(video, row, client))
            response.return_value['trashed'] = False
            response.return_value['md5Checksum'] = 'wrong'
            self.assertFalse(verified_drive(video, row, client))
            response.side_effect = OSError('offline')
            with patch('untangle.archive.DriveClient', return_value=client), \
                    patch('untangle.archive.UploadStore') as store:
                store.return_value.get.return_value = row
                self.assertFalse(has_remote_copy(video, state=Path(directory)))

    def test_unuploaded_recordings_are_never_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'test.mp4'
            video.write_bytes(b'recording')
            self.assertEqual(cleanup_candidates(root, root), [])
            self.assertFalse(has_remote_copy(video, state=root))

    def test_interrupted_upload_reuses_reserved_id_and_verifies_before_retention(self):
        import sys
        from untangle.archive import run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'test.mp4'
            video.write_bytes(b'recording')
            configure(True, 'chosen', root)
            store = UploadStore(root / 'archive-uploads.json')
            store.update(video, observed_at=time.time() - 600)
            client = Mock()
            files = client.service.return_value.files.return_value
            files.generateIds.return_value.execute.return_value = {'ids': ['reserved']}
            missing = Exception('not found')
            missing.resp = Mock(status=404)
            metadata = {'size': str(video.stat().st_size), 'md5Checksum': checksum(video), 'trashed': False}
            files.get.return_value.execute.side_effect = [missing, missing, metadata, metadata, metadata]
            files.create.return_value.next_chunk.side_effect = [OSError('interrupted'), (None, {'id': 'reserved'})]
            with patch('untangle.archive.DriveClient', return_value=client), \
                    patch.dict(sys.modules, {'googleapiclient.http': Mock()}), \
                    patch.dict('os.environ', {'XDG_RUNTIME_DIR': str(root)}):
                run(root, root)
                self.assertNotIn('verified_at', UploadStore(root / 'archive-uploads.json').get(video))
                run(root, root)
                self.assertIn('verified_at', UploadStore(root / 'archive-uploads.json').get(video))
                run(root, root)
            self.assertEqual(files.generateIds.call_count, 1)
            self.assertEqual(files.create.call_count, 2)
            self.assertTrue(all(call.kwargs['body']['id'] == 'reserved'
                                for call in files.create.call_args_list))
