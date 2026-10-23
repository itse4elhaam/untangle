import json
import unittest

from untangle.loom import (
    ACCOUNT_ARGS, parse_account_status, parse_upload_progress, parse_upload_result,
    parse_video_info, rename_title_args, supports_option, upload_args,
    valid_share_url, video_id, video_info_args,
)


class LoomParserTests(unittest.TestCase):
    def test_strict_share_urls(self):
        self.assertEqual(valid_share_url('https://loom.com/share/abc123?sid=tracking#t=1'),
                         'https://www.loom.com/share/abc123')
        for value in ('http://loom.com/share/abc123', 'https://loom.com.evil/share/abc123',
                      'https://user@loom.com/share/abc123', 'https://loom.com:443/share/abc123',
                      'https://loom.com/share/abc123/extra', 'https://loom.com/embed/abc123',
                      'https://loom.com/share/abc%2f123', 'https://loom.com/share/abc123\n',
                      'https://[broken/share/abc123', 'file:///video.mp4', None):
            with self.subTest(value=value):
                self.assertEqual(valid_share_url(value), '')

    def test_video_ids_and_read_commands(self):
        ari = 'ari:cloud:loom:cloud123:video/activation/workspace123/abc123'
        self.assertEqual(video_id(ari), 'abc123')
        self.assertEqual(video_id('https://www.loom.com/share/abc123'), 'abc123')
        self.assertEqual(video_info_args(ari)[:4], ['loom', 'video', 'get', ari])
        self.assertIn('--output-summary', ACCOUNT_ARGS)
        for invalid in ('--delete', 'https://evil.com/share/abc', 'ari:cloud:identity::user/abc'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                video_info_args(invalid)

    def test_account_contract_never_claims_loom_entitlement_or_leaks_tokens(self):
        output = json.dumps({'apiVersion': 'v2', 'data': {'accountId': 'account1',
                            'name': 'Synthetic user', 'email': 'user@example.test', 'token': 'secret'}})
        row = parse_account_status(output)
        self.assertEqual(row['status'], 'connected')
        self.assertEqual(row['name'], 'Synthetic user')
        self.assertIsNone(row['auto_titles_entitled'])
        self.assertIsNone(row['auto_titles_enabled'])
        self.assertNotIn('secret', str(row))
        self.assertEqual(parse_account_status('{}')['status'], 'unknown')
        self.assertEqual(parse_account_status(output, 1)['status'], 'unknown')
        self.assertEqual(parse_account_status('', 77)['status'], 'disconnected')
        self.assertEqual(parse_account_status('{"error":{"code":"AUTH_INVALID"}}', 1)['status'], 'disconnected')

    def test_installed_upload_and_get_shapes_use_name_as_title(self):
        video = {'id': 'abc123', 'name': 'A Loom title',
                 'url': 'https://www.loom.com/share/abc123', 'isComplete': True}
        upload = parse_upload_result({'data': {'video': video, 'transfer': {'bytes': 100}}})
        self.assertEqual(upload['status'], 'uploaded')
        self.assertEqual(upload['title'], 'A Loom title')
        self.assertEqual(upload['remote_id'], 'abc123')
        self.assertEqual(parse_video_info({'data': video})['status'], 'available')
        self.assertIs(parse_video_info({'data': video})['is_complete'], True)
        video['isComplete'] = False
        self.assertEqual(parse_upload_result({'data': {'video': video}})['status'], 'processing')
        self.assertIs(parse_video_info({'data': video})['is_complete'], False)
        del video['isComplete']
        self.assertIsNone(parse_video_info({'data': video})['is_complete'])
        video['isComplete'] = 'true'
        self.assertIsNone(parse_video_info({'data': video})['is_complete'])

    def test_jsonl_and_malformed_input(self):
        video = {'data': {'video': {'id': 'abc123', 'name': 'Title',
                 'url': 'https://www.loom.com/share/abc123'}}}
        output = 'diagnostic\n{broken\n' + json.dumps(video) + '\n'
        self.assertEqual(parse_upload_result(output.encode())['status'], 'uploaded')
        for bad in ('', '{bad', '[]', 'null', '{"data":null}', '{"data":{"video":[]}}'):
            with self.subTest(bad=bad):
                self.assertEqual(parse_video_info(bad)['status'], 'unknown')
                self.assertEqual(parse_upload_result(bad)['status'], 'uncertain')

    def test_failed_command_never_treats_diagnostic_urls_as_publication(self):
        error = {'ok': False, 'error': {'code': 'TWG_COMMAND_FAILED',
                 'message': 'Try https://www.loom.com/share/abc123',
                 'url': 'https://www.loom.com/share/abc123'}}
        self.assertEqual(parse_upload_result(error, 1)['url'], '')
        self.assertEqual(parse_upload_result(error, 1)['status'], 'uncertain')
        published = {'ok': False, 'data': {'video': {'id': 'abc123',
                     'url': 'https://www.loom.com/share/abc123'}}, 'error': {'code': 'VISIBILITY_FAILED'}}
        row = parse_upload_result(published, 3)
        self.assertEqual(row['url'], 'https://www.loom.com/share/abc123')
        self.assertEqual(row['status'], 'uncertain')

    def test_remote_unknown_is_never_inferred_as_deleted(self):
        for payload, code in (({'error': {'code': 'NOT_FOUND'}}, 1),
                              ({'error': {'status': 404}}, 1),
                              ({'error': {'status': 403}}, 1),
                              ({'data': None}, 0),
                              ({'data': {'id': 'abc123', 'isArchived': True}}, 0),
                              ({'data': {'id': 'abc123', 'status': 'PRIVATE'}}, 0)):
            with self.subTest(payload=payload):
                self.assertEqual(parse_video_info(payload, code)['status'], 'unknown')
        # Explicit future response only. The inspected CLI does not emit this.
        deleted = {'data': {'id': 'abc123', 'status': 'DELETED',
                           'url': 'https://www.loom.com/share/abc123'}}
        self.assertEqual(parse_video_info(deleted)['status'], 'deleted')
        self.assertEqual(parse_video_info(deleted)['url'], '')
        self.assertEqual(parse_video_info(deleted, 1)['status'], 'unknown')

    def test_upload_command_preserves_loom_title_choice(self):
        help_text = ('Usage: twg loom video upload [options] <file>\n'
                     '  --title <title>  Set title\n  --visibility <visibility>  Sharing\n')
        args = upload_args('/synthetic.mp4', help_text, title='Filename title')
        self.assertNotIn('--title', args)
        self.assertIn('--visibility', args)
        args = upload_args('/synthetic.mp4', help_text, title='Manual', prefer_loom_titles=False)
        self.assertEqual(args[-2:], ['--title', 'Manual'])
        old_help = 'Usage: twg loom video upload [options] <file>\n'
        self.assertNotIn('--visibility', upload_args('/synthetic.mp4', old_help))
        self.assertFalse(supports_option('  --title-prefix <value>', '--title'))
        with self.assertRaises(ValueError):
            upload_args('/synthetic.mp4', 'Unsupported upload command')
        with self.assertRaises(ValueError):
            upload_args('/synthetic.mp4', old_help, title='Manual', prefer_loom_titles=False)

    def test_manual_remote_rename_requires_advertised_title_option(self):
        args = rename_title_args('abc123', ' New title ', '  --title <title> New video title')
        self.assertEqual(args[:6], ['loom', 'video', 'rename', 'abc123', '--title', 'New title'])
        with self.assertRaises(ValueError):
            rename_title_args('abc123', 'Title', 'Unsupported command')

    def test_progress_is_indeterminate_without_actual_percentage(self):
        self.assertEqual(parse_upload_progress('Uploading Loom video...'),
                         {'stage': 'uploading', 'percent': None})
        self.assertEqual(parse_upload_progress('\x1b[32mUploading: 42.5%\x1b[0m\r'),
                         {'stage': 'uploading', 'percent': 42.5})
        self.assertEqual(parse_upload_progress('Processing Loom video...'),
                         {'stage': 'processing', 'percent': None})
        for value in ('Uploading: 101%', '100% unrelated',
                      '{"data":{"transfer":{"bytes":5000}}}',
                      '{"event":"upload_progress","percent":42}', 'Copied a link'):
            with self.subTest(value=value):
                self.assertIsNone(parse_upload_progress(value))


if __name__ == '__main__':
    unittest.main()
