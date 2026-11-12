"""MCP server (stdio, JSON-RPC 2.0) so agents can read frame comments, see frames and answer them.

Nothing but JSON-RPC goes to stdout; diagnostics go to stderr.
"""
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

from .frames import Frames, crop, frame_path
from .server import ReviewServer, running_url
from .sources import add as add_source
from .store import Review, ReviewError, STATUSES, default_root, timecode

PROTOCOLS = ('2025-06-18', '2025-03-26', '2024-11-05')
INSTRUCTIONS = """Untangle Review: frame-accurate video review between a person and agents, like a code review for video.
A review holds versions of one video (local files, Google Drive links or URLs) and comments anchored to a version and frame,
optionally to a region [x, y, w, h] given as fractions of the frame. Typical loop:
1. add_version with the new render or its Drive link (creates the review with create=true).
2. open_review and show the returned URL to the person (in T3 Code, open it in the preview panel) so they can comment on frames.
3. list_comments to read unresolved feedback; get_frame with comment_id to see exactly what they pointed at.
4. Fix the edit, add_version for the new render, then mark_addressed each comment with that version and a short note.
The person verifies and resolves; agents never resolve. Frame numbers start at 0 on a constant frame-rate grid;
timecodes are mm:ss:ff."""


def text(value):
    return {'type': 'text', 'text': value if isinstance(value, str) else json.dumps(value, indent=1, ensure_ascii=False)}


def schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


REVIEW = {'type': 'string', 'description': 'Review name (lowercase-hyphenated) under the review root, or a review directory path.'}
VERSION = {'type': 'string', 'description': 'Version id, as listed by get_review. Defaults to the latest version.'}
FRAME = {'type': 'integer', 'minimum': 0, 'description': 'Frame index from 0.'}
REGION = {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4,
          'description': '[x, y, width, height] as fractions (0-1) of the frame.'}

TOOLS = [
    ('list_reviews', 'List reviews with their versions and open/addressed/resolved comment counts.', schema({})),
    ('get_review', 'Overview of one review: versions (fps, frames, size, origin, frame-cache state), comment counts, '
     'unresolved comments in brief, and the browser link if the review app is running.', schema({'review': REVIEW}, ['review'])),
    ('add_version', 'Add a render to a review. source is a local video path, a Google Drive file link '
     '(downloaded with the configured rclone Drive remote) or a direct video URL. Starts frame extraction.',
     schema({'review': REVIEW, 'source': {'type': 'string'}, 'label': {'type': 'string', 'description': 'Short name such as "v6 playful".'},
             'note': {'type': 'string', 'description': 'What changed in this version.'},
             'captions': {'type': 'string', 'description': 'Optional local caption file (SRT, timed segments or caption groups).'},
             'edl': {'type': 'string', 'description': 'Optional local EDL mapping output time to source time.'},
             'create': {'type': 'boolean', 'description': 'Create the review if it does not exist.'},
             'title': {'type': 'string', 'description': 'Title when creating the review.'}}, ['review', 'source'])),
    ('list_comments', 'Read comments with their full threads, frame, timecode, source time, caption and region.',
     schema({'review': REVIEW, 'status': {'type': 'string', 'enum': ['unresolved', 'all', *STATUSES],
                                          'description': 'Default unresolved (open and addressed).'},
             'version': VERSION}, ['review'])),
    ('get_frame', 'Return the exact frame as an image. With comment_id, returns that comment\'s frame plus a crop of '
     'its region. compare_version adds the same moment from another version (mapped through the EDL when available).',
     schema({'review': REVIEW, 'comment_id': {'type': 'string'}, 'version': VERSION, 'frame': FRAME,
             'compare_version': {'type': 'string'}}, ['review'])),
    ('add_comment', 'Leave a comment on a frame as the agent, for example to ask the person to check a moment.',
     schema({'review': REVIEW, 'version': VERSION, 'frame': FRAME, 'text': {'type': 'string'}, 'region': REGION},
            ['review', 'frame', 'text'])),
    ('reply', 'Reply in a comment thread.', schema({'review': REVIEW, 'comment_id': {'type': 'string'},
                                                   'text': {'type': 'string'}}, ['review', 'comment_id', 'text'])),
    ('mark_addressed', 'Mark a comment addressed in a version you added, with a note on what changed. '
     'The person then checks that frame in the new version and resolves or reopens it.',
     schema({'review': REVIEW, 'comment_id': {'type': 'string'}, 'version': VERSION,
             'note': {'type': 'string'}}, ['review', 'comment_id'])),
    ('open_review', 'Start the local review app if needed and return a link to a review, optionally at a version, '
     'frame or comment. Show the link to the person; in T3 Code open it in the preview panel.',
     schema({'review': REVIEW, 'version': VERSION, 'frame': FRAME, 'comment_id': {'type': 'string'}}, ['review'])),
    ('export_review', 'Unresolved comments as Markdown, for handoffs and edit notes.', schema({'review': REVIEW}, ['review'])),
]


