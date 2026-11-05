"""Check installation prerequisites; repair them only with explicit consent."""
import argparse
import ctypes
import ctypes.util
import json
from importlib import metadata
import platform
import re
import shlex
import os
from pathlib import Path
import shutil
import subprocess
import sys

HINT = ('Arch: sudo pacman -S obs-studio ffmpeg libpulse v4l-utils uv. '
        'Ubuntu: sudo apt install obs-studio obs-plugins ffmpeg pulseaudio-utils v4l-utils; '
        'install uv from https://docs.astral.sh/uv/getting-started/installation/. '
        'Wayland/Omarchy: sudo pacman -S xorg-xwayland pipewire pipewire-pulse '
        'xdg-desktop-portal xdg-desktop-portal-hyprland. '
        'Use OBS 27 on X11 or 30–33 on X11/Wayland. '
        'Future OBS versions are rejected until their native API is reviewed. '
        'Run scripts/install.sh to offer prerequisite installation after confirmation.')


def plugin_paths():
    """Search native and multiarch package layouts without assuming a distro."""
    roots = [Path('/usr/lib'), Path('/usr/lib64'), Path('/usr/local/lib')]
    roots += list(Path('/usr/lib').glob('*-linux-gnu'))
    return [root / 'obs-plugins' for root in roots]


def screencast_backends():
    """Read installed portal declarations without activating the session bus."""
    result = []
    for root in (Path('/usr/share/xdg-desktop-portal/portals'),
                 Path('/usr/local/share/xdg-desktop-portal/portals')):
        for path in root.glob('*.portal'):
            try:
                if 'org.freedesktop.impl.portal.ScreenCast' in path.read_text():
                    result.append(path.stem)
            except (OSError, UnicodeError):
                continue
    return result


def check(*, session=False, runtime=False, target_wayland=False):
    results = []

    def record(name, ok, detail):
        results.append(dict(name=name, ok=bool(ok), detail=detail))

    record('platform', sys.platform == 'linux' and platform.machine() == 'x86_64',
           f'{sys.platform}/{platform.machine()} (requires x86-64 Linux)')
    record('python', sys.version_info >= (3, 10), sys.version.split()[0] + ' (requires 3.10+)')
    for name, flag in [('uv', '--version'), ('ffmpeg', '-version'),
                       ('ffprobe', '-version'), ('pactl', '--version'),
                       ('v4l2-ctl', '--version')]:
        executable = shutil.which(name)
        try:
            if not executable:
                raise OSError('not found in PATH')
            proc = subprocess.run([executable, flag], capture_output=True, text=True, timeout=10)
            output = (proc.stdout or proc.stderr).strip()
            version = re.search(r'uv (\d+)\.(\d+)\.(\d+)', output) if name == 'uv' else None
            compatible = name != 'uv' or (version and tuple(map(int, version.groups())) >= (0, 9, 0))
            record(name, proc.returncode == 0 and compatible,
                   (output.splitlines()[0] if output else 'no version output')
                   + (' (requires uv 0.9+)' if name == 'uv' else ''))
        except (OSError, subprocess.SubprocessError) as exc:
            record(name, False, str(exc))
    major = None
    library = ctypes.util.find_library('obs') or 'libobs.so.0'
    try:
        obs = ctypes.CDLL(library)
        obs.obs_get_version.restype = ctypes.c_uint32
        version = obs.obs_get_version()
        major = version >> 24
        record('libobs', major == 27 or 30 <= major <= 33,
               f'{library}: {major}.{(version >> 16) & 255}.{version & 65535} (requires 27 or 30–33)')
    except (OSError, AttributeError) as exc:
        record('libobs', False, str(exc))
    wayland = target_wayland or bool(os.environ.get('WAYLAND_DISPLAY')) or os.environ.get('XDG_SESSION_TYPE') == 'wayland'
    if wayland:
        record('Wayland OBS', major is not None and 30 <= major <= 33, 'Wayland capture requires OBS 30–33')
        record('pipewire', bool(shutil.which('pipewire')), 'Wayland capture requires the PipeWire daemon package')
        record('Xwayland', shutil.which('Xwayland') is not None, 'Install xorg-xwayland for embedded preview')
        backends = screencast_backends()
        record('ScreenCast portal backend', bool(backends),
               ', '.join(backends) or 'Install a screen-sharing portal backend for your desktop')
        for name in ('xdg-desktop-portal', 'xdg-desktop-portal-hyprland'):
            if name.endswith('hyprland') and 'hyprland' not in os.environ.get('XDG_CURRENT_DESKTOP', '').lower():
                continue
            found = shutil.which(name) or next((str(root / name) for root in
                (Path('/usr/lib'), Path('/usr/libexec')) if (root / name).is_file()), None)
            record(name, bool(found), found or 'Desktop portal executable missing')
    if session:
        record('DISPLAY', bool(os.environ.get('DISPLAY')), 'Launch inside your graphical session; Xwayland is required on Wayland')
        if wayland:
            record('session bus', bool(os.environ.get('DBUS_SESSION_BUS_ADDRESS')),
                   'A graphical session bus is required for the permission picker; services are not contacted by this check')
    plugins = ['obs-ffmpeg', 'obs-x264', 'obs-outputs', 'obs-filters', 'image-source',
               'linux-v4l2', 'linux-pulseaudio', 'linux-capture']
    if wayland:
        plugins.append('linux-pipewire')
    for name in plugins:
        found = next((root / (name + '.so') for root in plugin_paths() if (root / (name + '.so')).is_file()), None)
        record(name, found is not None, str(found) if found else 'OBS plugin missing')
    if runtime:
        for name in ('PySide6-Essentials', 'PySide6-Addons', 'shiboken6'):
            try:
                version = metadata.version(name)
                record(name, version == '6.11.1', f'{version} (requires 6.11.1)')
            except metadata.PackageNotFoundError:
                record(name, False, 'Missing from this Python runtime. Rerun scripts/install.sh.')
    return results


