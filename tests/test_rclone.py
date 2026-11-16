"""rclone runner and remote discovery with a mocked subprocess. No rclone process or network is used."""
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch

from untangle import rclone


class FakeProcess:
    def __init__(self, stderr=(), stdout='', returncode=0, finishes=True):
        self.stderr = iter(stderr)
        self.stdout = Mock(read=Mock(return_value=stdout))
        self.final = returncode
        self.returncode = returncode if finishes else None
        self.terminate = Mock(side_effect=self.stop)
        self.kill = Mock(side_effect=self.stop)

    def stop(self):
        self.returncode = -15

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


def popen(process):
    return patch('untangle.rclone.subprocess.Popen', return_value=process)


class RunTests(unittest.TestCase):
    def setUp(self):
        which = patch('untangle.rclone.executable', return_value='/usr/bin/rclone')
        which.start()
        self.addCleanup(which.stop)

    def test_runs_without_shell_or_prompts_and_returns_stdout(self):
        with popen(FakeProcess(stdout='[]')) as spawn:
            self.assertEqual(rclone.run(['lsjson', 'gdrive:'], timeout=5), '[]')
        command = spawn.call_args.args[0]
        self.assertEqual(command, ['/usr/bin/rclone', 'lsjson', 'gdrive:', '--ask-password=false'])
        self.assertIs(spawn.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.assertNotIn('shell', spawn.call_args.kwargs)

    def test_missing_rclone_raises_setup_message_without_spawning(self):
        with patch('untangle.rclone.executable', return_value=None), \
                patch('untangle.rclone.subprocess.Popen') as spawn:
            with self.assertRaises(rclone.RcloneMissing) as caught:
                rclone.run(['listremotes'], timeout=5)
        spawn.assert_not_called()
        self.assertIn('rclone config', str(caught.exception))

    def test_json_log_records_reach_progress(self):
        lines = ['{"level":"notice","stats":{"bytes":5,"totalBytes":10}}\n', 'plain text\n']
        records = []
        with popen(FakeProcess(stderr=lines)):
            rclone.run(['copyto', 'a', 'b'], timeout=5, on_log=records.append, capture=False)
        self.assertEqual(records[0]['stats'], {'bytes': 5, 'totalBytes': 10})

    def test_timeout_terminates_process(self):
        process = FakeProcess(finishes=False)
        with popen(process):
            with self.assertRaises(rclone.RcloneTimeout):
                rclone.run(['copyto', 'a', 'b'], timeout=0.3)
        process.terminate.assert_called_once_with()

    def test_cancel_terminates_process(self):
        process = FakeProcess(finishes=False)
        cancel = threading.Event()
        cancel.set()
        with popen(process):
            with self.assertRaises(rclone.RcloneCancelled):
                rclone.run(['copyto', 'a', 'b'], timeout=60, cancel=cancel)
        process.terminate.assert_called_once_with()

    def test_not_found_and_auth_failures_have_safe_messages(self):
        with popen(FakeProcess(returncode=3)):
            with self.assertRaises(rclone.RcloneNotFound):
                rclone.run(['lsjson', 'gdrive:'], timeout=5)
        error = '{"level":"error","msg":"oauth2: token expired secret-detail"}\n'
        with popen(FakeProcess(stderr=[error], returncode=1)):
            with self.assertRaises(rclone.RcloneError) as caught:
                rclone.run(['lsjson', 'gdrive:'], timeout=5)
        self.assertIn('rclone config reconnect', str(caught.exception))
        self.assertNotIn('secret-detail', str(caught.exception))
        self.assertIn('secret-detail', caught.exception.detail)


class DiscoveryTests(unittest.TestCase):
    LISTING = 'local: local\nwork: drive\nphotos: s3\nbackup: drive\n'

    def test_environment_override_needs_no_rclone_call(self):
        with patch.dict('os.environ', {'UNTANGLE_DRIVE_REMOTE': 'mine'}), \
                patch('untangle.rclone.run') as run:
            self.assertEqual(rclone.drive_remote('UNTANGLE_DRIVE_REMOTE'), 'mine:')
        run.assert_not_called()

    def test_first_drive_remote_unless_a_gdrive_remote_exists(self):
        with patch.dict('os.environ', {}, clear=True), \
                patch('untangle.rclone.executable', return_value='/usr/bin/rclone'), \
                patch('untangle.rclone.run', return_value=self.LISTING) as run:
            self.assertEqual(rclone.drive_remotes(), ['work:', 'backup:'])
            self.assertEqual(rclone.drive_remote('UNTANGLE_DRIVE_REMOTE'), 'work:')
            run.return_value = self.LISTING + 'gdrive-main: drive\n'
            self.assertEqual(rclone.drive_remote('UNTANGLE_DRIVE_REMOTE'), 'gdrive-main:')
        self.assertEqual(run.call_args.args[0], ['listremotes', '--long'])

    def test_no_drive_remote_or_no_rclone(self):
        with patch.dict('os.environ', {}, clear=True):
            with patch('untangle.rclone.executable', return_value=None):
                self.assertIsNone(rclone.drive_remote('UNTANGLE_DRIVE_REMOTE'))
            with patch('untangle.rclone.executable', return_value='/usr/bin/rclone'), \
                    patch('untangle.rclone.run', return_value='local: local\n'):
                self.assertIsNone(rclone.drive_remote('UNTANGLE_DRIVE_REMOTE'))
            with patch('untangle.rclone.executable', return_value='/usr/bin/rclone'), \
                    patch('untangle.rclone.run', side_effect=rclone.RcloneTimeout()):
                self.assertIsNone(rclone.drive_remote('UNTANGLE_DRIVE_REMOTE'))

    def test_review_tool_shares_discovery_with_its_own_variable(self):
        from untangle.review import sources
        with patch.dict('os.environ', {'UNTANGLE_REVIEW_DRIVE_REMOTE': 'reviews'}):
            self.assertEqual(sources.drive_remote(), 'reviews:')
