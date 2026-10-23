import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from untangle.upload_store import UploadStore


class UploadStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.video = self.root / 'Recording.mp4'
        self.video.write_bytes(b'synthetic video')
        self.state = self.root / 'state' / 'uploads.json'
        self.store = UploadStore(self.state)

    def upload(self, **fields):
        values = {'status': 'uploaded', 'url': 'https://www.loom.com/share/abc123',
                  'title': 'Remote title', 'remote_id': 'abc123',
                  'visibility': 'owner', 'error': ''}
        values.update(fields)
        return self.store.update(self.video, **values)

    def test_round_trip_and_detached_results(self):
        row = self.upload()
        row['title'] = 'Changed by caller'
        restored = UploadStore(self.state)
        self.assertEqual(restored.get(self.video)['title'], 'Remote title')
        self.assertEqual(restored.get(self.video)['visibility'], 'owner')
        self.assertEqual(restored.get(self.video)['remote_id'], 'abc123')
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)

    def test_replaced_file_with_same_name_size_and_mtime_rejects_link(self):
        self.upload()
        original = self.video.stat()
        replacement = self.root / 'replacement.mp4'
        replacement.write_bytes(b'x' * original.st_size)
        os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
        replacement.replace(self.video)
        self.assertEqual(self.store.get(self.video), {})
        self.assertEqual(UploadStore(self.state).get(self.video), {})
        self.store.update(self.video, status='uploading')
        self.assertNotIn('url', self.store.get(self.video))

    def test_completion_rejects_replacement_identity_without_writing(self):
        identity = self.store.file_identity(self.video)
        self.store.update(self.video, expected_identity=identity, status='uploading')
        contents = self.state.read_bytes()
        replacement = self.root / 'replacement.mp4'
        replacement.write_bytes(b'a replacement recording')
        replacement.replace(self.video)
        with self.assertRaisesRegex(OSError, 'changed during upload'):
            self.store.update(self.video, expected_identity=identity, status='uploaded',
                              url='https://www.loom.com/share/abc123')
        self.assertEqual(self.state.read_bytes(), contents)
        self.assertEqual(self.store.get(self.video), {})
        self.assertEqual(UploadStore(self.state).get(self.video), {})

    def test_modified_contents_reject_link(self):
        self.upload()
        self.video.write_bytes(b'a different recording')
        self.assertEqual(self.store.get(self.video), {})

    def test_temporarily_missing_folder_is_never_pruned(self):
        folder = self.root / 'recordings'
        folder.mkdir()
        video = folder / self.video.name
        self.video.rename(video)
        self.store.update(video, status='uploaded', url='https://www.loom.com/share/abc123')
        elsewhere = self.root / 'disconnected'
        folder.rename(elsewhere)
        restored = UploadStore(self.state)
        self.assertEqual(restored.get(video), {})
        restored.update(self.video if self.video.exists() else elsewhere / video.name, status='failed')
        elsewhere.rename(folder)
        self.assertEqual(UploadStore(self.state).get(video)['url'], 'https://www.loom.com/share/abc123')

    def test_rename_then_local_delete_lifecycle(self):
        self.upload()
        renamed = self.video.with_name('Renamed.mp4')
        self.video.rename(renamed)
        self.store.rename(self.video, renamed)
        self.assertEqual(self.store.get(self.video), {})
        self.assertEqual(UploadStore(self.state).get(renamed)['title'], 'Remote title')
        renamed.unlink()
        self.store.remove(renamed)
        self.assertEqual(json.loads(self.state.read_text())['uploads'], {})

    def test_forget_only_removes_metadata(self):
        self.upload()
        self.store.remove(self.video)
        self.assertEqual(self.video.read_bytes(), b'synthetic video')
        self.assertEqual(UploadStore(self.state).get(self.video), {})

    def test_rename_rejects_different_file_without_losing_metadata(self):
        self.upload()
        other = self.root / 'other.mp4'
        other.write_bytes(b'unrelated')
        with self.assertRaises(OSError):
            self.store.rename(self.video, other)
        self.assertEqual(self.store.get(self.video)['remote_id'], 'abc123')
        self.assertEqual(self.store.get(other), {})

    def test_confirmed_remote_deletion_invalidates_url_only(self):
        self.upload()
        row = self.store.mark_remote_deleted(self.video)
        self.assertEqual(row['status'], 'deleted')
        self.assertEqual(row['url'], '')
        self.assertEqual(row['title'], 'Remote title')
        self.assertEqual(row['remote_id'], 'abc123')
        self.assertTrue(self.video.exists())
        self.assertEqual(UploadStore(self.state).get(self.video), row)

    def test_interrupted_uploads_become_uncertain_on_restore(self):
        for status in ('uploading', 'processing'):
            with self.subTest(status=status):
                self.upload(status=status)
                row = UploadStore(self.state).get(self.video)
                self.assertEqual(row['status'], 'uncertain')
                self.assertIn('Check Loom', row['error'])
                self.assertEqual(row['url'], 'https://www.loom.com/share/abc123')
                self.assertEqual(UploadStore(self.state).get(self.video), row)

    def test_corrupt_or_future_metadata_is_left_untouched(self):
        self.state.parent.mkdir()
        for contents in ('{bad json', '[]', '{"version":2,"uploads":{}}',
                         '{"version":1,"uploads":{"/x":null}}'):
            with self.subTest(contents=contents):
                self.state.write_text(contents)
                store = UploadStore(self.state)
                self.assertTrue(store.error)
                self.assertEqual(store.get(self.video), {})
                with self.assertRaises(OSError):
                    store.update(self.video, status='uploaded')
                self.assertEqual(self.state.read_text(), contents)

    def test_failed_atomic_replace_preserves_saved_and_in_memory_metadata(self):
        self.upload()
        contents = self.state.read_bytes()
        with patch('untangle.upload_store.os.replace', side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError):
                self.store.update(self.video, title='New title')
        self.assertEqual(self.state.read_bytes(), contents)
        self.assertEqual(self.store.get(self.video)['title'], 'Remote title')
        self.assertEqual(list(self.state.parent.iterdir()), [self.state])

    def test_missing_video_or_non_json_value_cannot_erase_store(self):
        self.upload()
        contents = self.state.read_bytes()
        with self.assertRaises(OSError):
            self.store.update(self.root / 'missing.mp4', status='uploaded')
        with self.assertRaises(TypeError):
            self.store.update(self.video, extra=object())
        self.assertEqual(self.state.read_bytes(), contents)


if __name__ == '__main__':
    unittest.main()
