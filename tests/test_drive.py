"""Drive uploads through a fake rclone.run. No rclone process, sign-in or network is used."""
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from untangle import rclone
from untangle.drive import DriveClient
from untangle.upload_store import UploadStore


class FakeDrive:
    """Stands in for rclone.run: folders of uploaded files keyed by Drive folder ID."""
    def __init__(self, corrupt=False, fail=()):
        self.folders = {}
        self.calls = []
        self.corrupt = corrupt
        self.fail = set(fail)
        self.next_id = 0

    def __call__(self, args, *, timeout, cancel=None, on_log=None, capture=True):
        self.calls.append(list(args))
        if args[0] == 'listremotes':
            return 'gdrive: drive\n'
        folder = args[args.index('--drive-root-folder-id') + 1] if '--drive-root-folder-id' in args else None
        if args[0] == 'copyto':
            source, name = Path(args[1]), args[2].split(':', 1)[1]
            if source.name in self.fail:
                raise rclone.RcloneError('rclone could not finish this action.', returncode=1)
            data = source.read_bytes()
            self.next_id += 1
            self.folders.setdefault(folder, {})[name] = {
                'Name': name, 'Path': name, 'ID': f'file-{self.next_id}', 'Size': len(data),
                'IsDir': False, 'Hashes': {'md5': 'f' * 32 if self.corrupt else hashlib.md5(data).hexdigest()}}
            if on_log:
                on_log({'stats': {'bytes': len(data), 'totalBytes': len(data)}})
            return ''
        if '--dirs-only' in args:
            return json.dumps([{'Path': 'Archive', 'Name': 'Archive', 'ID': 'archive-id', 'IsDir': True},
                               {'Path': 'Archive/2026', 'Name': '2026', 'ID': 'year-id', 'IsDir': True}])
        if folder not in self.folders:
            raise rclone.RcloneNotFound('Not found on Drive.', returncode=3)
        return json.dumps(list(self.folders[folder].values()))

    def copies(self):
        return [call for call in self.calls if call[0] == 'copyto']


class DriveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.client = DriveClient(self.root / 'state', 'gdrive')

    def fake(self, drive):
        return patch('untangle.rclone.run', drive)

    def video(self, name, content=b'synthetic recording'):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_folders_list_recursively_with_ids_under_the_remote(self):
        drive = FakeDrive()
        with self.fake(drive):
            self.assertEqual(self.client.folders(), [
                ('My Drive', 'root'), ('Archive', 'archive-id'), ('Archive/2026', 'year-id')])
        self.assertIn('--dirs-only', drive.calls[0])
        self.assertEqual(drive.calls[0][-1], 'gdrive:')

    def test_remote_resolution_prefers_choice_then_saved_then_discovery(self):
        from untangle.archive import configure
        client = DriveClient(self.root / 'state')
        configure(False, 'root', client.state, remote='saved:')
        self.assertEqual(client.resolve_remote(), 'saved:')
        client = DriveClient(self.root / 'other')
        with patch('untangle.rclone.drive_remote', return_value=None), \
                patch('untangle.rclone.executable', return_value=None):
            with self.assertRaises(rclone.RcloneMissing):
                client.resolve_remote()
        with patch('untangle.rclone.drive_remote', return_value=None), \
                patch('untangle.rclone.executable', return_value='/usr/bin/rclone'):
            with self.assertRaises(rclone.NoDriveRemote) as caught:
                client.resolve_remote()
        self.assertIn('rclone config', str(caught.exception))

    def test_upload_verifies_and_keeps_partial_failure(self):
        from untangle.archive import has_remote_copy
        good, bad = self.video('good.mp4', b'good synthetic'), self.video('bad.mp4', b'bad synthetic')
        drive, progress = FakeDrive(fail={'bad.mp4'}), Mock()
        with self.fake(drive), patch('untangle.archive.DriveClient', return_value=self.client):
            outcomes = self.client.upload([good, bad], 'chosen-folder', progress)
            self.assertTrue(has_remote_copy(good, state=self.client.state))
            self.assertFalse(has_remote_copy(bad, state=self.client.state))
        self.assertEqual(outcomes, [
            {'name': 'good.mp4', 'status': 'uploaded', 'remote_id': 'file-1'},
            {'name': 'bad.mp4', 'status': 'unconfirmed'}])
        copy = drive.copies()[0]
        self.assertEqual(copy[1:3], [str(good), 'gdrive:good.mp4'])
        self.assertEqual(copy[copy.index('--drive-root-folder-id') + 1], 'chosen-folder')
        self.assertIn('--immutable', copy)
        progress.assert_any_call('good.mp4: 100%')
        row = UploadStore(self.client.state / 'archive-uploads.json').get(good)
        self.assertEqual((row['remote'], row['folder'], row['name']), ('gdrive:', 'chosen-folder', 'good.mp4'))
        self.assertIn('verified_at', row)
        self.assertTrue(good.exists() and bad.exists())

    def test_hash_mismatch_is_a_failure_and_never_starts_retention(self):
        video = self.video('test.mp4')
        with self.fake(FakeDrive(corrupt=True)):
            result = self.client.upload([video], 'chosen', Mock())
        self.assertEqual(result[0]['status'], 'unconfirmed')
        self.assertNotIn('verified_at', UploadStore(self.client.state / 'archive-uploads.json').get(video))
        self.assertTrue(video.exists())

    def test_missing_rclone_fails_each_upload_without_retention(self):
        video = self.video('test.mp4')
        with patch('untangle.rclone.executable', return_value=None), \
                patch('untangle.rclone.subprocess.Popen') as spawn:
            result = self.client.upload([video], 'chosen', Mock())
        spawn.assert_not_called()
        self.assertEqual(result, [{'name': 'test.mp4', 'status': 'unconfirmed'}])

    def test_cancel_stops_current_transfer_and_skips_the_rest(self):
        first, second = self.video('one.mp4'), self.video('two.mp4')
        def cancelled(args, **kwargs):
            if args[0] == 'copyto':
                self.client.cancel()
                raise rclone.RcloneCancelled()
            raise rclone.RcloneNotFound('Not found on Drive.', returncode=3)
        progress = Mock()
        with patch('untangle.rclone.run', side_effect=cancelled):
            result = self.client.upload([first, second], 'chosen', progress)
        self.assertEqual(result, [{'name': 'one.mp4', 'status': 'unconfirmed'},
                                  {'name': 'two.mp4', 'status': 'cancelled'}])
        progress.assert_any_call('one.mp4: cancelled. Check Drive before retrying.')

    def test_excluded_files_never_contact_drive_manually_or_in_background(self):
        from untangle.drive_policy import DrivePolicy
        from untangle.archive import configure, run
        video = self.video('private.mp4', b'private fixture')
        DrivePolicy.set_blocked([video], True, self.client.state)
        configure(True, 'chosen', self.client.state, remote='gdrive:')
        with patch('untangle.rclone.run') as call, \
                patch.dict('os.environ', {'XDG_RUNTIME_DIR': str(self.root)}):
            self.assertEqual(self.client.upload([video], 'chosen', Mock()),
                             [{'name': 'private.mp4', 'status': 'excluded'}])
            run(self.root, self.client.state)
            call.assert_not_called()
        # An unreadable policy must never silently permit a private upload.
        (self.client.state / 'upload-exclusions.json').write_text('invalid')
        with patch('untangle.rclone.run') as call:
            with self.assertRaises(OSError):
                self.client.upload([video], 'chosen', Mock())
            call.assert_not_called()

    def test_google_api_rows_and_settings_keep_working_and_files_are_kept(self):
        """A copy verified by the earlier Google API client is matched by its Drive ID, not re-uploaded."""
        from untangle.archive import checksum, has_remote_copy, run
        state = self.root / 'state'
        state.mkdir()
        (state / 'archive.json').write_text(json.dumps({'enabled': True, 'folder': 'legacy-folder'}))
        (state / 'token.json').write_text('synthetic token')
        video = self.video('old.mp4')
        store = UploadStore(state / 'archive-uploads.json')
        store.update(video, remote_id='legacy-id', checksum=checksum(video), folder='legacy-folder',
                     observed_at=time.time() - 600, verified_at=time.time() - 60)
        drive = FakeDrive()
        drive.folders['legacy-folder'] = {'old.mp4': {
            'Name': 'old.mp4', 'ID': 'legacy-id', 'Size': video.stat().st_size,
            'Hashes': {'md5': checksum(video).upper()}}}
        with self.fake(drive), patch.dict('os.environ', {'XDG_RUNTIME_DIR': str(self.root),
                                                          'UNTANGLE_DRIVE_REMOTE': 'gdrive'}):
            self.assertTrue(has_remote_copy(video, state=state))
            run(self.root, state)
        self.assertEqual(drive.copies(), [])
        self.assertEqual(DriveClient(state).legacy_sign_in(), [state / 'token.json'])
