"""Existing recording quality remains the default; OBS is mocked."""
from pathlib import Path
import unittest
from unittest.mock import Mock
from untangle.engine import Engine


class EncodingTests(unittest.TestCase):
    def test_recording_keeps_original_bitrate_and_audio_settings(self):
        for encoder in ('obs_x264', 'ffmpeg_vaapi'):
            with self.subTest(encoder=encoder):
                engine = Engine.__new__(Engine)
                engine._obs = Mock()
                engine.width, engine.height, engine.fps = 1920, 1080, 30
                engine.encoders = ['ffmpeg_aac']
                engine._stop_event = Mock()
                engine._stop_callback = Mock()
                settings = []
                engine._data = lambda value: settings.append(value.copy()) or len(settings)
                engine._create_recording(Path('/synthetic.mkv'), encoder)
                self.assertEqual(settings[0]['rate_control'], 'CBR')
                self.assertEqual(settings[0]['bitrate'], 6221)
                self.assertNotIn('crf', settings[0])
                self.assertNotIn('qp', settings[0])
                self.assertEqual(settings[1], {'bitrate': 160})
