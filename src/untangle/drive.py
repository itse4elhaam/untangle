"""Google Drive through the user's own rclone remote. No network calls occur until explicitly requested.

Destinations are Drive folder IDs, addressed with ``--drive-root-folder-id`` so
folders saved by the earlier Google API client keep working. ``token.json`` and
``client.json`` from that client are no longer read and are never deleted here.
"""
import json
import os
from pathlib import Path
import threading

from . import rclone
from .diagnostics import observed

REMOTE_ENV = 'UNTANGLE_DRIVE_REMOTE'
FOLDER_DEPTH = 4


class DriveClient:
    def __init__(self, state=None, remote=None):
        self.state = state or Path.home() / '.local/share/glint/google-drive'
        self.client_file = self.state / 'client.json'
        self.token_file = self.state / 'token.json'
        self.remote = rclone.normalize(remote) if remote else None
        self.cancelled = threading.Event()

    def save_private(self, path, content):
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state, 0o700)
        temporary = path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        temporary.replace(path)

    def legacy_sign_in(self):
        """Files left by the earlier Google API sign-in, which the user may remove themselves."""
        return [path for path in (self.token_file, self.client_file) if path.exists()]

    def cancel(self):
        self.cancelled.set()

    def resolve_remote(self):
        """The chosen remote, else the saved one, else UNTANGLE_DRIVE_REMOTE or the first Drive remote."""
        if self.remote:
            return self.remote
        from .archive import config
        saved = config(self.state).get('remote')
        self.remote = rclone.normalize(saved) if saved else rclone.drive_remote(REMOTE_ENV)
        if not self.remote:
            if rclone.executable() is None:
                raise rclone.RcloneMissing()
            raise rclone.NoDriveRemote()
        return self.remote

    @observed("drive.remotes")
    def remotes(self):
        return rclone.drive_remotes(cancel=self.cancelled)

    @observed("drive.folders")
    def folders(self):
        listing = rclone.run(['lsjson', '--dirs-only', '-R', '--max-depth', str(FOLDER_DEPTH),
                              '--no-modtime', '--no-mimetype', self.resolve_remote()],
                             timeout=180, cancel=self.cancelled)
        folders = [('My Drive', 'root')]
        folders.extend((item['Path'], item['ID']) for item in json.loads(listing or '[]')
                       if item.get('IsDir') and item.get('ID') and item.get('Path'))
        return folders

    def files(self, folder, remote=None):
        """Untrashed files directly inside a folder ID, with MD5, or None when the folder is gone."""
        try:
            # Fail fast offline: cleanup checks run behind a modal progress dialog.
            listing = rclone.run(['lsjson', '--files-only', '--hash-type', 'md5', '--no-modtime',
                                  '--no-mimetype', '--low-level-retries', '2', '--contimeout', '15s',
                                  '--drive-root-folder-id', folder,
                                  rclone.normalize(remote) if remote else self.resolve_remote()],
                                 timeout=60, cancel=self.cancelled)
        except rclone.RcloneNotFound:
            return None
        return [item for item in json.loads(listing or '[]') if isinstance(item, dict)]

    def stat(self, row):
        """The remote file recorded in an archive row, matched by Drive ID; None when missing."""
        entries = self.files(row['folder'], row.get('remote'))
        matches = [entry for entry in entries or () if entry.get('ID') == row['remote_id']]
        return matches[0] if len(matches) == 1 else None

    def copy(self, path, folder, name, progress=lambda message: None, remote=None):
        """Copy one file into a folder ID. --immutable refuses to replace different content."""
        size = Path(path).stat().st_size
        def report(record):
            stats = record.get('stats')
            if isinstance(stats, dict) and stats.get('totalBytes'):
                progress(f'{name}: {stats.get("bytes", 0) / stats["totalBytes"]:.0%}')
        rclone.run(['copyto', str(Path(path).absolute()),
                    (rclone.normalize(remote) if remote else self.resolve_remote()) + name,
                    '--drive-root-folder-id', folder, '--immutable', '--use-json-log',
                    '--stats', '2s', '--stats-log-level', 'NOTICE', '--retries', '3',
                    '--low-level-retries', '10', '--contimeout', '60s', '--timeout', '5m'],
                   # Allow slow links (64 KiB/s) while still ending a stuck transfer.
                   timeout=900 + size / (64 * 1024), cancel=self.cancelled, on_log=report,
                   capture=False)

    @observed("drive.upload")
    def upload(self, paths, folder_id, progress):
        from .archive import upload_paths
        return upload_paths(paths, folder_id, self, progress)
