"""Extract every frame of a version once, on the constant-rate grid comments are anchored to."""
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import threading

from .sources import refetch
from .store import ReviewError, identity

LONG_EDGE = int(os.environ.get('UNTANGLE_REVIEW_FRAME_SIZE', '1280'))
BYTES_PER_PIXEL = 0.2  # Generous JPEG estimate for the free-space check.
RESERVE = 1 << 30
_running = {}
_running_lock = threading.Lock()


class Frames:
    def __init__(self, review, version):
        self.review = review
        self.version = version
        root = review.path / 'frames'
        self.dir = root / version['id']
        self.partial = root / f'.{version["id"]}.partial'
        self.lock_file = root / f'.{version["id"]}.lock'
        self.error_file = root / f'.{version["id"]}.error'

    def size(self):
        width, height = self.version['width'], self.version['height']
        scale = min(1.0, LONG_EDGE / max(width, height, 1))
        return max(2, round(width * scale / 2) * 2), max(2, round(height * scale / 2) * 2)

    def ready(self):
        return (self.dir / '.complete').is_file()

    def file(self, frame):
        """The cached JPG for a frame, or None while it is not written yet."""
        name = f'{int(frame):06d}.jpg'
        if self.ready():
            path = self.dir / name
            return path if path.is_file() else None
        current, following = self.partial / name, self.partial / f'{int(frame) + 1:06d}.jpg'
        # ffmpeg writes frames in order, so a frame is complete once the next one exists.
        return current if current.is_file() and following.is_file() else None

    def status(self):
        key = (str(self.review.path), self.version['id'])
        source = Path(self.version['path'])
        if self.ready():
            return {'state': 'ready', 'done': self.version['frames'], 'total': self.version['frames']}
        if self.error_file.is_file():
            return {'state': 'error', 'error': self.error_file.read_text(encoding='utf-8')[:500],
                    'done': 0, 'total': self.version['frames']}
        done = sum(1 for _ in os.scandir(self.partial)) if self.partial.is_dir() else 0
        with _running_lock:
            running = key in _running and _running[key].is_alive()
        if running or done:
            return {'state': 'extracting', 'done': done, 'total': self.version['frames']}
        if not source.is_file():
            return {'state': 'missing-source', 'done': 0, 'total': self.version['frames']}
        return {'state': 'pending', 'done': 0, 'total': self.version['frames']}

    def stale(self):
        source = Path(self.version['path'])
        return source.is_file() and identity(source) != self.version.get('identity')

    def check_space(self):
        width, height = self.size()
        needed = int(width * height * BYTES_PER_PIXEL * self.version['frames']) + RESERVE
        free = shutil.disk_usage(self.review.path).free
        if free < needed:
            raise ReviewError(f'Extracting {self.version["id"]} needs about {needed >> 20} MB free; '
                              f'only {free >> 20} MB is left. Run `untangle-review prune` on finished reviews.')

    def extract(self):
        """Extract all frames, blocking. Safe to call from several processes; one does the work."""
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_file, 'a+') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                if self.ready():
                    return self.version['frames']
                source = Path(self.version['path'])
                if not source.is_file():
                    raise ReviewError(f'The video for {self.version["id"]} is gone ({source}). '
                                      'Fetch it again with `untangle-review fetch`.')
                self.check_space()
                self.error_file.unlink(missing_ok=True)
                shutil.rmtree(self.partial, ignore_errors=True)
                self.partial.mkdir(parents=True)
                width, height = self.size()
                command = ['ffmpeg', '-nostdin', '-v', 'error', '-i', str(source), '-map', '0:v:0', '-an', '-sn',
                           '-vf', f'fps={self.version["rate"]},scale={width}:{height}:flags=lanczos',
                           '-q:v', '3', '-start_number', '0', str(self.partial / '%06d.jpg')]
                result = subprocess.run(command, capture_output=True, text=True)
                count = sum(1 for _ in os.scandir(self.partial))
                if result.returncode or not count:
                    message = (result.stderr.strip() or 'ffmpeg wrote no frames')[-500:]
                    self.error_file.write_text(message, encoding='utf-8')
                    shutil.rmtree(self.partial, ignore_errors=True)
                    raise ReviewError(f'Frame extraction failed for {self.version["id"]}: {message}')
                (self.partial / '.complete').write_text(str(count), encoding='utf-8')
                shutil.rmtree(self.dir, ignore_errors=True)
                os.replace(self.partial, self.dir)
                if count != self.version['frames']:
                    self._record_count(count)
                return count
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _record_count(self, count):
        # The decoded frame count is authoritative over ffprobe's estimate.
        def change(data):
            for version in data['versions']:
                if version['id'] == self.version['id']:
                    version['frames'] = count
        self.review.mutate(change)
        self.version['frames'] = count

    def start(self, on_error=None):
        """Extract in a background thread unless that is already happening or done."""
        if self.ready():
            return
        key = (str(self.review.path), self.version['id'])
        with _running_lock:
            if key in _running and _running[key].is_alive():
                return

            def work():
                try:
                    self.extract()
                except ReviewError as error:
                    if on_error:
                        on_error(error)
            thread = threading.Thread(target=work, name=f'frames-{self.version["id"]}', daemon=True)
            _running[key] = thread
            thread.start()


def crop(frame_path, region, destination):
    """Write the region of a cached frame (fractions of the frame) to a JPG, for agents to inspect."""
    x, y, w, h = region
    expression = f'crop=iw*{w}:ih*{h}:iw*{x}:ih*{y}'
    result = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(frame_path), '-vf', expression,
                             '-q:v', '2', str(destination)], capture_output=True, text=True)
    if result.returncode:
        raise ReviewError(f'Could not crop the frame: {result.stderr.strip()[-300:]}')
    return destination


def frame_path(review, version_id, frame):
    """Path of one cached frame, downloading the source and extracting frames first when needed."""
    version = review.version(review.load(), version_id)
    frames = Frames(review, version)
    if not frames.ready():
        if not Path(version['path']).is_file():
            refetch(review, version)
        frames.extract()
        frames = Frames(review, review.version(review.load(), version_id))
    path = frames.file(frame)
    if not path:
        raise ReviewError(f'{version_id} has no frame {frame}.')
    return path
