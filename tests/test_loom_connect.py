"""Exercise sign-in script with a fake CLI, never an account or browser."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class ConnectChecks(unittest.TestCase):
    def test_consent_and_login_failures_keep_terminal_message_and_stop(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/connect-loom.sh'
        whoami = 'whoami -o json --output-summary none'
        cases = [('consent', [whoami, 'consent']), ('login', [whoami, 'consent', 'login']),
                 ('none', [whoami, 'consent', 'login']),
                 # An expired session keeps its profile; only a forced login replaces it.
                 ('whoami', [whoami, 'consent', 'login --force'])]
        for failure, expected in cases:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cli = root / 'fake cli'
                log = root / 'calls'
                cli.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$MOCK_LOG"\n[[ "$1" != "$MOCK_FAIL" ]]\n')
                cli.chmod(0o700)
                result = subprocess.run(['bash', str(script), str(cli)], input='\n', text=True,
                    capture_output=True, timeout=5,
                    env={**os.environ, 'MOCK_LOG': str(log), 'MOCK_FAIL': failure})
                self.assertEqual(log.read_text().splitlines(), expected)
                succeeded = failure in ('none', 'whoami')
                self.assertEqual(result.returncode, 0 if succeeded else 1)
                self.assertIn('Connection finished' if succeeded else 'No video was uploaded', result.stdout)
