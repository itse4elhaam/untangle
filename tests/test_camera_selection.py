"""Camera selection uses synthetic V4L2 advertisements, never real devices."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from untangle.camera_devices import camera_quality


def formats(width, height, fps=30, colour='MJPG'):
    return f"[0]: '{colour}'\nSize: Discrete {width}x{height}\nInterval: Discrete 0.033s ({fps:.3f} fps)\n"


class CameraSelectionTests(unittest.TestCase):
    def test_prefers_highest_resolution_at_recording_frame_rate(self):
        self.assertGreater(camera_quality(formats(3840, 2160)), camera_quality(formats(1920, 1080)))
        self.assertGreater(camera_quality(formats(1920, 1080)), camera_quality(formats(3840, 2160, 15)))
        self.assertGreater(camera_quality(formats(1920, 1080, 60)), camera_quality(formats(1920, 1080)))

    def test_ir_modes_do_not_inflate_quality_and_unknown_modes_are_last(self):
        colour = formats(1280, 720)
        self.assertEqual(camera_quality(colour + formats(8000, 6000, colour='GREY')),
                         camera_quality(colour))
        self.assertGreater(camera_quality(colour), camera_quality('unavailable'))
        self.assertGreater(camera_quality(formats(1920, 1080, 15)),
                           camera_quality(formats(1280, 720, 15)))

    def test_discovery_places_best_camera_first_and_preserves_tie_order(self):
        from untangle.app import cameras
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            devices = []
            for index, name in enumerate(('Built-in camera', 'External 4K camera', 'Equal external camera')):
                device = root / f'video{index}'
                device.mkdir()
                (device / 'name').write_text(name)
                devices.append(device)
            samples = [formats(1280, 720), formats(3840, 2160), formats(3840, 2160)]
            with patch('untangle.app.Path.glob', return_value=devices), \
                    patch('untangle.app.subprocess.run', side_effect=[Mock(stdout=sample) for sample in samples]):
                self.assertEqual(cameras(), [('External 4K camera', '/dev/video1'),
                    ('Equal external camera', '/dev/video2'), ('Built-in camera', '/dev/video0')])