def dependency_commands(results, *, assume_yes=False):
    """Build a reviewable repair plan, without executing commands or writes."""
    failed = {row['name'] for row in results if not row['ok']}
    if 'platform' in failed:
        raise ValueError('Untangle requires x86-64 Linux. No automatic repair is available for this platform.')
    try:
        release = platform.freedesktop_os_release()
    except (AttributeError, OSError):
        try:
            release = {}
            for line in Path('/etc/os-release').read_text().splitlines():
                key, separator, value = line.partition('=')
                if separator and key in ('ID', 'ID_LIKE'):
                    release[key] = shlex.split(value)[0]
        except (OSError, ValueError, IndexError):
            release = {}
    families = {release.get('ID', ''), *release.get('ID_LIKE', '').split()}
    if families & {'arch', 'omarchy', 'manjaro'}:
        manager, install = 'pacman', ['pacman', '-Syu', '--noconfirm']
        packages = {'python': ['python'], 'pactl': ['libpulse'], 'venv': ['python']}
    elif families & {'debian', 'ubuntu', 'pop', 'linuxmint'}:
        manager, install = 'apt-get', ['apt-get', 'install', '-y']
        packages = {'python': ['python3', 'python3-venv'], 'pactl': ['pulseaudio-utils'],
                    'venv': ['python3-venv']}
    elif families & {'fedora', 'rhel', 'centos', 'rocky', 'almalinux'}:
        manager, install = 'dnf', ['dnf', 'install', '-y']
        packages = {'python': ['python3'], 'pactl': ['pulseaudio-utils'], 'venv': ['python3-pip']}
    elif families & {'suse', 'opensuse', 'opensuse-tumbleweed', 'opensuse-leap'}:
        manager, install = 'zypper', ['zypper', '--non-interactive', 'install']
        packages = {'python': ['python3'], 'pactl': ['pulseaudio-utils'], 'venv': ['python3-pip']}
    else:
        raise ValueError('Automatic prerequisite installation supports Arch, Debian/Ubuntu, Fedora/RHEL and openSUSE families. '
                         'Install the reported prerequisites using your platform tools and rerun; Untangle was not installed.')
    packages.update({'ffmpeg': ['ffmpeg'], 'ffprobe': ['ffmpeg'], 'v4l2-ctl': ['v4l-utils'],
                     'Xwayland': ['xorg-xwayland' if manager == 'pacman' else
                                  'xorg-x11-server-Xwayland' if manager == 'dnf' else 'xwayland'],
                     'xdg-desktop-portal': ['xdg-desktop-portal'], 'pipewire': ['pipewire']})
    obs_checks = {'libobs', 'Wayland OBS', 'obs-ffmpeg', 'obs-x264', 'obs-outputs',
                  'obs-filters', 'image-source', 'linux-v4l2', 'linux-pulseaudio',
                  'linux-capture', 'linux-pipewire'}
    wanted = set()
    for name in failed:
        if name in obs_checks:
            wanted.add('obs-studio')
            if manager == 'apt-get':
                wanted.add('obs-plugins')
            if manager == 'dnf' and name in ('obs-x264', 'libobs', 'Wayland OBS'):
                wanted.add('obs-studio-plugin-x264')
        elif name == 'ScreenCast portal backend':
            desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
            backend = next((backend for desktop_name, backend in
                            [('hyprland', 'hyprland'), ('gnome', 'gnome'), ('kde', 'kde'), ('sway', 'wlr')]
                            if desktop_name in desktop), None)
            if not backend:
                raise ValueError('Cannot select a screen-sharing backend for this desktop. '
                                 'Run from your desktop session or specify XDG_CURRENT_DESKTOP, '
                                 'for example XDG_CURRENT_DESKTOP=Hyprland over SSH.')
            wanted.update(['xdg-desktop-portal', 'xdg-desktop-portal-' + backend])
        elif name.startswith('xdg-desktop-portal-'):
            wanted.add(name)
        elif name == 'uv':
            wanted.update(packages['venv'])
        elif name in packages:
            wanted.update(packages[name])
        else:
            raise ValueError(f'{name} requires manual repair. Untangle was not installed.')
    commands = []
    if wanted:
        if not shutil.which(manager):
            raise ValueError(f'{manager} is missing. Install prerequisites manually and rerun.')
        prefix = []
        if os.geteuid() != 0:
            if not shutil.which('sudo'):
                raise ValueError('sudo is missing. Have an administrator install the reported prerequisites and rerun.')
            prefix = ['sudo', '-n'] if assume_yes else ['sudo']
        if manager == 'apt-get':
            commands.append(prefix + ['apt-get', 'update'])
        commands.append(prefix + install + sorted(wanted))
    if 'uv' in failed:
        # A private tool environment avoids modifying the system Python or an
        # unrelated uv installation. The app runtime is still untouched.
        tools = Path.home() / '.local/share/glint/bootstrap-tools'
        link_dir = Path.home() / '.local/share/glint/tools-bin'
        commands.extend([[sys.executable, '-m', 'venv', str(tools)],
                         [str(tools / 'bin/python'), '-m', 'pip', 'install', '--upgrade', 'uv>=0.9,<1'],
                         ['mkdir', '-p', str(link_dir)],
                         ['ln', '-sfn', str(tools / 'bin/uv'), str(link_dir / 'uv')]])
    return commands


