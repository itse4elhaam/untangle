"""Read-only archive observations, kept distinct from saved preferences."""
from datetime import datetime
import json
from pathlib import Path
import subprocess
import time

from .archive import STATE, config


def scheduler_status():
    try:
        result = subprocess.run(
            ['systemctl', '--user', 'show', 'untangle-archive.timer',
             '--property=LoadState', '--property=ActiveState', '--property=UnitFileState'],
            capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return 'Unknown. The user scheduler could not be inspected.'
    if result.returncode:
        return 'Unknown. The user scheduler could not be inspected.'
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if values.get('LoadState') == 'not-found':
        return 'Not installed.'
    if values.get('ActiveState') == 'active':
        return 'Active when checked. This does not prove an upload succeeded.'
    return 'Not active when checked. Use the setup guide to configure scheduling.'


def archive_status(state=STATE, scheduler='Not checked. Choose Refresh archive status.', now=None):
    options = config(state)
    destination = options.get('folder') or 'Not saved'
    verified = 'No verified upload recorded.'
    try:
        payload = json.loads((Path(state) / 'archive-uploads.json').read_text())
        if payload.get('version') != 1 or not isinstance(payload.get('uploads'), dict):
            raise ValueError('Invalid archive metadata')
        dates = [row['verified_at'] for row in payload['uploads'].values()
                 if isinstance(row, dict) and isinstance(row.get('verified_at'), (int, float))
                 and 0 < row['verified_at'] <= (time.time() if now is None else now)]
        if dates:
            latest = max(dates)
            stale = (time.time() if now is None else now) - latest >= 7 * 86400
            verified = datetime.fromtimestamp(latest).astimezone().strftime('%Y-%m-%d %H:%M %Z')
            verified += ' (over 7 days ago)' if stale else ''
            verified += '. Historical record; remote copy not checked here.'
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, AttributeError, OverflowError):
        verified = 'Unknown. Archive upload history could not be read.'
    return (f'Destination saved: {destination}\n'
            f'Archiving enabled: {"Yes" if options.get("enabled") else "No"}\n'
            f'Scheduler observed: {scheduler}\n'
            f'Last verified archive upload: {verified}')
