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

    def test_remote_copy_must_exist_and_match_size_and_md5(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / 'test.mp4'
            video.write_bytes(b'recording')
            row = {'remote_id': 'remote', 'checksum': checksum(video), 'folder': 'folder'}
            client = Mock()
            client.stat.return_value = {'ID': 'remote', 'Size': video.stat().st_size,
                                        'Hashes': {'md5': row['checksum']}}
            self.assertTrue(verified_drive(video, row, client))
            self.assertFalse(verified_drive(video, {**row, 'folder': None}, client))
            client.stat.return_value['Size'] += 1
            self.assertFalse(verified_drive(video, row, client))
            client.stat.return_value.update(Size=video.stat().st_size, Hashes={'md5': 'wrong'})
            self.assertFalse(verified_drive(video, row, client))
            # Trashed or deleted copies are absent from rclone listings.
            client.stat.return_value = None
            self.assertFalse(verified_drive(video, row, client))
            client.stat.side_effect = OSError('offline')
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

    def test_interrupted_upload_keeps_destination_and_verifies_before_retention(self):
        from untangle import rclone
        from untangle.archive import run
        from test_drive import FakeDrive
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'test.mp4'
            video.write_bytes(b'recording')
            configure(True, 'chosen', root, remote='gdrive:')
            store = UploadStore(root / 'archive-uploads.json')
            store.update(video, observed_at=time.time() - 600)
            drive = FakeDrive()
            interrupted = [rclone.RcloneTimeout()]
            def flaky(args, **kwargs):
                if args[0] == 'copyto' and interrupted:
                    drive.calls.append(list(args))
                    raise interrupted.pop()
                return drive(args, **kwargs)
            with patch('untangle.rclone.run', side_effect=flaky), \
                    patch.dict('os.environ', {'XDG_RUNTIME_DIR': str(root)}):
                run(root, root)
                self.assertNotIn('verified_at', UploadStore(root / 'archive-uploads.json').get(video))
                # A destination change does not move a pending upload.
                configure(True, 'elsewhere', root, remote='gdrive:')
                run(root, root)
                self.assertIn('verified_at', UploadStore(root / 'archive-uploads.json').get(video))
                run(root, root)
            copies = drive.copies()
            self.assertEqual(len(copies), 2)
            self.assertTrue(all(call[call.index('--drive-root-folder-id') + 1] == 'chosen'
                                for call in copies))
            self.assertEqual(UploadStore(root / 'archive-uploads.json').get(video)['remote_id'], 'file-1')

    def test_disabled_or_remote_less_archive_never_uploads(self):
        from untangle.archive import run
        from untangle import rclone
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'test.mp4').write_bytes(b'recording')
            with patch('untangle.rclone.run') as call, \
                    patch.dict('os.environ', {'XDG_RUNTIME_DIR': str(root)}):
                configure(False, 'chosen', root, remote='gdrive:')
                run(root, root)
                configure(True, 'chosen', root)
                with patch('untangle.rclone.drive_remote', return_value=None), \
                        patch('untangle.rclone.executable', return_value=None):
                    run(root, root)
            call.assert_not_called()
            self.assertEqual(UploadStore(root / 'archive-uploads.json').get(root / 'test.mp4'), {})
