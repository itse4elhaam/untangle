"""Decide whether a verified Loom upload may replace its local recording. No Qt.

Loom exposes no checksum, so "verified" means: the upload published with a valid
share link, the local file still has the identity it had when the upload started,
``loom video get`` reports that same video available and playable, and Loom's
playable duration matches the local file's (ffprobe) within a second or 1%.
Today's CLI omits ``isComplete``; ``playableDuration`` only appears once Loom can
play the video. Anything missing or unknown keeps the file.
"""
import json
from pathlib import Path
import shutil
import subprocess

from .loom import valid_share_url, video_id, video_playable

PREFERENCE = 'loom_delete_verified_local'

REASONS = {
    'disabled': 'Automatic deletion is off in Sharing.',
    'processing': 'Loom is still processing the video.',
    'not_uploaded': 'Loom did not confirm the upload.',
    'no_link': 'No valid Loom link is saved.',
    'changed': 'The local file changed after the upload started.',
    'remote_unverified': 'Loom could not confirm the video is available.',
    'remote_incomplete': 'Loom has not confirmed the video finished processing.',
    'remote_mismatch': 'Loom returned a different video.',
    'duration_mismatch': 'The Loom video length does not match the local recording.',
    'local_unknown': 'The local recording length could not be read.',
    'recording': 'Untangle was recording or saving.',
    'upload': 'The recording was uploading.',
    'playback': 'The recording was playing in Recordings.',
    'review': 'The recording is a version in a frame review.',
    'review_unknown': 'A frame review could not be read.',
    'metadata': 'The Loom link could not be saved for the deleted file.',
    'delete_failed': 'The file could not be deleted.',
    'closing': 'Untangle was closing.',
}
# Busy states that end on their own; cleanup retries for a while instead of giving up.
TRANSIENT = frozenset(('recording', 'upload', 'playback', 'remote_incomplete'))


def decide(*, enabled, row, upload_identity, current_identity, remote=None, local_duration=None):
    """Return a reason code. 'check_remote' means only the Loom probe remains."""
    if not enabled:
        return 'disabled'
    # Uploads publish as processing; only the fresh video-get below can prove playability.
    if row.get('status') not in ('uploaded', 'processing'):
        return 'not_uploaded'
    stored_id = video_id(row.get('remote_id') or '')
    if not valid_share_url(row.get('url')) or not stored_id:
        return 'no_link'
    if current_identity is None or current_identity != upload_identity:
        return 'changed'
    if remote is None:
        return 'check_remote'
    if remote.get('status') != 'available' or not remote.get('remote_id'):
        return 'remote_unverified'
    if video_id(remote['remote_id']) != stored_id:
        return 'remote_mismatch'
    if remote.get('url') and valid_share_url(remote['url']) != valid_share_url(row['url']):
        return 'remote_mismatch'
    if not video_playable(remote) or not remote.get('duration'):
        return 'remote_incomplete'
    if not local_duration:
        return 'local_unknown'
    if abs(remote['duration'] - local_duration) > max(1.0, local_duration * .01):
        return 'duration_mismatch'
    return 'verified'


def local_duration(path):
    """Container duration in seconds from ffprobe, or None. Reads only this local file."""
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        return None
    try:
        probe = subprocess.run([ffprobe, '-v', 'error', '-protocol_whitelist', 'file,pipe',
                                '-show_entries', 'format=duration', '-of', 'json', str(path)],
                               capture_output=True, text=True, timeout=10, check=True)
        value = float(json.loads(probe.stdout)['format']['duration'])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None
    return value if 0 < value < 1e7 else None


def review_reason(path, root=None):
    """'review' when a frame review registers this file, 'review_unknown' when one is unreadable."""
    from .review.store import default_root
    root = Path(root or default_root())
    try:
        target = Path(path).resolve()
        info = target.stat()
    except OSError:
        return ''
    try:
        candidates = sorted(root.glob('*/review.json')) if root.is_dir() else []
    except OSError:
        return 'review_unknown'
    for review in candidates:
        try:
            versions = json.loads(review.read_text(encoding='utf-8')).get('versions', [])
            sources = [Path(str(version['path'])) for version in versions if version.get('path')]
        except (OSError, ValueError, AttributeError, TypeError, KeyError):
            return 'review_unknown'
        for source in sources:
            try:
                if source.resolve() == target:
                    return 'review'
                other = source.stat()
            except OSError:
                continue
            if (other.st_dev, other.st_ino) == (info.st_dev, info.st_ino):
                return 'review'
    return ''


def unlink_unchanged(path, identity, blocked):
    """The manual-deletion guard: refuse busy, symlinked or changed files, then unlink."""
    from .upload_store import UploadStore
    path = Path(path)
    if blocked(path) or path.is_symlink() or UploadStore.file_identity(path) != identity:
        raise OSError('The recording changed or is in use.')
    path.unlink()
