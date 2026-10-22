"""Check source entry points without opening the app or installed runtime."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackageLayoutTests(unittest.TestCase):
    def test_module_entry_dispatches_main_outside_checkout(self):
        code = """
import runpy
from pathlib import Path
from unittest.mock import patch
from untangle import app
assert app.ICON.is_file()
assert (app.ROOT / 'scripts/connect-loom.sh').is_file()
with patch.object(app, 'main', return_value=17) as main:
    try:
        runpy.run_module('untangle', run_name='__main__')
    except SystemExit as result:
        assert result.code == 17
    else:
        raise AssertionError('entry point did not return the app exit code')
    main.assert_called_once_with()
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-c', code], cwd=directory,
                env=dict(os.environ, PYTHONPATH=str(ROOT / 'src')),
                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_symlinked_launchers_find_package_outside_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            python = home / '.local/share/glint/venv/bin/python'
            python.parent.mkdir(parents=True)
            # A stand-in interpreter records arguments and environment. No app runs.
            python.write_text(f'#!{sys.executable}\nimport json, os, sys\n'
                              'print(json.dumps([sys.argv[1:], os.environ["PYTHONPATH"]]))\n')
            python.chmod(0o755)
            for name in ('untangle', 'recit'):
                with self.subTest(launcher=name):
                    link = home / name
                    link.symlink_to(ROOT / 'bin' / name)
                    result = subprocess.run([str(link), 'argument with spaces'], cwd=home,
                        env=dict(os.environ, HOME=str(home), PYTHONPATH=''),
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    log = home / '.local/state/glint/glint.log'
                    args, source = json.loads(log.read_text().splitlines()[-1])
                    self.assertEqual(args, ['-m', 'untangle', 'argument with spaces'])
                    self.assertEqual(source, str(ROOT / 'src'))
