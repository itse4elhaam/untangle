"""Headless Drive archiving. This module never imports the recorder or deletes files."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time

from .drive import DriveClient
from .naming import recording_files
from .upload_store import UploadStore

STATE = Path.home() / '.local/share/glint/google-drive'
RETENTION = 7 * 24 * 60 * 60


def checksum(path):
    digest = hashlib.md5()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


@contextmanager
def archive_lock(state=STATE):
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / 'archive.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def config(state=STATE):
    try:
        data = json.loads((state / 'archive.json').read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def configure(enabled, folder, state=STATE):
    if enabled and not folder:
        raise ValueError('Choose a destination folder first.')
    with archive_lock(state):
        DriveClient(state).save_private(state / 'archive.json', json.dumps(
            {'enabled': bool(enabled), 'folder': folder}))


def verified_drive(path, row, client):
    if not row.get('remote_id') or not row.get('checksum'):
        return False
    identity = UploadStore.file_identity(path)
    if identity is None or checksum(path) != row['checksum']:
        return False
    try:
        remote = client.service().files().get(fileId=row['remote_id'],
            fields='id,size,md5Checksum,trashed', supportsAllDrives=True).execute()
    except Exception as exc:
        if getattr(getattr(exc, 'resp', None), 'status', None) == 404:
            return False
        raise
    return (remote.get('trashed') is False and str(remote.get('size')) == str(identity['size'])
            and remote.get('md5Checksum') == row['checksum']
            and UploadStore.file_identity(path) == identity)


def has_remote_copy(path, loom_store=None, state=STATE):
    """Fail closed on missing metadata, changed files, offline services or deleted videos."""
    try:
        row = UploadStore(state / 'archive-uploads.json').get(path)
        if verified_drive(path, row, DriveClient(state)):
            return True
    except Exception:
        pass
    if loom_store is not None:
        row = loom_store.get(path)
        if row.get('status') == 'uploaded' and row.get('remote_id'):
            try:
                import subprocess
                from .loom import video_info_args, parse_video_info
                result = subprocess.run(['twg', *video_info_args(row['remote_id'])],
                    capture_output=True, text=True, timeout=20, check=True)
                remote = parse_video_info(result.stdout)
                return (remote.get('status') == 'available' and remote.get('is_complete') is not False
                        and remote.get('remote_id') == row['remote_id'])
            except Exception:
                pass
    return False


def cleanup_candidates(directory, state=STATE, now=None):
    now = time.time() if now is None else now
    store = UploadStore(state / 'archive-uploads.json')
    return [path for path in recording_files(directory)
            if store.get(path).get('verified_at', now) <= now - RETENTION]


def run(directory=None, state=STATE):
    # Leave active recording sessions alone. A stale app lock conservatively defers work.
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
    if (runtime / 'truedevs-glint.lock').exists():
        return
    from googleapiclient.http import MediaFileUpload
    directory = directory or Path.home() / 'Videos/RecIt'
    with archive_lock(state):
        options = config(state)
        if not options.get('enabled') or not options.get('folder'):
            return
        client = DriveClient(state)
        store = UploadStore(state / 'archive-uploads.json')
        if store.error:
            raise OSError(store.error)
        for path in recording_files(directory):
            try:
                # Only archive files observed unchanged across two periodic runs.
                if path.is_symlink():
                    continue
                identity = store.file_identity(path)
                row = store.get(path)
                if not row.get('observed_at'):
                    store.update(path, observed_at=time.time())
                    continue
                if time.time() - row['observed_at'] < 300:
                    continue
                digest = checksum(path)
                if store.file_identity(path) != identity:
                    continue
                service = client.service()
                remote_id = row.get('remote_id')
                if not remote_id:
                    remote_id = service.files().generateIds(count=1, space='drive').execute()['ids'][0]
                    # Persist before uploading: retries use the same ID, including after crashes.
                    store.update(path, expected_identity=identity, remote_id=remote_id,
                                 checksum=digest, folder=options['folder'])
                if not verified_drive(path, store.get(path), client):
                    media = MediaFileUpload(str(path), resumable=True, chunksize=8 * 1024 * 1024)
                    request = service.files().create(body={'id': remote_id, 'name': path.name,
                        'parents': [store.get(path)['folder']]}, media_body=media,
                        fields='id', supportsAllDrives=True)
                    response = None
                    while response is None:
                        _, response = request.next_chunk(num_retries=3)
                if verified_drive(path, store.get(path), client):
                    store.update(path, expected_identity=identity,
                                 verified_at=row.get('verified_at', time.time()))
            except Exception:
                # One failed upload must not prevent other recordings from being archived.
                # Do not log HTTP exceptions, which can contain tokens.
                continue


if __name__ == '__main__':
    run()
