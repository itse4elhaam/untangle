"""Headless Drive archiving. This module never imports the recorder or deletes files."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time

from .diagnostics import event, failure as diagnostic_failure
from .drive import DriveClient
from .rclone import RcloneCancelled
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


def configure(enabled, folder, state=STATE, remote=None):
    """Save the folder ID and rclone remote. Configs saved before rclone have no remote."""
    if enabled and not folder:
        raise ValueError('Choose a destination folder first.')
    options = {'enabled': bool(enabled), 'folder': folder}
    if remote:
        options['remote'] = remote
    with archive_lock(state):
        DriveClient(state).save_private(state / 'archive.json', json.dumps(options))


def verified_drive(path, row, client):
    """True only when the recorded Drive file exists untrashed with this file's size and MD5.

    Missing remote files return False; rclone failures raise so callers fail closed.
    """
    if not row.get('remote_id') or not row.get('checksum') or not row.get('folder'):
        return False
    identity = UploadStore.file_identity(path)
    if identity is None or checksum(path) != row['checksum']:
        return False
    remote = client.stat(row)
    if remote is None:
        return False
    md5 = str((remote.get('Hashes') or {}).get('md5', '')).lower()
    return (str(remote.get('Size')) == str(identity['size']) and md5 == row['checksum']
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


def upload_recording(path, folder, store, client, progress=lambda message: None):
    """Record the destination before transfer, then verify before establishing retention."""
    identity = store.file_identity(path)
    if identity is None or path.is_symlink():
        raise OSError('The recording is missing or is a symbolic link.')
    row = store.get(path)
    digest = checksum(path)
    if store.file_identity(path) != identity:
        raise OSError('The recording changed.')
    if not row.get('folder'):
        # Retries keep the original destination, even after the chosen folder changes.
        store.update(path, expected_identity=identity, checksum=digest, folder=folder,
                     remote=client.resolve_remote(), name=path.name)
    row = store.get(path)
    if not verified_drive(path, row, client):
        name = row.get('name') or path.name
        remote = row.get('remote') or client.resolve_remote()
        client.copy(path, row['folder'], name, progress, remote)
        copies = [entry for entry in client.files(row['folder'], remote) or ()
                  if entry.get('Name') == name]
        if len(copies) != 1 or not copies[0].get('ID'):
            raise OSError('The Drive copy could not be identified.')
        # Rows from the Google API client hold a reserved ID that rclone cannot reuse.
        store.update(path, expected_identity=identity, remote_id=copies[0]['ID'],
                     remote=remote, name=name)
    row = store.get(path)
    if not verified_drive(path, row, client):
        raise OSError('The Drive copy could not be verified.')
    store.update(path, expected_identity=identity,
                 verified_at=row.get('verified_at', time.time()))
    return row['remote_id']


def upload_paths(paths, folder, client, progress):
    """Explicit manual upload, independent of background opt-in and file age."""
    from .drive_policy import DrivePolicy
    outcomes = []
    with archive_lock(client.state):
        policy = DrivePolicy(client.state)
        store = UploadStore(client.state / 'archive-uploads.json')
        if store.error:
            raise OSError(store.error)
        for target in paths:
            path = Path(target)
            if client.cancelled.is_set():
                outcomes.append({'name': path.name, 'status': 'cancelled'})
                continue
            try:
                if policy.blocked(path):
                    outcomes.append({'name': path.name, 'status': 'excluded'})
                    progress(f'{path.name}: Do not upload to Google Drive is set.')
                    continue
                progress(f'Uploading {path.name}…')
                remote_id = upload_recording(path, folder, store, client, progress)
                outcomes.append({'name': path.name, 'status': 'uploaded', 'remote_id': remote_id})
                progress(f'Uploaded and verified {path.name}')
            except Exception as exc:
                diagnostic_failure('archive.upload_paths.file_failed', exc)
                outcomes.append({'name': path.name, 'status': 'unconfirmed'})
                if isinstance(exc, RcloneCancelled):
                    progress(f'{path.name}: cancelled. Check Drive before retrying.')
                else:
                    progress(f'{path.name}: failed or unconfirmed. Check Drive before retrying.')
    return outcomes


def run(directory=None, state=STATE):
    # Leave active recording sessions alone. A stale app lock conservatively defers work.
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
    if (runtime / 'truedevs-glint.lock').exists():
        return
    directory = directory or Path.home() / 'Videos/RecIt'
    with archive_lock(state):
        options = config(state)
        if not options.get('enabled') or not options.get('folder'):
            event('archive.run', outcome='disabled')
            return
        from .drive_policy import DrivePolicy
        policy = DrivePolicy(state)
        # Configs saved before rclone have no remote; the default Drive remote is used.
        client = DriveClient(state, options.get('remote'))
        try:
            client.resolve_remote()
        except Exception as exc:
            diagnostic_failure('archive.run.no_remote', exc)
            return
        store = UploadStore(state / 'archive-uploads.json')
        if store.error:
            raise OSError(store.error)
        for path in recording_files(directory):
            try:
                # Only archive files observed unchanged across two periodic runs.
                if path.is_symlink() or policy.blocked(path):
                    continue
                row = store.get(path)
                if not row.get('observed_at'):
                    store.update(path, observed_at=time.time())
                    continue
                if time.time() - row['observed_at'] < 300:
                    continue
                upload_recording(path, options['folder'], store, client)
            except Exception as exc:
                # One failed upload must not prevent other recordings from being archived.
                # Log only the exception type: rclone messages can contain names and accounts.
                diagnostic_failure('archive.run.file_failed', exc)
                continue


if __name__ == '__main__':
    from .diagnostics import install
    # Separate from the app's log so two processes never rotate the same file.
    install(Path.home() / '.local/state/glint/archive')
    run()
