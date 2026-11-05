"""Consent and required-version gates; all package commands are mocked."""
import contextlib
import io
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from untangle import preflight


class DependencyInstallTests(unittest.TestCase):
    def run_install(self, *, approved='yes', tty=True, yes=False, command_results=None, family='ubuntu'):
        rows = [dict(name='ffmpeg', ok=False, detail='missing')]
        with patch.object(preflight, 'check', return_value=rows), \
             patch.object(preflight.platform, 'freedesktop_os_release', return_value={'ID': family}), \
             patch.object(preflight.shutil, 'which', side_effect=lambda name: '/mock/' + name), \
             patch.object(preflight.os, 'geteuid', return_value=1000), \
             patch.object(preflight.sys.stdin, 'isatty', return_value=tty), \
             patch('builtins.input', return_value=approved) as prompt, \
             patch.object(preflight.subprocess, 'run',
                          side_effect=command_results,
                          return_value=SimpleNamespace(returncode=0)) as run, \
             contextlib.redirect_stdout(io.StringIO()) as output, \
             contextlib.redirect_stderr(io.StringIO()):
            code = preflight.main(['--install-deps', *(['--yes'] if yes else [])])
        return code, run, prompt, output.getvalue()

    def test_declining_or_missing_terminal_cannot_run_package_commands(self):
        for response, tty in [('no', True), ('', True), ('yes', False)]:
            with self.subTest(response=response, tty=tty):
                code, run, _, _ = self.run_install(approved=response, tty=tty)
                self.assertEqual(code, 1)
                run.assert_not_called()

    def test_consent_installs_and_requires_fresh_version_check(self):
        code, run, prompt, output = self.run_install()
        self.assertEqual(code, 0)
        prompt.assert_called_once()
        self.assertIn('apt-get install -y ffmpeg', output)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[:2], [['sudo', 'apt-get', 'update'],
                                       ['sudo', 'apt-get', 'install', '-y', 'ffmpeg']])
        self.assertEqual(commands[-1][:2], [preflight.sys.executable, str(preflight.Path(preflight.__file__).resolve())])
        # Package success is insufficient when the required version is still missing.
        code, _, _, _ = self.run_install(command_results=[SimpleNamespace(returncode=0),
            SimpleNamespace(returncode=0), SimpleNamespace(returncode=1)])
        self.assertEqual(code, 1)

    def test_failed_package_transaction_stops_before_recheck(self):
        code, run, _, _ = self.run_install(command_results=[subprocess.CalledProcessError(7, ['apt-get'])])
        self.assertEqual(code, 1)
        self.assertEqual(run.call_count, 1)

    def test_explicit_yes_supports_agents_without_prompt_or_password_wait(self):
        code, run, prompt, _ = self.run_install(tty=False, yes=True)
        self.assertEqual(code, 0)
        prompt.assert_not_called()
        self.assertEqual(run.call_args_list[0].args[0][:2], ['sudo', '-n'])

    def test_unknown_platform_never_runs_commands(self):
        code, run, prompt, _ = self.run_install(family='unknown')
        self.assertEqual(code, 1)
        run.assert_not_called()
        prompt.assert_not_called()

    def test_native_package_names_and_no_partial_arch_upgrade(self):
        cases = [('arch', 'pacman', 'libpulse', 'xorg-xwayland'),
                 ('ubuntu', 'apt-get', 'pulseaudio-utils', 'xwayland'),
                 ('fedora', 'dnf', 'pulseaudio-utils', 'xorg-x11-server-Xwayland'),
                 ('opensuse-tumbleweed', 'zypper', 'pulseaudio-utils', 'xwayland')]
        rows = [dict(name=name, ok=False) for name in ('pactl', 'Xwayland', 'obs-x264')]
        for family, manager, pulse, xwayland in cases:
            with self.subTest(family=family), \
                 patch.object(preflight.platform, 'freedesktop_os_release', return_value={'ID': family}), \
                 patch.object(preflight.shutil, 'which', return_value='/mock/manager'), \
                 patch.object(preflight.os, 'geteuid', return_value=0):
                commands = preflight.dependency_commands(rows)
            install = commands[-1]
            self.assertEqual(install[0], manager)
            self.assertIn(pulse, install)
            self.assertIn(xwayland, install)
            if manager == 'pacman':
                self.assertIn('-Syu', install)
            if manager == 'dnf':
                self.assertIn('obs-studio-plugin-x264', install)

    def test_uv_uses_private_environment_and_unambiguous_portal_backend(self):
        with patch.object(preflight.platform, 'freedesktop_os_release', return_value={'ID': 'arch'}), \
             patch.object(preflight.shutil, 'which', return_value='/mock/manager'), \
             patch.object(preflight.os, 'geteuid', return_value=0), \
             patch.dict(preflight.os.environ, {'XDG_CURRENT_DESKTOP': 'Hyprland'}, clear=True):
            commands = preflight.dependency_commands([dict(name='uv', ok=False),
                dict(name='ScreenCast portal backend', ok=False)])
        self.assertIn('xdg-desktop-portal-hyprland', commands[0])
        self.assertIn('uv>=0.9,<1', commands[2])
        self.assertNotIn('--system', [arg for command in commands for arg in command])

    def test_read_only_flags_cannot_trigger_repair(self):
        for flag in ('--check', '--json', '--runtime', '--session'):
            with self.subTest(flag=flag), patch.object(preflight, 'check') as check, \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit_code:
                preflight.main(['--install-deps', flag])
            self.assertEqual(exit_code.exception.code, 2)
            check.assert_not_called()
