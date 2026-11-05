import contextlib
import io
import json
import unittest
from unittest.mock import patch, Mock

from untangle import preflight


class PreflightTests(unittest.TestCase):
    def test_missing_tools_never_run_commands(self):
        with patch.object(preflight.shutil, 'which', return_value=None), \
             patch.object(preflight.subprocess, 'run') as run, \
             patch.object(preflight.ctypes, 'CDLL', side_effect=OSError('missing')), \
             patch.object(preflight.ctypes.util, 'find_library', return_value=None), \
             patch.object(preflight, 'plugin_paths', return_value=[]), \
             patch.dict(preflight.os.environ, {'XDG_SESSION_TYPE': 'wayland'}, clear=True):
            rows = preflight.check()
        run.assert_not_called()
        self.assertFalse(next(row['ok'] for row in rows if row['name'] == 'Xwayland'))
        self.assertTrue(any(row['name'] == 'linux-pipewire' for row in rows))

    def test_obs_version_range(self):
        for major in (27, 28, 29, 30, 33, 34):
            obs = Mock()
            obs.obs_get_version.return_value = major << 24
            with patch.object(preflight.shutil, 'which', return_value=None), \
                 patch.object(preflight.ctypes, 'CDLL', return_value=obs), \
                 patch.object(preflight.ctypes.util, 'find_library', return_value='libobs.so.0'), \
                 patch.object(preflight, 'plugin_paths', return_value=[]):
                row = next(row for row in preflight.check() if row['name'] == 'libobs')
            self.assertEqual(row['ok'], major in (27, 30, 33))

    def test_json_failure_exit(self):
        output = io.StringIO()
        with patch.object(preflight, 'check', return_value=[dict(name='uv', ok=False, detail='missing')]), \
             contextlib.redirect_stdout(output):
            self.assertEqual(preflight.main(['--check', '--json']), 1)
        self.assertFalse(json.loads(output.getvalue())['ok'])

    def test_headless_wayland_and_pinned_runtime_checks(self):
        obs = Mock()
        with patch.object(preflight.shutil, 'which', side_effect=lambda name: '/fake/' + name), \
             patch.object(preflight.subprocess, 'run', return_value=Mock(returncode=0, stdout='uv 0.9.1', stderr='')), \
             patch.object(preflight.ctypes, 'CDLL', return_value=obs), \
             patch.object(preflight.ctypes.util, 'find_library', return_value='libobs.so.30'), \
             patch.object(preflight.Path, 'is_file', return_value=True), \
             patch.object(preflight.metadata, 'version', return_value='6.11.1'), \
             patch.object(preflight, 'screencast_backends', return_value=['hyprland']), \
             patch.dict(preflight.os.environ, {}, clear=True):
            obs.obs_get_version.return_value = 33 << 24
            rows = preflight.check(target_wayland=True, runtime=True)
            self.assertTrue(all(row['ok'] for row in rows), rows)
            session_rows = preflight.check(target_wayland=True, session=True)
            self.assertFalse(next(row['ok'] for row in session_rows if row['name'] == 'DISPLAY'))
            obs.obs_get_version.return_value = 27 << 24
            rows = preflight.check(target_wayland=True)
            self.assertFalse(next(row['ok'] for row in rows if row['name'] == 'Wayland OBS'))
            with patch.object(preflight.metadata, 'version', return_value='6.12.0'):
                rows = preflight.check(runtime=True)
            self.assertFalse(next(row['ok'] for row in rows if row['name'] == 'shiboken6'))

    def test_old_uv_cannot_replace_runtime(self):
        with patch.object(preflight.shutil, 'which', side_effect=lambda name: '/fake/' + name), \
             patch.object(preflight.subprocess, 'run', return_value=Mock(returncode=0, stdout='uv 0.8.0', stderr='')), \
             patch.object(preflight.ctypes, 'CDLL', side_effect=OSError('missing')), \
             patch.object(preflight.ctypes.util, 'find_library', return_value=None), \
             patch.object(preflight, 'plugin_paths', return_value=[]):
            rows = preflight.check()
        self.assertFalse(next(row['ok'] for row in rows if row['name'] == 'uv'))
