"""Untangle Review: store, frame accuracy, sources, local server and MCP. Synthetic clips only; no app launch."""
import http.client
import io
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from untangle.review import frames as frames_module
from untangle.review import mcp, sources
from untangle.review.frames import Frames
from untangle.review.server import ReviewServer
from untangle.review.store import Review, ReviewError, clean_region, load_captions

ROOT = Path(__file__).resolve().parents[1]
HAS_FFMPEG = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))


def make_clip(path, seconds=2, rate=10, size='64x48', gray_ramp=False, extra=''):
    """Each frame N of a gray-ramp clip has luma 16 + 6N, so a frame's identity is visible in its pixels."""
    source = f'color=black:size={size}:rate={rate}:duration={seconds}'
    filters = "geq=lum='16+6*N':cb=128:cr=128" if gray_ramp else 'null'
    if extra:
        filters += ',' + extra
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', source, '-vf', filters,
                    '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-qp', '0', str(path)], check=True)
    return path


def mean_luma(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'rawvideo', '-pix_fmt', 'gray', '-'],
                         capture_output=True, check=True).stdout
    return sum(raw) / len(raw)


def append_comments(root, count):
    review = Review.open('race', root)
    for index in range(count):
        review.add_comment('v1', index % 10, f'note {os.getpid()} {index}', 'tester')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_names_and_listing(self):
        review = Review.create('launch-teaser', 'Launch teaser', self.root)
        self.assertEqual(Review.open('launch-teaser', self.root).path, review.path)
        self.assertEqual([item['name'] for item in Review.list(self.root)], ['launch-teaser'])
        for bad in ('../escape', 'Upper', '', 'a/b'):
            with self.assertRaises(ReviewError):
                Review.create(bad, None, self.root)
        with self.assertRaises(ReviewError):
            Review.create('launch-teaser', None, self.root)

    def test_regions_are_clamped_and_tiny_regions_dropped(self):
        self.assertEqual(clean_region([0.9, -0.2, 0.5, 0.5]), [0.9, 0.0, 0.1, 0.5])
        self.assertIsNone(clean_region([0.5, 0.5, 0.001, 0.2]))
        self.assertIsNone(clean_region(None))
        with self.assertRaises(ReviewError):
            clean_region(['a', 1, 2, 3])

    def test_caption_formats(self):
        srt = self.root / 'c.srt'
        srt.write_text('1\n00:00:01,000 --> 00:00:02,500\nHello\nthere\n\n2\n00:00:03,000 --> 00:00:04,000\nBye\n')
        self.assertEqual(load_captions(srt), [{'start': 1.0, 'end': 2.5, 'text': 'Hello there'},
                                              {'start': 3.0, 'end': 4.0, 'text': 'Bye'}])
        groups = self.root / 'g.json'
        groups.write_text(json.dumps([[{'start': 0, 'end': 0.4, 'word': 'You'}, {'start': 0.4, 'end': 0.9, 'word': 'have'}]]))
        self.assertEqual(load_captions(groups), [{'start': 0.0, 'end': 0.9, 'text': 'You have'}])