def repair_prerequisites(results, *, assume_yes=False, target_wayland=False):
    try:
        commands = dependency_commands(results, assume_yes=assume_yes)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print('Required prerequisite installation/upgrade commands:')
    for command in commands:
        print('  ' + shlex.join(command))
    if any('pacman' in command for command in commands):
        print('Arch requires a full system upgrade with these packages; partial upgrades are unsupported.')
    if not assume_yes:
        if not sys.stdin.isatty():
            print('No interactive input. Rerun in a terminal, or pass --yes to approve the displayed prerequisite plan.', file=sys.stderr)
            return 1
        try:
            approved = input('Install/upgrade these prerequisites before installing Untangle? [y/N] ').strip().lower()
        except EOFError:
            approved = ''
        if approved not in ('y', 'yes'):
            print('Cancelled. Untangle was not installed.')
            return 1
    try:
        for command in commands:
            subprocess.run(command, check=True)
        # libobs may already be mapped into this process; only a fresh process
        # can verify a newly installed native library or Python interpreter.
        print('Rechecking required versions before installing Untangle…', flush=True)
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                 *(['--wayland'] if target_wayland else [])])
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f'Prerequisite installation failed: {exc}. Untangle was not installed.', file=sys.stderr)
        return 1
    if result.returncode:
        print('Required versions are still unavailable. Untangle was not installed. '
              'Your configured repositories may not provide a supported OBS/Python version. '
              'No repositories were added and no forced downgrade was attempted.', file=sys.stderr)
    return 0 if result.returncode == 0 else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='check software without changing anything')
    parser.add_argument('--json', action='store_true', help='emit machine-readable diagnostics')
    parser.add_argument('--wayland', action='store_true', help='check Wayland requirements even over SSH')
    parser.add_argument('--session', action='store_true', help='also check graphical session environment, without contacting services')
    parser.add_argument('--runtime', action='store_true', help='also check pinned Qt distribution versions')
    parser.add_argument('--install-deps', action='store_true', help='offer to repair failed prerequisites, then recheck')
    parser.add_argument('--yes', action='store_true', help='approve prerequisite installation without prompting')
    args = parser.parse_args(argv)
    if args.install_deps and (args.check or args.json or args.session or args.runtime):
        parser.error('--install-deps cannot be combined with check-only, session or runtime modes')
    if args.yes and not args.install_deps:
        parser.error('--yes requires --install-deps')
    results = check(session=args.session, runtime=args.runtime, target_wayland=args.wayland)
    ok = all(row['ok'] for row in results)
    if args.json:
        print(json.dumps(dict(ok=ok, checks=results, hint=HINT)))
    else:
        for row in results:
            print(f"{'OK' if row['ok'] else 'ERROR'} {row['name']}: {row['detail']}")
        if not ok:
            print(HINT)
    if not ok and args.install_deps:
        return repair_prerequisites(results, assume_yes=args.yes, target_wayland=args.wayland)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
