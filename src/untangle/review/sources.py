"""Bring a video into a review from a local path, a Google Drive link, or a direct URL.

Drive files are fetched by file ID with rclone, using an already configured
Drive remote, so private files work without new credentials. Publicly shared
files fall back to Google's direct download. Downloads land in the review's
``sources/`` cache and can be pruned and fetched again from the recorded origin.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from .store import ReviewError, identity

DRIVE = re.compile(r'^https://(?:drive|docs)\.google\.com/.*?(?:/d/|[?&]id=)([A-Za-z0-9_-]{20,})')
VIDEO_TYPES = ('video/', 'application/octet-stream', 'binary/octet-stream')


def drive_id(reference):
    match = DRIVE.match(str(reference).strip())
    return match.group(1) if match else None


def is_url(reference):
    return str(reference).startswith(('http://', 'https://'))


def drive_remote():
    """The rclone remote for Drive: UNTANGLE_REVIEW_DRIVE_REMOTE, else the first Drive-type remote."""
    configured = os.environ.get('UNTANGLE_REVIEW_DRIVE_REMOTE')
    if configured:
        return configured if configured.endswith(':') else configured + ':'
    if not shutil.which('rclone'):
        return None
    result = subprocess.run(['rclone', 'listremotes', '--long'], capture_output=True, text=True, timeout=30)
    remotes = [line.split() for line in result.stdout.splitlines() if line.strip()]
    drives = [parts[0] for parts in remotes if len(parts) > 1 and parts[1] == 'drive']
    # Prefer a remote rooted at "My Drive" when several exist; folder-scoped ones still resolve IDs.
    return next((name for name in drives if name.startswith('gdrive')), drives[0] if drives else None)


def fetch(review, reference, progress=None):
    """Resolve a reference to a local file. Returns (path, origin or None)."""
    file_id = drive_id(reference)
    if file_id:
        return fetch_drive(review, file_id, reference, progress), {'kind': 'drive', 'id': file_id, 'url': reference}
    if is_url(reference):
        return fetch_url(review, reference, progress), {'kind': 'url', 'url': reference}
    path = Path(reference).expanduser()
    if not path.is_file():
        raise ReviewError(f'{reference} is not a file, a Google Drive link or a URL.')
    return path.resolve(), None


def _cached(folder):
    if folder.is_dir():
        files = [path for path in folder.iterdir() if path.is_file() and not path.name.startswith('.')]
        if files:
            return files[0]
    return None


def _check_space(review, needed=512 << 20):
    review.path.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(review.path).free
    if free < needed:
        raise ReviewError(f'Only {free >> 20} MB is free; downloading needs more room. '
                          'Run `untangle-review prune` on finished reviews.')


def fetch_drive(review, file_id, url, progress=None):
    folder = review.source_dir() / file_id
    existing = _cached(folder)
    if existing:
        return existing
    _check_space(review)
    staging = review.source_dir() / f'.{file_id}.partial'
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    errors = []
    remote = drive_remote()
    if remote:
        if progress:
            progress(f'Downloading {file_id} from Drive with rclone ({remote})')
        result = subprocess.run(['rclone', 'backend', 'copyid', remote, file_id, f'{staging}/'],
                                capture_output=True, text=True)
        if result.returncode == 0 and _cached(staging):
            return _publish(staging, folder)
        errors.append(f'rclone {remote}: {_last_line(result.stderr)}')
    else:
        errors.append('no rclone Drive remote is configured')
    if progress:
        progress('Trying the public Drive download')
    try:
        public = f'https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t'
        _download(public, staging, fallback_name=f'{file_id}.mp4')
        return _publish(staging, folder)
    except ReviewError as error:
        errors.append(f'public link: {error}')
    shutil.rmtree(staging, ignore_errors=True)
    raise ReviewError('Could not download the Drive file. ' + '; '.join(errors) +
                      '. Configure an rclone Drive remote (or set UNTANGLE_REVIEW_DRIVE_REMOTE), share the file '
                      'by link, or download it yourself and add the local path with --origin set to the link.')


def fetch_url(review, url, progress=None):
    folder = review.source_dir() / ('url-' + re.sub(r'[^A-Za-z0-9]+', '-', urllib.parse.urlsplit(url).path)[-40:].strip('-'))
    existing = _cached(folder)
    if existing:
        return existing
    _check_space(review)
    staging = review.source_dir() / f'.{folder.name}.partial'
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    if progress:
        progress(f'Downloading {url}')
    try:
        _download(url, staging, fallback_name='video.mp4')
    except ReviewError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return _publish(staging, folder)


def _download(url, staging, fallback_name):
    request = urllib.request.Request(url, headers={'User-Agent': 'untangle-review'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            kind = response.headers.get('Content-Type', '')
            if not kind.startswith(VIDEO_TYPES):
                raise ReviewError(f'the server returned {kind or "no content type"}, not a video '
                                  '(the file may be private)')
            disposition = response.headers.get('Content-Disposition', '')
            match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', disposition)
            name = Path(urllib.parse.unquote(match.group(1))).name if match else fallback_name
            with open(staging / (name or fallback_name), 'wb') as handle:
                shutil.copyfileobj(response, handle, 1 << 20)
    except urllib.error.URLError as error:
        raise ReviewError(str(getattr(error, 'reason', error))) from error


def _publish(staging, folder):
    shutil.rmtree(folder, ignore_errors=True)
    os.replace(staging, folder)
    return _cached(folder)


def _last_line(text):
    lines = [line for line in text.strip().splitlines() if 'NOTICE' not in line]
    return (lines[-1] if lines else 'failed')[-300:]


def label_from(path):
    stem = Path(path).stem
    return re.sub(r'\s+', ' ', stem).strip()[:80] or 'version'


def add(review, reference, label=None, captions=None, edl=None, note='', origin=None, progress=None):
    """Fetch if needed and register a new version."""
    path, fetched_origin = fetch(review, reference, progress)
    if origin and not fetched_origin:
        fetched_origin = {'kind': 'drive', 'id': drive_id(origin), 'url': origin} if drive_id(origin) else {
            'kind': 'url', 'url': origin}
    return review.add_version(path, label=label or label_from(path), captions=captions, edl=edl, note=note,
                              origin=fetched_origin)


def refetch(review, version):
    """Download a pruned version again from its recorded origin."""
    origin = version.get('origin') or {}
    if Path(version['path']).is_file():
        return Path(version['path'])
    if origin.get('kind') == 'drive':
        path = fetch_drive(review, origin['id'], origin['url'])
    elif origin.get('kind') == 'url':
        path = fetch_url(review, origin['url'])
    else:
        raise ReviewError(f'{version["id"]} came from {version["path"]}, which is gone, and has no link to fetch.')
    def change(data):
        for item in data['versions']:
            if item['id'] == version['id']:
                item['path'], item['identity'] = str(path), identity(path)
    review.mutate(change)
    version['path'], version['identity'] = str(path), identity(path)
    return path
