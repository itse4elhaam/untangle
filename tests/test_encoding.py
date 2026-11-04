"""Recording encoder contracts with mocked OBS and synthetic media only."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from untangle.engine import Engine, EngineError


class EncodingTests(unittest.TestCase):
    def encoder_settings(self, encoder, **kwargs):
        engine = Engine.__new__(Engine)
        engine._obs = Mock()
        engine.width, engine.height, engine.fps = 1920, 1080, 30
        engine.encoders = ['ffmpeg_aac']
        engine._stop_event = Mock()
        engine._stop_callback = Mock()
        settings = []
        engine._data = lambda value: settings.append(value.copy()) or len(settings)
        engine._create_recording(Path('/synthetic.mkv'), encoder, **kwargs)
        self.assertEqual(settings[1], {'bitrate': 160})
        engine._obs.obs_output_set_audio_encoder.assert_called_once()
        return settings[0]

    def test_encoder_quality_modes_use_obs27_options_and_keep_aac(self):
        cpu = self.encoder_settings('obs_x264')
        self.assertEqual((cpu['rate_control'], cpu['crf']), ('CRF', 18))
        self.assertEqual(cpu['preset'], 'veryfast')
        hardware = self.encoder_settings('ffmpeg_vaapi')
        self.assertEqual((hardware['rate_control'], hardware['qp']), ('CQP', 18))
        fallback = self.encoder_settings('ffmpeg_vaapi', constant_bitrate=True)
        self.assertEqual(fallback['rate_control'], 'CBR')
        self.assertEqual(fallback['bitrate'], 6221)

    def test_unsupported_hardware_quality_mode_keeps_hardware_fallback(self):
        engine = Engine.__new__(Engine)
        engine._closed, engine._output, engine._configured = False, None, True
        engine._obs = Mock()
        engine.encoders = ['ffmpeg_vaapi', 'obs_x264']
        engine.warnings = []
        engine._create_recording = Mock(side_effect=[EngineError('CQP unsupported'), None])
        engine._release_recording = Mock()
        with tempfile.TemporaryDirectory() as root, patch('untangle.engine.os.access', return_value=True):
            path = Path(root) / 'take.mkv'
            engine.start(path)
        self.assertEqual(engine._create_recording.call_count, 2)
        engine._create_recording.assert_called_with(path, 'ffmpeg_vaapi', constant_bitrate=True)
        self.assertIn('compatible fixed bitrate', engine.warnings[0])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg unavailable')
    def test_synthetic_screen_compression_quality_and_lossless_mp4_preparation(self):
        # Static text/grid is a repeatable screen-content benchmark. This does
        # not establish quality or speed on a physical VAAPI device.
        font = Path('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf')
        if not font.is_file():
            self.skipTest('Synthetic text font unavailable')
        source = ('color=c=0x20252b:s=1280x720:r=30:d=2,'
                  'drawgrid=w=80:h=40:t=1:c=gray@0.3,'
                  f'drawtext=fontfile={font}:text=Untangle code review 0123456789:'
                  'fontsize=18:fontcolor=white:x=40:y=80')
        def run(args):
            return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30)
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            common = ['ffmpeg', '-hide_banner', '-nostdin', '-y', '-f', 'lavfi', '-i', source,
                      '-c:v', 'libx264', '-preset', 'veryfast', '-profile:v', 'high', '-g', '60', '-threads', '1']
            quality, cbr = root / 'quality.mkv', root / 'cbr.mkv'
            run([*common, '-crf', '18', str(quality)])
            run([*common, '-b:v', '6000k', '-minrate', '6000k', '-maxrate', '6000k',
                 '-bufsize', '6000k', '-x264-params', 'nal-hrd=cbr:filler=1', str(cbr)])
            self.assertLess(quality.stat().st_size, cbr.stat().st_size / 2)
            comparison = run(['ffmpeg', '-hide_banner', '-nostdin', '-i', str(quality),
                              '-f', 'lavfi', '-i', source, '-lavfi', 'ssim', '-f', 'null', '-'])
            score = float(re.search(r'All:([\d.]+)', comparison.stderr)[1])
            self.assertGreater(score, .99)
            mp4 = root / 'quality.mp4'
            run(['ffmpeg', '-nostdin', '-y', '-i', str(quality), '-map', '0', '-c', 'copy',
                 '-movflags', '+faststart', str(mp4)])
            probe = json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(mp4)]).stdout)['streams'][0]
            self.assertEqual((probe['width'], probe['height'], probe['r_frame_rate']), (1280, 720, '30/1'))
            hashes = [run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path),
                           '-f', 'framemd5', '-']).stdout for path in (quality, mp4)]
            self.assertEqual(hashes[0], hashes[1])
