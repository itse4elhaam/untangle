"""Exercise menu installation in a temporary home without installing or opening apps."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

from PySide6.QtGui import QImage


ROOT = Path(__file__).resolve().parents[1]
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


class DesktopIconTests(unittest.TestCase):
    def test_installer_rerun_replaces_art_and_refreshes_xdg_icons(self):
        for custom_xdg in (False, True):
            with self.subTest(custom_xdg=custom_xdg), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                home = temporary / 'test home'
                checkout = temporary / 'test checkout'
                tools = temporary / 'tools'
                for path in (home, checkout / 'scripts', checkout / 'assets', tools):
                    path.mkdir(parents=True)
                shutil.copyfile(ROOT / 'scripts/install.sh', checkout / 'scripts/install.sh')
                (checkout / 'requirements.txt').touch()
                python = home / '.local/share/glint/venv/bin/python'
                python.parent.mkdir(parents=True)
                python.write_text(f'#!/bin/bash\nexec {shlex.quote(sys.executable)} "$@"\n')
                python.chmod(0o755)
                # Dependency installation and cache tools are stand-ins. Only the
                # installer and its image renderer execute in this temporary home.
                for name in ('uv', 'obs', 'ffmpeg'):
                    command = tools / name
                    command.write_text('#!/bin/bash\nexit 0\n')
                    command.chmod(0o755)
                for name in ('gtk-update-icon-cache', 'update-desktop-database'):
                    command = tools / name
                    command.write_text('#!/bin/bash\n'
                                       'printf "%s\\n" "$0" "$@" >> "$ICON_TEST_LOG"\n')
                    command.chmod(0o755)
                log = temporary / 'cache calls'
                env = dict(os.environ, HOME=str(home), PATH=f'{tools}:{os.defpath}',
                           ICON_TEST_LOG=str(log))
                for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'XDG_DATA_HOME'):
                    env.pop(name, None)
                data = home / '.local/share'
                if custom_xdg:
                    data = temporary / 'custom data'
                    env['XDG_DATA_HOME'] = str(data)
                icons = data / 'icons/hicolor'
                svg = icons / 'scalable/apps/tech.truedevs.Untangle.svg'
                svg.parent.mkdir(parents=True)
                # Reproduce the old installer layout, including its symlink.
                source = checkout / 'assets/untangle-mark.svg'
                svg.symlink_to(source)
                desktop = data / 'applications'
                desktop.mkdir(parents=True)
                legacy = desktop / 'tech.truedevs.RecIt.desktop'
                legacy.touch()
                for color in ('#2454b8', '#b85424'):
                    source.write_text('<svg xmlns="http://www.w3.org/2000/svg" '
                                      'width="512" height="512" viewBox="0 0 512 512">'
                                      f'<rect width="512" height="512" fill="{color}"/>'
                                      '</svg>')
                    result = subprocess.run(['bash', str(checkout / 'scripts/install.sh')],
                                            cwd=temporary, env=env, capture_output=True,
                                            text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(svg.is_symlink())
                    self.assertEqual(svg.read_bytes(), source.read_bytes())
                    for size in SIZES:
                        icon = QImage(str(icons / f'{size}x{size}/apps/tech.truedevs.Untangle.png'))
                        self.assertEqual((icon.width(), icon.height()), (size, size))
                        self.assertEqual(icon.pixelColor(size // 2, size // 2).name(), color)
                    self.assertFalse(legacy.exists())
                    entry = (desktop / 'tech.truedevs.Untangle.desktop').read_text()
                    self.assertIn('\nIcon=tech.truedevs.Untangle\n', entry)
                    self.assertIn(f'Exec="{home}/.local/bin/untangle"', entry)
                    self.assertIn(str(icons), log.read_text())
                    self.assertIn(str(desktop), log.read_text())
                calls = log.read_text()
                self.assertEqual(calls.count(str(tools / 'gtk-update-icon-cache')), 2)
                self.assertEqual(calls.count(str(tools / 'update-desktop-database')), 2)