class Session:
    def __init__(self, root=None):
        self.root = Path(root or default_root()).expanduser()
        self.agent = os.environ.get('UNTANGLE_REVIEW_AGENT_NAME') or 'Agent'
        self.server = None

    def log(self, message):
        print(f'untangle-review: {message}', file=sys.stderr, flush=True)

    def review(self, args):
        return Review.open(args['review'], self.root)

    def latest(self, data, version_id=None):
        if version_id:
            return version_id
        if not data['versions']:
            raise ReviewError('This review has no versions yet; add one with add_version.')
        return data['versions'][-1]['id']

    def url(self):
        existing = running_url(self.root)
        if existing:
            return existing
        if not self.server:
            self.server = ReviewServer(self.root, int(os.environ.get('UNTANGLE_REVIEW_PORT', '8740')))
            self.server.announce()
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
            self.log(f'review app at {self.server.url}')
        return self.server.url

    def brief(self, comment, versions):
        version = versions.get(comment['version'], {})
        first = comment['thread'][0]
        return {'id': comment['id'], 'number': comment['number'], 'status': comment['status'],
                'version': comment['version'], 'frame': comment['frame'],
                'timecode': timecode(comment['frame'], version.get('fps', comment['fps'])),
                'region': comment['region'], 'by': first['author'], 'text': first['text'],
                'replies': len([m for m in comment['thread'] if not m.get('event')]) - 1,
                'addressed_in': comment.get('addressed_in')}

    @staticmethod
    def frame_image(review, data, version_id, frame):
        return frame_path(review, version_id, frame)

    @staticmethod
    def image(path):
        return {'type': 'image', 'data': base64.b64encode(Path(path).read_bytes()).decode(), 'mimeType': 'image/jpeg'}

    # ---- tools
    def list_reviews(self, args):
        return [text({'root': str(self.root), 'reviews': Review.list(self.root)})]

    def get_review(self, args):
        review = self.review(args)
        data = review.load()
        versions = {v['id']: v for v in data['versions']}
        overview = {
            'name': review.name, 'title': data['title'], 'link': running_url(self.root) and f'{running_url(self.root)}/r/{review.name}',
            'versions': [{key: v.get(key) for key in ('id', 'label', 'fps', 'frames', 'duration', 'width', 'height',
                                                     'note', 'origin', 'added')} | {'frames_cache': Frames(review, v).status()['state'],
                                                                                     'has_captions': bool(v.get('captions')),
                                                                                     'has_edl': bool(v.get('edl'))}
                         for v in data['versions']],
            'counts': review.summary()['counts'],
            'unresolved': [self.brief(c, versions) for c in data['comments'] if c['status'] != 'resolved'],
        }
        return [text(overview)]

    def add_version(self, args):
        try:
            review = self.review(args)
        except ReviewError:
            if not args.get('create'):
                raise
            review = Review.create(args['review'], args.get('title'), self.root)
        version = add_source(review, args['source'], label=args.get('label'), captions=args.get('captions'),
                             edl=args.get('edl'), note=args.get('note', ''), progress=self.log)
        Frames(review, version).start(on_error=lambda error: self.log(str(error)))
        shown = {key: version.get(key) for key in ('id', 'label', 'fps', 'frames', 'duration', 'width', 'height', 'origin')}
        if version.get('variable_rate'):
            shown['warning'] = 'Variable frame rate source: frames follow a constant-rate grid and may drift from playback.'
        return [text({'added': shown, 'review': review.name})]

    def list_comments(self, args):
        review = self.review(args)
        data = review.load()
        wanted = args.get('status', 'unresolved')
        versions = {v['id']: v for v in data['versions']}
        comments = []
        for comment in data['comments']:
            if wanted == 'unresolved' and comment['status'] == 'resolved':
                continue
            if wanted not in ('unresolved', 'all') and comment['status'] != wanted:
                continue
            if args.get('version') and comment['version'] != args['version']:
                continue
            version = versions[comment['version']]
            item = dict(comment, timecode=timecode(comment['frame'], version['fps']))
            path = Frames(review, version).file(comment['frame'])
            item['frame_file'] = str(path) if path else None
            comments.append(item)
        return [text({'review': review.name, 'comments': comments})]

    def get_frame(self, args):
        review = self.review(args)
        data = review.load()
        region = None
        if args.get('comment_id'):
            comment = review.comment(data, args['comment_id'])
            version_id, frame, region = comment['version'], comment['frame'], comment['region']
        else:
            version_id = self.latest(data, args.get('version'))
            if args.get('frame') is None:
                raise ReviewError('Give a frame or a comment_id.')
            frame = int(args['frame'])
        version, frame, where = review.locate(data, version_id, frame)
        path = self.frame_image(review, data, version_id, frame)
        content = [text(dict(where, version=version_id, frame=frame, timecode=timecode(frame, version['fps']),
                             region=region, size=[version['width'], version['height']])), self.image(path)]
        if region:
            with tempfile.TemporaryDirectory() as scratch:
                content += [text('Region crop:'), self.image(crop(path, region, Path(scratch) / 'crop.jpg'))]
        if args.get('compare_version'):
            mapped = review.map_frame(data, version_id, frame, args['compare_version'])
            other = self.frame_image(review, data, args['compare_version'], mapped['frame'])
            content += [text({'compare_version': args['compare_version'], **mapped}), self.image(other)]
        return content

    def add_comment(self, args):
        review = self.review(args)
        data = review.load()
        comment = review.add_comment(self.latest(data, args.get('version')), args['frame'], args['text'],
                                     self.agent, role='agent', region=args.get('region'))
        return [text(comment)]

    def reply(self, args):
        return [text(self.review(args).reply(args['comment_id'], args['text'], self.agent, role='agent'))]

    def mark_addressed(self, args):
        review = self.review(args)
        version = self.latest(review.load(), args.get('version'))
        if args.get('note'):
            review.reply(args['comment_id'], args['note'], self.agent, role='agent')
        return [text(review.set_status(args['comment_id'], 'addressed', self.agent, role='agent', version_id=version))]

    def open_review(self, args):
        review = self.review(args)
        data = review.load()
        query = []
        if args.get('comment_id'):
            review.comment(data, args['comment_id'])
            query.append(f'c={args["comment_id"]}')
        if args.get('version'):
            review.version(data, args['version'])
            query.append(f'v={args["version"]}')
        if args.get('frame') is not None:
            query.append(f'f={int(args["frame"])}')
        link = f'{self.url()}/r/{review.name}' + ('?' + '&'.join(query) if query else '')
        return [text({'url': link, 'note': 'Open this link for the person. In T3 Code, use the preview panel. '
                      'Comments they leave appear in list_comments immediately.'})]

    def export_review(self, args):
        return [text(self.review(args).export_markdown())]

    # ---- protocol
    def handle(self, message):
        method, identifier = message.get('method'), message.get('id')
        if identifier is None:
            return None  # Notifications, including notifications/initialized, get no response.
        try:
            if method == 'initialize':
                agent = (message.get('params', {}).get('clientInfo') or {}).get('name')
                if agent and 'UNTANGLE_REVIEW_AGENT_NAME' not in os.environ:
                    self.agent = agent.replace('-', ' ').title()[:80]
                requested = message.get('params', {}).get('protocolVersion')
                result = {'protocolVersion': requested if requested in PROTOCOLS else PROTOCOLS[0],
                          'capabilities': {'tools': {'listChanged': False}},
                          'serverInfo': {'name': 'untangle-review', 'version': '1.0.0'},
                          'instructions': INSTRUCTIONS}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': [{'name': name, 'description': description, 'inputSchema': input_schema}
                                    for name, description, input_schema in TOOLS]}
            elif method == 'tools/call':
                params = message.get('params') or {}
                name = params.get('name')
                if name not in {tool[0] for tool in TOOLS}:
                    return error(identifier, -32602, f'Unknown tool {name}.')
                try:
                    result = {'content': getattr(self, name)(params.get('arguments') or {})}
                except (ReviewError, KeyError, ValueError, TypeError, OSError) as failure:
                    detail = f'Missing argument {failure}.' if isinstance(failure, KeyError) else str(failure)
                    result = {'content': [text(detail)], 'isError': True}
            else:
                return error(identifier, -32601, f'Method {method} not found.')
        except Exception as failure:  # A broken request must not end the session.
            self.log(f'{method} failed: {failure!r}')
            return error(identifier, -32603, 'Internal error.')
        return {'jsonrpc': '2.0', 'id': identifier, 'result': result}


def error(identifier, code, message):
    return {'jsonrpc': '2.0', 'id': identifier, 'error': {'code': code, 'message': message}}


def run(root=None, stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    session = Session(root)
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response = error(None, -32700, 'Parse error.')
        else:
            batch = message if isinstance(message, list) else [message]
            replies = [reply for reply in (session.handle(item) for item in batch if isinstance(item, dict)) if reply]
            response = replies if isinstance(message, list) else (replies[0] if replies else None)
        if response:
            stdout.write(json.dumps(response, ensure_ascii=False) + '\n')
            stdout.flush()
    if session.server:
        session.server.withdraw()
        session.server.shutdown()
        session.server.server_close()
