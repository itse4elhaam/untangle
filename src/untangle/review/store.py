"""Review projects: versions of one video, frame-anchored comments and their threads.

A review is a directory holding ``review.json`` plus disposable caches
(``sources/`` for downloaded media, ``frames/`` for extracted stills). Writers
take an exclusive ``flock`` and replace the file atomically, so the browser
server, the MCP server and the CLI can run at the same time.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import time

SCHEMA = 1
STATUSES = ('open', 'addressed', 'resolved')
NAME = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
MAX_TEXT = 8000


class ReviewError(Exception):
    """A request the store refuses, with a message fit to show a person or agent."""


def default_root():
    return Path(os.environ.get('UNTANGLE_REVIEW_ROOT') or Path.home() / 'Videos' / 'reviews').expanduser()


def slug(text, fallback='review'):
    value = re.sub(r'[^a-z0-9]+', '-', str(text).lower()).strip('-')[:64].strip('-')
    return value or fallback


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def fraction(text):
    try:
        top, _, bottom = str(text).partition('/')
        value = float(top) / float(bottom or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0
    return value


def probe(path):
    """Describe a video with ffprobe. Raises ReviewError when it is not decodable video."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
             'stream=width,height,r_frame_rate,avg_frame_rate,nb_frames,codec_name:format=duration',
             '-of', 'json', str(path)],
            capture_output=True, text=True, timeout=60)
    except FileNotFoundError as error:
        raise ReviewError('ffprobe is not installed; install FFmpeg to review videos.') from error
    data = json.loads(result.stdout or '{}')
    if result.returncode or not data.get('streams'):
        raise ReviewError(f'{Path(path).name} has no readable video stream.')
    stream = data['streams'][0]
    fps = fraction(stream.get('r_frame_rate'))
    average = fraction(stream.get('avg_frame_rate'))
    duration = float(data.get('format', {}).get('duration') or 0)
    if fps <= 0 or duration <= 0:
        raise ReviewError(f'{Path(path).name} has no usable frame rate or duration.')
    counted = int(stream.get('nb_frames') or 0)
    return {
        'width': int(stream.get('width') or 0), 'height': int(stream.get('height') or 0),
        'codec': stream.get('codec_name', ''), 'rate': stream.get('r_frame_rate'),
        'fps': round(fps, 6), 'duration': round(duration, 3),
        'frames': counted or max(1, round(duration * fps)),
        # The cache is extracted on a constant-rate grid; variable-rate sources can drift from the player.
        'variable_rate': bool(average) and abs(average - fps) > 0.01,
    }


def identity(path):
    stat = Path(path).stat()
    return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def load_captions(path):
    """Accept caption groups (lists of timed words), timed segments, or SRT. Returns [{start, end, text}]."""
    path = Path(path).expanduser()
    text = path.read_text(encoding='utf-8')
    if path.suffix.lower() == '.srt':
        segments = []
        pattern = re.compile(r'(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)\s*\n(.*?)(?:\n\s*\n|\Z)', re.S)
        for match in pattern.finditer(text.replace('\r\n', '\n')):
            h1, m1, s1, f1, h2, m2, s2, f2, body = match.groups()
            segments.append({'start': int(h1) * 3600 + int(m1) * 60 + int(s1) + int(f1) / 1000,
                             'end': int(h2) * 3600 + int(m2) * 60 + int(s2) + int(f2) / 1000,
                             'text': ' '.join(body.split())})
        return segments
    data = json.loads(text)
    segments = []
    for item in data:
        if isinstance(item, list) and item:
            segments.append({'start': float(item[0]['start']), 'end': float(item[-1]['end']),
                             'text': ' '.join(str(word['word']) for word in item)})
        elif isinstance(item, dict) and 'text' in item:
            segments.append({'start': float(item['start']), 'end': float(item['end']), 'text': str(item['text'])})
    if not segments and data:
        raise ReviewError(f'{path.name} is not a recognised caption file.')
    return segments


