"""rclone processes for Google Drive, shared by archive uploads and the review tool.

Standard library only, so ``review`` can import it without Qt. Commands run
without a shell, never prompt (``--ask-password=false``, no stdin), and are
bounded by a timeout and an optional cancel event. Untangle never runs
``rclone config``; remotes come from the user's own rclone setup.
"""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

from .diagnostics import event

SETUP = ('Run "rclone config" in a terminal, add a remote of type "drive" for your Google '
         'account, then try again. Untangle never runs rclone config for you.')
# rclone exit codes 3 and 4: directory or file not found.
NOT_FOUND = frozenset((3, 4))


class RcloneError(Exception):
    """A failure whose message is safe to show; rclone's own output is kept in ``detail``."""
    def __init__(self, message, *, returncode=None, detail=''):
        super().__init__(message)
        self.returncode = returncode
        self.detail = detail


class RcloneMissing(RcloneError):
    def __init__(self):
        super().__init__('rclone is not installed. Install it from your package manager '
                         '(for example "sudo apt install rclone") or https://rclone.org/install/, '
                         'then ' + SETUP[0].lower() + SETUP[1:])


class NoDriveRemote(RcloneError):
    def __init__(self):
        super().__init__('No rclone Google Drive remote is configured. ' + SETUP)


class RcloneCancelled(RcloneError):
    def __init__(self):
        super().__init__('Cancelled. Check Drive before retrying; a partial transfer is not kept.')


class RcloneTimeout(RcloneError):
    def __init__(self):
        super().__init__('rclone did not finish in time. Check your connection and try again.')


class RcloneNotFound(RcloneError):
    pass


def executable():
    """PATH first; systemd user services often lack ~/.local/bin, so check it too."""
    found = shutil.which('rclone')
    if found:
        return found
    for candidate in (Path.home() / '.local/bin/rclone', Path('/usr/local/bin/rclone'),
                      Path('/usr/bin/rclone')):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _pump(stream, sink):
    try:
        for line in stream:
            sink.put(line)
    finally:
        sink.put(None)


def run(args, *, timeout, cancel=None, on_log=None, capture=True):
    """Run ``rclone *args`` and return stdout. ``on_log`` receives parsed JSON log records."""
    binary = executable()
    if binary is None:
        event('rclone.run', operation=args[0], outcome='missing')
        raise RcloneMissing()
    started = time.monotonic()
    process = subprocess.Popen(
        [binary, *args, '--ask-password=false'], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', errors='replace')
    output, logs = [], queue.Queue()
    readers = [threading.Thread(target=_pump, args=(process.stderr, logs), daemon=True)]
    if capture:
        readers.append(threading.Thread(target=lambda: output.append(process.stdout.read()), daemon=True))
    for reader in readers:
        reader.start()
    errors, open_streams, outcome = [], 1, 'exit'
    try:
        while open_streams or process.poll() is None:
            if cancel is not None and cancel.is_set():
                outcome = 'cancelled'
                raise RcloneCancelled()
            if time.monotonic() - started > timeout:
                outcome = 'timeout'
                raise RcloneTimeout()
            try:
                line = logs.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                open_streams = 0
                continue
            try:
                record = json.loads(line)
            except ValueError:
                record = {'level': 'error' if 'ERROR' in line else 'info', 'msg': line.strip()}
            if not isinstance(record, dict):
                continue
            if record.get('level') in ('error', 'critical'):
                errors.append(str(record.get('msg', '')).strip())
            if on_log is not None:
                on_log(record)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for reader in readers:
            reader.join(timeout=5)
        # Never log rclone output: it can contain file names and account details.
        event('rclone.run', operation=args[0], outcome=outcome, returncode=process.returncode,
              duration_ms=round((time.monotonic() - started) * 1000))
    detail = errors[-1] if errors else ''
    if process.returncode in NOT_FOUND:
        raise RcloneNotFound('Not found on Drive.', returncode=process.returncode, detail=detail)
    if process.returncode:
        message = 'rclone could not finish this action.'
        lowered = detail.lower()
        if any(word in lowered for word in ('invalid_grant', 'token', 'unauthenticated', '401')):
            message = ('rclone\'s Google sign-in has expired or was revoked. Run "rclone config '
                       'reconnect <remote>:" in a terminal, then try again.')
        raise RcloneError(message, returncode=process.returncode, detail=detail)
    return ''.join(output)


def drive_remotes(*, timeout=30, cancel=None):
    """Names (with trailing colon) of remotes of type ``drive``, in rclone's order."""
    listing = run(['listremotes', '--long'], timeout=timeout, cancel=cancel)
    remotes = [line.split() for line in listing.splitlines() if line.strip()]
    return [parts[0] for parts in remotes if len(parts) > 1 and parts[1] == 'drive']


def preferred(remotes):
    # Prefer a remote rooted at "My Drive" when several exist; folder-scoped ones still resolve IDs.
    return next((name for name in remotes if name.startswith('gdrive')), remotes[0] if remotes else None)


def normalize(remote):
    return remote if remote.endswith(':') else remote + ':'


def drive_remote(env_var):
    """The remote named by ``env_var``, else the preferred Drive remote, else None."""
    configured = os.environ.get(env_var)
    if configured:
        return normalize(configured)
    if executable() is None:
        return None
    try:
        return preferred(drive_remotes())
    except RcloneError:
        return None
