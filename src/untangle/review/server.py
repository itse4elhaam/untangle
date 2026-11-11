"""Local review web app on 127.0.0.1. Serves only registered versions; never accepts file paths from the page."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, unquote, urlsplit

from .frames import Frames
from .sources import refetch
from .store import NAME, Review, ReviewError, STATUSES, default_root

WEB = Path(__file__).resolve().parent / 'web'
ASSETS = Path(__file__).resolve().parents[3] / 'assets'
STATIC = {
    'review.css': WEB / 'review.css', 'review.js': WEB / 'review.js',
    'mark.svg': ASSETS / 'untangle-mark.svg',
    'Inter-Regular.ttf': ASSETS / 'fonts' / 'Inter-Regular.ttf',
    'Inter-Medium.ttf': ASSETS / 'fonts' / 'Inter-Medium.ttf',
    'Inter-SemiBold.ttf': ASSETS / 'fonts' / 'Inter-SemiBold.ttf',
}
MAX_BODY = 64 * 1024
FRAME = re.compile(r'^(\d{1,7})\.jpg$')


def reviewer_name():
    name = os.environ.get('UNTANGLE_REVIEWER', '').strip()
    if not name:
        try:
            import pwd
            name = pwd.getpwuid(os.getuid()).pw_gecos.split(',')[0].strip()
        except (ImportError, KeyError):
            name = ''
    return (name or os.environ.get('USER') or 'Reviewer')[:80]


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root, port=8740, reviewer=None):
        self.root = Path(root or default_root()).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.reviewer = reviewer or reviewer_name()
        self.fetching = set()
        self.fetching_lock = threading.Lock()
        self.problems = {}
        last = None
        for candidate in range(port, port + 20) if port else [0]:
            try:
                super().__init__(('127.0.0.1', candidate), Handler)
                break
            except OSError as error:
                last = error
        else:
            raise ReviewError(f'No free port from {port}: {last}')
        self.port = self.server_address[1]
        self.url = f'http://127.0.0.1:{self.port}'
        self.allowed_hosts = {f'127.0.0.1:{self.port}', f'localhost:{self.port}'}

    def announce(self):
        (self.root / '.server.json').write_text(json.dumps({'url': self.url, 'pid': os.getpid()}), encoding='utf-8')

    def withdraw(self):
        marker = self.root / '.server.json'
        try:
            if json.loads(marker.read_text()).get('pid') == os.getpid():
                marker.unlink()
        except (OSError, ValueError):
            pass

    def prepare(self, review, version):
        """Make frames available: re-download pruned sources from their origin, then extract."""
        key = (review.name, version['id'])
        frames = Frames(review, version)
        if frames.ready():
            return
        if Path(version['path']).is_file():
            frames.start(on_error=lambda error: self.problems.__setitem__(key, str(error)))
            return
        if not version.get('origin'):
            return
        with self.fetching_lock:
            if key in self.fetching:
                return
            self.fetching.add(key)

        def work():
            try:
                refetch(review, version)
                Frames(review, version).extract()
            except ReviewError as error:
                self.problems[key] = str(error)
            finally:
                with self.fetching_lock:
                    self.fetching.discard(key)
        threading.Thread(target=work, daemon=True).start()


def running_url(root=None):
    """URL of a review server already serving this root, if one is alive."""
    marker = Path(root or default_root()).expanduser() / '.server.json'
    try:
        info = json.loads(marker.read_text())
        os.kill(int(info['pid']), 0)
        return info['url']
    except (OSError, ValueError, KeyError):
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = 'UntangleReview'
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    # ---- responses
    def send(self, code, body=b'', kind='application/json', headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def fail(self, code, message):
        self.send(code, {'error': message})

    def guard(self):
        # Reject DNS-rebinding hosts and cross-site writes; the server holds private media.
        if self.headers.get('Host') not in self.server.allowed_hosts:
            self.fail(403, 'Unexpected host.')
            return False
        origin = self.headers.get('Origin')
        if self.command == 'POST':
            if origin and urlsplit(origin).netloc not in self.server.allowed_hosts:
                self.fail(403, 'Cross-site request refused.')
                return False
            if not self.headers.get('Content-Type', '').startswith('application/json'):
                self.fail(415, 'Send JSON.')
                return False
        return True

    def review(self, name):
        if not NAME.match(name):
            raise ReviewError('Unknown review.')
        return Review.open(name, self.server.root)

    # ---- GET
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.guard():
            return
        url = urlsplit(self.path)
        parts = [unquote(part) for part in url.path.strip('/').split('/') if part]
        try:
            if not parts or parts[0] == 'r':
                return self.send(200, (WEB / 'index.html').read_bytes(), 'text/html; charset=utf-8',
                                 {'Cache-Control': 'no-store'})
            if parts[0] == 'static' and len(parts) == 2 and parts[1] in STATIC:
                path = STATIC[parts[1]]
                kind = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
                if path.suffix == '.ttf':
                    kind = 'font/ttf'
                return self.send(200, path.read_bytes(), kind, {'Cache-Control': 'no-cache'})
            if parts[:2] == ['api', 'reviews']:
                return self.get_api(parts[2:], parse_qs(url.query))
        except ReviewError as error:
            return self.fail(404, str(error))
        self.fail(404, 'Not found.')

    def get_api(self, parts, query):
        if not parts:
            return self.send(200, {'reviewer': self.server.reviewer, 'root': str(self.server.root),
                                   'reviews': Review.list(self.server.root)})
        review = self.review(parts[0])
        if len(parts) == 1:
            revision = review.revision()
            data = review.load()
            for version in data['versions']:
                self.server.prepare(review, version)
            frames = {}
            for version in data['versions']:
                status = Frames(review, version).status()
                problem = self.server.problems.get((review.name, version['id']))
                if problem and status['state'] != 'ready':
                    status = dict(status, state='error', error=problem)
                if status['state'] == 'missing-source' and (review.name, version['id']) in self.server.fetching:
                    status = dict(status, state='downloading')
                status['stale'] = Frames(review, version).stale()
                status['playable'] = Path(version['path']).is_file()
                frames[version['id']] = status
            settled = all(status['state'] == 'ready' for status in frames.values())
            tag = f'"{revision}"'
            if settled and self.headers.get('If-None-Match') == tag:
                return self.send(304, headers={'ETag': tag})
            for version in data['versions']:
                version.pop('path', None)  # The page never needs local paths.
            return self.send(200, dict(data, name=review.name, revision=revision, frames=frames,
                                       reviewer=self.server.reviewer, statuses=STATUSES),
                             headers={'ETag': tag, 'Cache-Control': 'no-cache'})
        data = review.load()
        if len(parts) == 4 and parts[1] == 'frames':
            version = review.version(data, parts[2])
            match = FRAME.match(parts[3])
            if not match:
                return self.fail(404, 'Not found.')
            frame = int(match.group(1))
            if frame >= version['frames']:
                return self.fail(404, f'{version["id"]} has {version["frames"]} frames.')
            path = Frames(review, version).file(frame)
            if not path:
                self.server.prepare(review, version)
                return self.send(202, {'pending': True}, headers={'Retry-After': '1'})
            return self.send(200, path.read_bytes(), 'image/jpeg', {'Cache-Control': 'private, max-age=86400'})
        if len(parts) == 3 and parts[1] == 'media':
            version = review.version(data, parts[2])
            return self.stream(Path(version['path']))
        return self.fail(404, 'Not found.')

    def stream(self, path):
        if not path.is_file():
            return self.fail(404, 'The video is not on this computer right now.')
        size = path.stat().st_size
        start, end = 0, size - 1
        match = re.match(r'bytes=(\d*)-(\d*)$', self.headers.get('Range', ''))
        code = 200
        if match and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
            else:
                start = max(0, size - int(match.group(2)))
            if start > end or start >= size:
                return self.send(416, headers={'Content-Range': f'bytes */{size}'})
            code = 206
        length = end - start + 1
        self.send_response(code)
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'video/mp4')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(length))
        if code == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command == 'HEAD':
            return
        with open(path, 'rb') as handle:
            handle.seek(start)
            remaining = length
            try:
                while remaining:
                    chunk = handle.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    # ---- POST
    def do_POST(self):
        if not self.guard():
            return
        length = int(self.headers.get('Content-Length') or 0)
        if length > MAX_BODY:
            return self.fail(413, 'Too large.')
        try:
            body = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self.fail(400, 'Send a JSON object.')
        parts = [unquote(part) for part in urlsplit(self.path).path.strip('/').split('/') if part]
        if parts[:2] != ['api', 'reviews'] or len(parts) < 4 or parts[3] != 'comments':
            return self.fail(404, 'Not found.')
        try:
            review = self.review(parts[2])
            author = self.server.reviewer
            if len(parts) == 4:
                result = review.add_comment(body.get('version'), body.get('frame', -1), body.get('text'),
                                            author, region=body.get('region'))
                return self.send(201, result)
            if len(parts) == 6 and parts[5] == 'replies':
                return self.send(200, review.reply(parts[4], body.get('text'), author))
            if len(parts) == 6 and parts[5] == 'status':
                return self.send(200, review.set_status(parts[4], body.get('status'), author,
                                                        version_id=body.get('version')))
        except ReviewError as error:
            return self.fail(400, str(error))
        except (TypeError, ValueError):
            return self.fail(400, 'Malformed request.')
        self.fail(404, 'Not found.')


def serve(root=None, port=8740, reviewer=None, ready=None):
    server = ReviewServer(root, port, reviewer)
    server.announce()
    if ready:
        ready(server)
    try:
        server.serve_forever()
    finally:
        server.withdraw()
        server.server_close()