def load_edl(path):
    """An edit decision list maps output time to source time: [{start, end, source_start, source_end}]."""
    data = json.loads(Path(path).expanduser().read_text(encoding='utf-8'))
    try:
        return [{key: float(segment[key]) for key in ('start', 'end', 'source_start', 'source_end')}
                for segment in data]
    except (TypeError, KeyError, ValueError) as error:
        raise ReviewError(f'{Path(path).name} is not an EDL of start/end/source_start/source_end segments.') from error


def source_time(version, seconds):
    for segment in version.get('edl') or ():
        if segment['start'] <= seconds < segment['end']:
            return round(segment['source_start'] + seconds - segment['start'], 3)
    return None


def output_time(version, source_seconds):
    for segment in version.get('edl') or ():
        if segment['source_start'] <= source_seconds < segment['source_end']:
            return segment['start'] + source_seconds - segment['source_start']
    return None


def caption_at(version, seconds):
    for segment in version.get('captions') or ():
        if segment['start'] <= seconds <= segment['end']:
            return segment['text']
    return ''


def clean_region(region):
    if region in (None, [], ''):
        return None
    try:
        x, y, w, h = (round(float(value), 4) for value in region)
    except (TypeError, ValueError) as error:
        raise ReviewError('A region is [x, y, width, height], each a fraction of the frame.') from error
    x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
    w, h = min(max(w, 0.0), 1.0 - x), min(max(h, 0.0), 1.0 - y)
    if w < 0.005 or h < 0.005:
        return None
    return [x, y, round(w, 4), round(h, 4)]


def clean_text(text):
    text = str(text or '').strip()
    if not text:
        raise ReviewError('Write something before sending.')
    if len(text) > MAX_TEXT:
        raise ReviewError(f'Keep a message under {MAX_TEXT} characters.')
    return text


