"""Installer failures must not replace an existing recording runtime."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallPreflightTests(unittest.TestCase):
    def test_check_and_dependency_failures_preserve_runtime(self):
        for args, preflight_exit in ((['--check', '--json'], '0'), ([], '1'), ([], '0')):
            with self.subTest(args=args, preflight_exit=preflight_exit), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                checkout, home, tools = root / 'checkout', root / 'home', root / 'tools'
                (checkout / 'scripts').mkdir(parents=True)
                tools.mkdir()
                runtime = home / '.local/share/glint/venv'
                runtime.mkdir(parents=True)
                marker = runtime / 'unchanged'
                marker.write_text('working runtime')
                shutil.copyfile(ROOT / 'scripts/install.sh', checkout / 'scripts/install.sh')
                # Stub the software check and dependency installer; no native libraries load.
                (tools / 'python3').write_text('#!/bin/bash\nexit "$PREFLIGHT_EXIT"\n')
                (tools / 'uv').write_text('#!/bin/bash\nexit 7\n')
                for tool in tools.iterdir():
                    tool.chmod(0o755)
                result = subprocess.run(['bash', str(checkout / 'scripts/install.sh'), *args],
                    env=dict(os.environ, HOME=str(home), PATH=f'{tools}:{os.defpath}',
                             PREFLIGHT_EXIT=preflight_exit), capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0 if args else (1 if preflight_exit == '1' else 7))
                self.assertEqual(marker.read_text(), 'working runtime')
                self.assertFalse((home / '.local/bin').exists() if args or preflight_exit == '1'
                                 else any((home / '.local/bin').iterdir()))
                self.assertFalse(list(runtime.parent.glob('venv-stage.*')))
                self.assertFalse((runtime.parent / 'venv.previous').exists())