@unittest.skipUnless(HAS_FFMPEG, 'FFmpeg is required for review clips')
class ClipTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.clip = make_clip(self.root / 'ramp.mp4', gray_ramp=True)
        self.review = Review.create('demo', None, self.root)
        self.version = self.review.add_version(self.clip, label='v1')

    def test_probe_and_comment_anchor(self):
        self.assertEqual((self.version['width'], self.version['height'], self.version['fps']), (64, 48, 10.0))
        self.assertEqual(self.version['frames'], 20)
        comment = self.review.add_comment('v1', 7, '  Fix the fade  ', 'Elhaam', region=[0.1, 0.1, 0.5, 0.5])
        self.assertEqual((comment['frame'], comment['time'], comment['status'], comment['number']), (7, 0.7, 'open', 1))
        self.assertEqual(comment['thread'][0]['text'], 'Fix the fade')
        for frame in (-1, 20):
            with self.assertRaises(ReviewError):
                self.review.add_comment('v1', frame, 'x', 'Elhaam')
        with self.assertRaises(ReviewError):
            self.review.add_comment('v1', 3, '   ', 'Elhaam')
        with self.assertRaises(ReviewError):
            self.review.add_comment('nope', 3, 'x', 'Elhaam')

    def test_cached_frames_are_the_anchored_frames(self):
        frames = Frames(self.review, self.version)
        self.assertEqual(frames.extract(), 20)
        self.assertTrue(frames.ready())
        for index in (0, 1, 7, 19):
            # JPEG stores full-range luma: TV-range 16 + 6N decodes as 6N * 255 / 219.
            self.assertAlmostEqual(mean_luma(frames.file(index)), 6 * index * 255 / 219, delta=3, msg=f'frame {index}')
        self.assertIsNone(frames.file(20))
        self.assertEqual(frames.extract(), 20)  # Already complete: no second extraction.

    def test_status_rules_follow_code_review(self):
        comment = self.review.add_comment('v1', 2, 'Too dark', 'Elhaam')
        v2 = self.review.add_version(make_clip(self.root / 'b.mp4'), label='v2')
        with self.assertRaises(ReviewError):
            self.review.set_status(comment['id'], 'resolved', 'Agent', role='agent')
        addressed = self.review.set_status(comment['id'], 'addressed', 'Agent', role='agent', version_id=v2['id'])
        self.assertEqual((addressed['status'], addressed['addressed_in']), ('addressed', 'v2'))
        self.assertEqual(addressed['thread'][-1]['event'], 'addressed')
        resolved = self.review.set_status(comment['id'], 'resolved', 'Elhaam')
        self.assertEqual((resolved['status'], resolved['addressed_in']), ('resolved', 'v2'))
        self.assertIn('Too dark', self.review.export_markdown(statuses=('resolved',)))

    def test_cli_show_gives_agents_the_frame_and_history(self):
        from contextlib import redirect_stdout
        from untangle.review import cli
        comment = self.review.add_comment('v1', 7, 'Fix the fade', 'Elhaam', region=[0.25, 0.25, 0.5, 0.5])
        self.assertEqual(cli.main(['--root', str(self.root), 'reply', 'demo', '#1', 'On it', '--agent']), 0)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(['--root', str(self.root), 'show', 'demo', '#1']), 0)
        text = out.getvalue()
        self.assertIn(f'#1 [{comment["id"]}] v1 00:00:07 (frame 7', text)
        self.assertIn('Agent: On it', text)
        frame = Path(text.split('Frame: ')[1].splitlines()[0])
        self.assertAlmostEqual(mean_luma(frame), 6 * 7 * 255 / 219, delta=3)
        self.assertTrue(Path(text.split(': ')[-1].strip()).is_file())  # Region crop
        self.assertEqual(cli.main(['--root', str(self.root), 'show', 'demo', '#9']), 1)

    def test_versions_map_through_the_edit_list(self):
        edl = self.root / 'edl.json'
        edl.write_text(json.dumps([{'start': 0, 'end': 2, 'source_start': 10, 'source_end': 12}]))
        trimmed = self.root / 'edl2.json'
        trimmed.write_text(json.dumps([{'start': 0, 'end': 1.5, 'source_start': 10.5, 'source_end': 12}]))
        review = Review.create('mapped', None, self.root)
        review.add_version(self.clip, label='a', edl=edl)
        review.add_version(self.clip, label='b', edl=trimmed)
        data = review.load()
        self.assertEqual(review.map_frame(data, 'a', 10, 'b'), {'frame': 5, 'method': 'source'})
        self.assertEqual(review.map_frame(data, 'a', 2, 'b')['method'], 'time (cut from this version)')
        self.assertEqual(review.locate(data, 'a', 10)[2]['source_time'], 11.0)

    def test_concurrent_writers_lose_nothing(self):
        race = Review.create('race', None, self.root)
        race.add_version(self.clip, label='v1')
        workers = [multiprocessing.Process(target=append_comments, args=(self.root, 15)) for _ in range(3)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(60)
        comments = race.load()['comments']
        self.assertEqual(len(comments), 45)
        self.assertEqual(len({c['id'] for c in comments}), 45)

    def test_prune_removes_only_rebuildable_caches(self):
        Frames(self.review, self.version).extract()
        download = self.review.source_dir() / 'abc123'
        download.mkdir(parents=True)
        shutil.copy(self.clip, download / 'clip.mp4')
        self.review.add_version(download / 'clip.mp4', label='drive', origin={'kind': 'drive', 'id': 'abc123', 'url': 'x'})
        self.assertGreater(self.review.prune(), 0)
        self.assertFalse((self.review.path / 'frames').exists())
        self.assertFalse(download.exists())
        self.assertTrue(self.clip.exists(), 'local originals are never deleted')
        self.assertTrue(self.review.file.exists())


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.review = Review.create('drive', None, self.root)

    def test_drive_links(self):
        cases = {
            'https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view?usp=sharing': '1AbCdEfGhIjKlMnOpQrStUvWxYz012345',
            'https://drive.google.com/open?id=1AbCdEfGhIjKlMnOpQrStUvWxYz012345': '1AbCdEfGhIjKlMnOpQrStUvWxYz012345',
            'https://drive.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOpQrStUvWxYz012345': '1AbCdEfGhIjKlMnOpQrStUvWxYz012345',
        }
        for url, expected in cases.items():
            self.assertEqual(sources.drive_id(url), expected)
        self.assertIsNone(sources.drive_id('https://evil.example/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345'))
        self.assertIsNone(sources.drive_id('/home/me/video.mp4'))

    def fake_rclone(self, script):
        tools = self.root / 'bin'
        tools.mkdir(exist_ok=True)
        rclone = tools / 'rclone'
        rclone.write_text('#!/bin/bash\n' + script)
        rclone.chmod(0o755)
        calls = self.root / 'calls'
        return mock.patch.dict(os.environ, {'PATH': f'{tools}:{os.environ["PATH"]}', 'RCLONE_CALLS': str(calls),
                                            'UNTANGLE_REVIEW_DRIVE_REMOTE': 'gdrive'}), calls

    def test_drive_download_uses_rclone_by_id_and_is_cached(self):
        patch, calls = self.fake_rclone('echo "$@" >> "$RCLONE_CALLS"\nprintf video > "$5/Reel v2.mp4"\n')
        url = 'https://drive.google.com/file/d/1ZyXwVuTsRqPoNmLkJiHgFeDcBa98765/view'
        with patch:
            path, origin = sources.fetch(self.review, url)
            again, _ = sources.fetch(self.review, url)
        self.assertEqual(path.name, 'Reel v2.mp4')
        self.assertEqual(path, again)
        self.assertEqual(origin, {'kind': 'drive', 'id': '1ZyXwVuTsRqPoNmLkJiHgFeDcBa98765', 'url': url})
        self.assertEqual(calls.read_text().split()[:4], ['backend', 'copyid', 'gdrive:', '1ZyXwVuTsRqPoNmLkJiHgFeDcBa98765'])
        self.assertEqual(len(calls.read_text().splitlines()), 1)

    def test_drive_failure_explains_what_to_do(self):
        patch, _ = self.fake_rclone('echo "Failed to copy: file not found" >&2\nexit 1\n')
        with patch, mock.patch.object(sources, '_download', side_effect=ReviewError('the file may be private')):
            with self.assertRaises(ReviewError) as caught:
                sources.fetch(self.review, 'https://drive.google.com/file/d/1ZyXwVuTsRqPoNmLkJiHgFeDcBa98765/view')
        message = str(caught.exception)
        self.assertIn('file not found', message)
        self.assertIn('--origin', message)
        self.assertFalse(any(self.review.source_dir().iterdir()), 'failed downloads leave nothing behind')


@unittest.skipUnless(HAS_FFMPEG, 'FFmpeg is required for review clips')
class ServerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        review = Review.create('teaser', 'Teaser', self.root)
        self.clip = make_clip(self.root / 'a.mp4', gray_ramp=True)
        version = review.add_version(self.clip, label='v1')
        Frames(review, version).extract()
        self.server = ReviewServer(self.root, port=0, reviewer='Elhaam')
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.port, timeout=10)
        payload = json.dumps(body).encode() if body is not None else None
        merged = {'Content-Type': 'application/json'} if payload is not None else {}
        merged.update(headers or {})
        connection.request(method, path, payload, merged)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, response.headers, data

    def test_review_data_hides_local_paths(self):
        status, _, data = self.request('GET', '/api/reviews/teaser')
        self.assertEqual(status, 200)
        body = json.loads(data)
        self.assertNotIn('path', body['versions'][0])
        self.assertNotIn(str(self.root), json.dumps(body['versions']))
        self.assertEqual(body['frames']['v1']['state'], 'ready')

    def test_frames_media_and_comments(self):
        status, headers, data = self.request('GET', '/api/reviews/teaser/frames/v1/7.jpg')
        self.assertEqual((status, headers['Content-Type']), (200, 'image/jpeg'))
        self.assertEqual(self.request('GET', '/api/reviews/teaser/frames/v1/20.jpg')[0], 404)
        status, headers, data = self.request('GET', '/api/reviews/teaser/media/v1', headers={'Range': 'bytes=0-9'})
        self.assertEqual((status, len(data), headers['Content-Range'].split('/')[1]), (206, 10, str(self.clip.stat().st_size)))
        status, _, data = self.request('POST', '/api/reviews/teaser/comments', {'version': 'v1', 'frame': 3, 'text': 'Warmer'})
        self.assertEqual(status, 201)
        comment = json.loads(data)
        self.assertEqual(comment['thread'][0]['author'], 'Elhaam')
        status, _, data = self.request('POST', f'/api/reviews/teaser/comments/{comment["id"]}/status', {'status': 'resolved'})
        self.assertEqual(json.loads(data)['status'], 'resolved')
        self.assertEqual(self.request('POST', '/api/reviews/teaser/comments', {'version': 'v1', 'frame': 3, 'text': ''})[0], 400)

    def test_guards(self):
        self.assertEqual(self.request('GET', '/api/reviews', headers={'Host': 'attacker.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/reviews/teaser/comments', {'version': 'v1', 'frame': 1, 'text': 'x'},
                                      {'Origin': 'https://attacker.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/reviews/teaser/comments', None,
                                      {'Content-Type': 'text/plain', 'Content-Length': '2'})[0], 415)
        for path in ('/api/reviews/..%2f..%2fetc/frames/v1/1.jpg', '/api/reviews/teaser/frames/v1/..%2f..%2freview.json',
                     '/static/..%2fstore.py', '/api/reviews/teaser/media/..%2f..'):
            self.assertIn(self.request('GET', path)[0], (403, 404), path)

    def test_pages_and_assets(self):
        for path in ('/', '/r/teaser', '/static/review.js', '/static/review.css', '/static/mark.svg', '/static/Inter-Regular.ttf'):
            self.assertEqual(self.request('GET', path)[0], 200, path)


@unittest.skipUnless(HAS_FFMPEG, 'FFmpeg is required for review clips')
class McpTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.clip = make_clip(self.root / 'a.mp4', gray_ramp=True)
        review = Review.create('teaser', None, self.root)
        review.add_version(self.clip, label='v1')
        self.comment = review.add_comment('v1', 4, 'Logo too small', 'Elhaam', region=[0.25, 0.25, 0.5, 0.5])

    def session(self, *messages):
        stdin = io.StringIO(''.join(json.dumps(m) + '\n' for m in messages))
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {'UNTANGLE_REVIEW_PORT': '0'}):
            mcp.run(self.root, stdin, stdout)
        return [json.loads(line) for line in stdout.getvalue().splitlines()]

    def call(self, identifier, name, arguments):
        return {'jsonrpc': '2.0', 'id': identifier, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}

    def test_protocol_handshake(self):
        replies = self.session(
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26', 'clientInfo': {'name': 'claude-code'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'nope'})
        self.assertEqual([r['id'] for r in replies], [1, 2, 3])
        self.assertEqual(replies[0]['result']['protocolVersion'], '2025-03-26')
        names = {tool['name'] for tool in replies[1]['result']['tools']}
        self.assertTrue({'list_comments', 'get_frame', 'add_version', 'mark_addressed', 'open_review'} <= names)
        self.assertEqual(replies[2]['error']['code'], -32601)

    def test_agent_review_loop(self):
        replies = self.session(
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'claude-code'}}},
            self.call(2, 'list_comments', {'review': 'teaser'}),
            self.call(3, 'get_frame', {'review': 'teaser', 'comment_id': self.comment['id']}),
            self.call(4, 'add_version', {'review': 'teaser', 'source': str(self.clip), 'label': 'v2'}),
            self.call(5, 'mark_addressed', {'review': 'teaser', 'comment_id': self.comment['id'], 'version': 'v2', 'note': 'Bigger logo'}),
            self.call(6, 'get_frame', {'review': 'teaser', 'frame': 999}),
            self.call(7, 'open_review', {'review': 'teaser', 'comment_id': self.comment['id']}))
        comments = json.loads(replies[1]['result']['content'][0]['text'])['comments']
        self.assertEqual((comments[0]['frame'], comments[0]['timecode']), (4, '00:00:04'))
        parts = replies[2]['result']['content']
        self.assertEqual([p['type'] for p in parts], ['text', 'image', 'text', 'image'])
        self.assertEqual(parts[1]['mimeType'], 'image/jpeg')
        self.assertNotIn('isError', replies[3]['result'])
        addressed = json.loads(replies[4]['result']['content'][0]['text'])
        self.assertEqual((addressed['status'], addressed['addressed_in']), ('addressed', 'v2'))
        self.assertEqual([m['author'] for m in addressed['thread'][1:]], ['Claude Code', 'Claude Code'])
        self.assertTrue(replies[5]['result']['isError'])
        self.assertIn('/r/teaser?c=', json.loads(replies[6]['result']['content'][0]['text'])['url'])


class PackagingTests(unittest.TestCase):
    def test_review_never_imports_qt(self):
        code = ('import sys, untangle.review.cli, untangle.review.server, untangle.review.mcp, untangle.review.sources;'
                "assert not [m for m in sys.modules if m.startswith('PySide6')], 'Qt imported'")
        result = subprocess.run([sys.executable, '-c', code], env=dict(os.environ, PYTHONPATH=str(ROOT / 'src')),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_symlinked_launcher_runs_outside_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            link = Path(directory) / 'untangle-review'
            link.symlink_to(ROOT / 'bin' / 'untangle-review')
            result = subprocess.run([str(link), '--root', directory, 'list'], cwd=directory, capture_output=True,
                                    text=True, timeout=30, env=dict(os.environ, PYTHONPATH=''))
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