class Review:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.file = self.path / 'review.json'
        self.name = self.path.name

    # ---- locating
    @classmethod
    def open(cls, reference, root=None):
        """Open a review by name under the root, or by a directory path."""
        reference = str(reference)
        candidate = Path(reference).expanduser()
        if ('/' in reference or reference.startswith('~')) and (candidate / 'review.json').is_file():
            return cls(candidate)
        if not NAME.match(reference):
            raise ReviewError(f'"{reference}" is not a review name; use lowercase letters, digits and hyphens.')
        review = cls(Path(root or default_root()) / reference)
        if not review.file.is_file():
            raise ReviewError(f'No review named "{reference}". Create it with `untangle-review new {reference}`.')
        return review

    @classmethod
    def create(cls, name, title=None, root=None):
        if not NAME.match(name):
            raise ReviewError(f'"{name}" is not a review name; use lowercase letters, digits and hyphens.')
        review = cls(Path(root or default_root()) / name)
        if review.file.exists():
            raise ReviewError(f'A review named "{name}" already exists.')
        review.path.mkdir(parents=True, exist_ok=True)
        with review._lock():
            if not review.file.exists():
                review._write({'schema': SCHEMA, 'title': (title or name.replace('-', ' ').capitalize()).strip()[:200],
                               'created': now(), 'updated': now(), 'versions': [], 'comments': []})
        return review

    @staticmethod
    def list(root=None):
        root = Path(root or default_root())
        reviews = []
        if root.is_dir():
            for path in sorted(root.iterdir()):
                if (path / 'review.json').is_file() and NAME.match(path.name):
                    try:
                        reviews.append(Review(path).summary())
                    except (OSError, ValueError):
                        continue
        return sorted(reviews, key=lambda item: item['updated'], reverse=True)

    # ---- persistence
    @contextmanager
    def _lock(self):
        self.path.mkdir(parents=True, exist_ok=True)
        with open(self.path / '.review.lock', 'a+') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _write(self, data):
        temporary = self.file.with_name(f'.review.{os.getpid()}.tmp')
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        os.replace(temporary, self.file)

    def load(self):
        data = json.loads(self.file.read_text(encoding='utf-8'))
        if data.get('schema') != SCHEMA:
            raise ReviewError(f'{self.file} uses review schema {data.get("schema")}; this tool reads {SCHEMA}.')
        return data

    def revision(self):
        stat = self.file.stat()
        return f'{stat.st_mtime_ns:x}-{stat.st_size:x}'

    def mutate(self, change):
        with self._lock():
            data = self.load()
            result = change(data)
            data['updated'] = now()
            self._write(data)
        return result

    # ---- queries
    def summary(self):
        data = self.load()
        counts = {status: 0 for status in STATUSES}
        for comment in data['comments']:
            counts[comment['status']] = counts.get(comment['status'], 0) + 1
        latest = data['versions'][-1] if data['versions'] else None
        return {'name': self.name, 'title': data['title'], 'updated': data['updated'], 'counts': counts,
                'versions': [{'id': v['id'], 'label': v['label']} for v in data['versions']],
                'latest': latest and {'id': latest['id'], 'label': latest['label'], 'width': latest['width'],
                                      'height': latest['height'], 'frames': latest['frames']}}

    def version(self, data, version_id):
        for version in data['versions']:
            if version['id'] == version_id:
                return version
        known = ', '.join(v['id'] for v in data['versions']) or 'none yet'
        raise ReviewError(f'No version "{version_id}" in {self.name}. Versions: {known}.')

    def comment(self, data, comment_id):
        for comment in data['comments']:
            if comment['id'] == comment_id:
                return comment
        raise ReviewError(f'No comment "{comment_id}" in {self.name}.')

    def locate(self, data, version_id, frame):
        version = self.version(data, version_id)
        frame = int(frame)
        if not 0 <= frame < version['frames']:
            raise ReviewError(f'{version_id} has frames 0 to {version["frames"] - 1}; {frame} is outside it.')
        seconds = frame / version['fps']
        return version, frame, {'time': round(seconds, 3), 'source_time': source_time(version, seconds),
                                'caption': caption_at(version, seconds)}

    def map_frame(self, data, from_version, frame, to_version):
        """Carry a frame to another version: through source time when both have an EDL, else by time."""
        source = self.version(data, from_version)
        target = self.version(data, to_version)
        seconds = int(frame) / source['fps']
        method = 'time'
        raw = source_time(source, seconds)
        if raw is not None and target.get('edl'):
            mapped = output_time(target, raw)
            if mapped is not None:
                seconds, method = mapped, 'source'
            else:
                method = 'time (cut from this version)'
        mapped_frame = min(max(round(seconds * target['fps']), 0), target['frames'] - 1)
        return {'frame': mapped_frame, 'method': method}

    # ---- changes
    def add_version(self, video, label=None, captions=None, edl=None, note='', origin=None):
        """Register a local video. ``origin`` records where it came from, such as a Drive link."""
        video = Path(video).expanduser().resolve()
        if not video.is_file():
            raise ReviewError(f'{video} does not exist.')
        details = probe(video)
        caption_segments = load_captions(captions) if captions else None
        edit_list = load_edl(edl) if edl else None

        def change(data):
            previous = data['versions'][-1] if data['versions'] else {}
            label_text = (label or f'v{len(data["versions"]) + 1}').strip()[:80]
            base = slug(label_text, 'version')
            taken = {v['id'] for v in data['versions']}
            identifier, counter = base, 2
            while identifier in taken:
                identifier, counter = f'{base}-{counter}', counter + 1
            version = dict(details, id=identifier, label=label_text, path=str(video), added=now(),
                           note=str(note or '')[:2000], origin=origin, identity=identity(video),
                           captions=caption_segments if captions else previous.get('captions'),
                           edl=edit_list if edl else previous.get('edl'))
            data['versions'].append(version)
            return version
        return self.mutate(change)

    def add_comment(self, version_id, frame, text, author, role='human', region=None):
        text = clean_text(text)
        region = clean_region(region)

        def change(data):
            version, index, where = self.locate(data, version_id, frame)
            taken = {c['id'] for c in data['comments']}
            identifier = secrets.token_hex(3)
            while identifier in taken:
                identifier = secrets.token_hex(3)
            comment = dict(where, id=identifier, number=len(data['comments']) + 1, version=version['id'],
                           frame=index, fps=version['fps'], region=region, status='open', addressed_in=None,
                           created=now(), updated=now(),
                           thread=[{'author': str(author)[:80], 'role': role, 'text': text, 'at': now()}])
            data['comments'].append(comment)
            return comment
        return self.mutate(change)

    def reply(self, comment_id, text, author, role='human'):
        text = clean_text(text)

        def change(data):
            comment = self.comment(data, comment_id)
            comment['thread'].append({'author': str(author)[:80], 'role': role, 'text': text, 'at': now()})
            comment['updated'] = now()
            return comment
        return self.mutate(change)

    def set_status(self, comment_id, status, author, role='human', version_id=None):
        if status not in STATUSES:
            raise ReviewError(f'Status must be one of {", ".join(STATUSES)}.')
        if status == 'resolved' and role == 'agent':
            # Like code review: the reviewer who raised a point decides when it is settled.
            raise ReviewError('Only the reviewer resolves a comment. Mark it addressed and name the version.')

        def change(data):
            comment = self.comment(data, comment_id)
            if version_id:
                self.version(data, version_id)
            comment['status'] = status
            comment['addressed_in'] = version_id if status == 'addressed' else (
                comment.get('addressed_in') if status == 'resolved' else None)
            comment['updated'] = now()
            note = {'open': 'reopened', 'addressed': 'marked addressed', 'resolved': 'resolved'}[status]
            if status == 'addressed' and version_id:
                note += f' in {version_id}'
            comment['thread'].append({'author': str(author)[:80], 'role': role, 'event': status,
                                      'text': note, 'at': now()})
            return comment
        return self.mutate(change)

    # ---- caches
    def source_dir(self):
        return self.path / 'sources'

    def prune(self, sources=True, frames=True):
        """Delete caches that can be rebuilt. Keeps review.json and any file outside the review folder."""
        freed = 0
        data = self.load()
        targets = []
        if frames:
            targets.append(self.path / 'frames')
        if sources:
            # Only downloads made by this tool, which can be fetched again from their origin.
            targets.extend(Path(v['path']).parent for v in data['versions']
                           if v.get('origin') and Path(v['path']).parent.parent == self.source_dir())
        for target in targets:
            if target.is_dir():
                freed += sum(f.stat().st_size for f in target.rglob('*') if f.is_file())
                shutil.rmtree(target, ignore_errors=True)
            elif target.is_file():
                freed += target.stat().st_size
                target.unlink()
        return freed

    def export_markdown(self, statuses=('open', 'addressed')):
        data = self.load()
        lines = [f'# {data["title"]} review', '']
        for comment in sorted(data['comments'], key=lambda c: (c['version'], c['frame'])):
            if comment['status'] not in statuses:
                continue
            version = self.version(data, comment['version'])
            stamp = timecode(comment['frame'], version['fps'])
            source = f', source {comment["source_time"]:.3f}s' if comment.get('source_time') is not None else ''
            lines.append(f'## #{comment["number"]} {version["label"]} {stamp} (frame {comment["frame"]}{source}) · {comment["status"]}')
            if comment.get('caption'):
                lines.append(f'> {comment["caption"]}')
            for message in comment['thread']:
                if message.get('event'):
                    lines.append(f'- _{message["author"]} {message["text"]}_')
                else:
                    lines.append(f'- **{message["author"]}:** {message["text"]}')
            lines.append('')
        return '\n'.join(lines)


def timecode(frame, fps):
    whole = int(frame // fps)
    rest = int(round(frame - whole * fps))
    return f'{whole // 60:02d}:{whole % 60:02d}:{rest:02d}'
