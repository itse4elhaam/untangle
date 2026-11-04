"""Persistent, local-only Drive exclusions, shared by manual and timed uploads."""
import json
from pathlib import Path

from .drive import DriveClient
from .upload_store import UploadStore


class DrivePolicy:
    def __init__(self, state=None):
        self.state = state or Path.home() / '.local/share/glint/google-drive'
        self.path = self.state / 'upload-exclusions.json'
        try:
            data = json.loads(self.path.read_text())
            if (not isinstance(data, dict) or data.get('version') != 1
                    or not isinstance(data.get('excluded'), list)
                    or any(not isinstance(key, str) for key in data['excluded'])):
                raise ValueError('Invalid exclusions')
            self.excluded = set(data['excluded'])
        except FileNotFoundError:
            self.excluded = set()
        except (OSError, ValueError, UnicodeError):
            raise OSError('Drive upload exclusions could not be read. Uploads are blocked.') from None

    @staticmethod
    def key(path):
        identity = UploadStore.file_identity(path)
        if identity is None or Path(path).is_symlink():
            raise OSError('The recording is missing or is a symbolic link.')
        # Follow the same local file through renames and edits.
        return f"{identity['device']}:{identity['inode']}"

    def blocked(self, path):
        return self.key(path) in self.excluded

    @classmethod
    def set_blocked(cls, paths, blocked, state=None):
        from .archive import STATE, archive_lock
        state = state or STATE
        with archive_lock(state):
            policy = cls(state)
            keys = {policy.key(path) for path in paths}
            if blocked:
                policy.excluded.update(keys)
            else:
                policy.excluded.difference_update(keys)
            DriveClient(state).save_private(policy.path, json.dumps(
                {'version': 1, 'excluded': sorted(policy.excluded)}))
