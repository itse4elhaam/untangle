"""Local Loom metadata. Reading a library never removes missing-file records."""
from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import tempfile


STATUSES = frozenset(('uploading', 'processing', 'uploaded', 'failed', 'uncertain', 'deleted'))


def _key(path):
    return str(Path(path).expanduser().absolute())


def _identity(path):
    try:
        info = Path(path).stat()
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    return {'device': info.st_dev, 'inode': info.st_ino,
            'size': info.st_size, 'mtime_ns': info.st_mtime_ns}


class UploadStore:
    """One UI-owned store at an explicit JSON file path; writes replace atomically.

    Malformed/unreadable stores remain untouched and expose ``error``. Mutations
    raise OSError in that case, so a failed read cannot erase saved links.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.error = ''
        self._uploads = {}
        try:
            payload = json.loads(self.path.read_text(encoding='utf-8'))
            if (not isinstance(payload, dict) or payload.get('version') != 1
                    or not isinstance(payload.get('uploads'), dict)
                    or any(not isinstance(key, str) or not isinstance(row, dict)
                           or not isinstance(row.get('identity'), dict)
                           for key, row in payload['uploads'].items())):
                raise ValueError('Invalid upload metadata format')
            self._uploads = payload['uploads']
        except FileNotFoundError:
            pass
        except (OSError, ValueError, UnicodeError):
            self.error = 'Upload metadata could not be read. The saved file was left untouched.'
        # A stopped process may already have published a video. Never retry it
        # automatically, even if the process stopped before saving its URL.
        restored = deepcopy(self._uploads)
        for row in restored.values():
            if row.get('status') in ('uploading', 'processing'):
                row.update(status='uncertain', error='Interrupted. Check Loom before uploading again.')
        if restored != self._uploads:
            try:
                self._save(restored)
            except OSError:
                self._uploads = restored
                self.error = 'Interrupted upload state could not be saved. Check Loom before retrying.'

    def get(self, video_path):
        row = self._uploads.get(_key(video_path), {})
        identity = _identity(video_path)
        if identity is None or row.get('identity') != identity:
            return {}
        return deepcopy({key: value for key, value in row.items() if key != 'identity'})

    file_identity = staticmethod(_identity)

    def update(self, video_path, *, expected_identity=None, **fields):
        if 'identity' in fields:
            raise ValueError('File identity is managed by UploadStore.')
        if 'status' in fields and fields['status'] not in STATUSES:
            raise ValueError('Unknown upload status.')
        identity = _identity(video_path)
        if identity is None:
            raise OSError('The local recording is missing or unreadable.')
        if expected_identity is not None and identity != expected_identity:
            raise OSError('The local recording changed during upload.')
        key = _key(video_path)
        uploads = deepcopy(self._uploads)
        row = uploads.get(key, {})
        if row.get('identity') != identity:
            row = {'identity': identity}
        row.update(deepcopy(fields))
        uploads[key] = row
        self._save(uploads)
        return self.get(video_path)

    def remove(self, video_path):
        """Forget local metadata only; never delete a recording or remote video."""
        key = _key(video_path)
        if key in self._uploads:
            uploads = deepcopy(self._uploads)
            del uploads[key]
            self._save(uploads)

    def rename(self, old, new):
        """Call after the local rename succeeds; do not move metadata to a new file."""
        old, new = _key(old), _key(new)
        if old == new or old not in self._uploads:
            return
        identity = _identity(new)
        if identity is None or self._uploads[old].get('identity') != identity:
            raise OSError('The renamed recording does not match its upload metadata.')
        if new in self._uploads and self._uploads[new].get('identity') == identity:
            raise FileExistsError('The destination already has upload metadata.')
        uploads = deepcopy(self._uploads)
        uploads[new] = uploads.pop(old)
        self._save(uploads)

    def mark_remote_deleted(self, video_path):
        """Only call after explicit evidence of remote deletion, never a 404."""
        if not self.get(video_path):
            return {}
        return self.update(video_path, status='deleted', url='', error='')

    def _save(self, uploads):
        if self.error:
            raise OSError(self.error)
        # Serialize before touching disk; callers may only store JSON values.
        content = json.dumps({'version': 1, 'uploads': uploads}, ensure_ascii=False,
                             indent=2, allow_nan=False) + '\n'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                             dir=self.path.parent,
                                             prefix=self.path.name + '.', delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._uploads = uploads
