"""Recent in-app notifications, persisted as small private JSON. No Qt.

An unreadable or malformed file is left untouched: the log then works in memory
for this session and reports ``error`` instead of overwriting what is there.
"""
import json
import os
from pathlib import Path
import tempfile
import time

LIMIT = 50
KINDS = frozenset(('deleted', 'kept'))


class NotificationLog:
    def __init__(self, path):
        self.path = Path(path)
        self.error = ''
        self._entries = []
        try:
            payload = json.loads(self.path.read_text(encoding='utf-8'))
            entries = payload.get('notifications') if isinstance(payload, dict) else None
            if payload.get('version') != 1 or not isinstance(entries, list) or not all(
                    isinstance(entry, dict) and isinstance(entry.get('id'), str) for entry in entries):
                raise ValueError('Invalid notification format')
            self._entries = entries[:LIMIT]
        except FileNotFoundError:
            pass
        except (OSError, ValueError, UnicodeError, AttributeError):
            self.error = 'Notifications could not be read. The saved file was left untouched.'

    def entries(self):
        """Newest first."""
        return [dict(entry) for entry in self._entries]

    def unread(self):
        return sum(1 for entry in self._entries if not entry.get('read'))

    def add(self, kind, title, detail='', url=''):
        if kind not in KINDS:
            raise ValueError('Unknown notification kind.')
        now = time.time()
        entry = {'id': f'{now:.6f}-{len(self._entries)}', 'time': now, 'kind': kind,
                 'title': str(title)[:300], 'detail': str(detail)[:1000], 'url': str(url or '')[:300],
                 'read': False}
        self._entries = [entry, *self._entries][:LIMIT]
        self._save()
        return dict(entry)

    def mark_all_read(self):
        if any(not entry.get('read') for entry in self._entries):
            self._entries = [dict(entry, read=True) for entry in self._entries]
            self._save()

    def clear(self):
        self._entries = []
        self._save()

    def _save(self):
        """Best effort: notifications never block cleanup. Failures stay in memory."""
        if self.error:
            return False
        content = json.dumps({'version': 1, 'notifications': self._entries},
                             ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix=self.path.name + '.', delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
            return True
        except OSError:
            return False
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
