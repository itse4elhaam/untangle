"""The ordinary runner must have no access to laptop devices or audio."""
import os
from pathlib import Path
import socket
import unittest


@unittest.skipUnless(os.environ.get('UNTANGLE_SYNTHETIC_SANDBOX') == '1',
                     'Run through scripts/test.sh for namespace isolation')
class TestSandboxTests(unittest.TestCase):
    def test_capture_and_sound_devices_are_absent(self):
        self.assertFalse(Path('/dev/snd').exists())
        self.assertFalse(list(Path('/dev').glob('video*')))
        self.assertFalse(Path('/run/dbus/system_bus_socket').exists())
        self.assertFalse(os.environ.get('DISPLAY'))
        self.assertFalse(os.environ.get('WAYLAND_DISPLAY'))

    def test_runtime_and_audio_endpoints_are_private_and_unavailable(self):
        self.assertEqual(os.environ['XDG_RUNTIME_DIR'], '/run/untangle-tests')
        self.assertEqual(Path('/run/untangle-tests').stat().st_mode & 0o777, 0o700)
        for address in ('PULSE_SERVER', 'DBUS_SESSION_BUS_ADDRESS', 'DBUS_SYSTEM_BUS_ADDRESS'):
            path = os.environ[address].removeprefix('unix:').removeprefix('path=')
            with self.subTest(address=address), socket.socket(socket.AF_UNIX) as connection:
                with self.assertRaises(OSError):
                    connection.connect(path)

    def test_repository_is_read_only_in_test_namespace(self):
        probe = Path(__file__).resolve().parents[1] / '.test-sandbox-write-probe'
        with self.assertRaises(OSError):
            probe.touch()
