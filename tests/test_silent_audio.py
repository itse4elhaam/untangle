"""Offline regressions for the all-zero AAC track in the 10:59 OnePlus file.

Only generated temporary media is decoded. No OBS/device capture or playback.
"""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import wave
from unittest.mock import Mock, patch

from untangle.engine import recording_audio_warning
from untangle.app import FinishWorker


class SavedAudioTests(unittest.TestCase):
    def test_actual_decoded_audio_not_track_presence_or_low_bitrate(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, audio, expected in (
                ('silent', 'anullsrc=r=48000:cl=stereo', 'silent'),
                ('quiet', 'sine=frequency=440:sample_rate=48000,volume=0.0001', ''),
                ('audible', 'sine=frequency=440:sample_rate=48000', ''),
                ('missing', None, 'no audio track'),
            ):
                with self.subTest(name=name):
                    path = Path(directory) / f'{name}.mp4'
                    args = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
                            '-f', 'lavfi', '-i', 'color=size=16x16:rate=10']
                    if audio:
                        args += ['-f', 'lavfi', '-i', audio]
                    subprocess.run(args + ['-t', '0.3', '-c:v', 'libx264', '-c:a', 'aac',
                                           str(path)], check=True, capture_output=True)
                    warning = recording_audio_warning(path)
                    if expected:
                        self.assertIn(expected, warning)
                    else:
                        self.assertEqual(warning, '')

    def test_decode_failure_does_not_claim_silence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.mp4'
            path.write_bytes(b'broken')
            self.assertIn('could not be verified', recording_audio_warning(path))

    def test_one_quiet_sample_in_either_channel_and_empty_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stereo.wav'
            silent_frame = struct.pack('<hh', 0, 0)
            for frames, expected in (
                (silent_frame * 48000 + struct.pack('<hh', 1, 0), ''),
                (silent_frame * 48000 + struct.pack('<hh', 0, -1), ''),
                (silent_frame, 'silent'),
                (b'', 'could not be verified'),
            ):
                with self.subTest(last_frame=frames[-4:]):
                    with wave.open(str(path), 'wb') as audio:
                        audio.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
                        audio.writeframes(frames)
                    warning = recording_audio_warning(path)
                    if expected:
                        self.assertIn(expected, warning)
                    else:
                        self.assertEqual(warning, '')

    def test_legacy_ffmpeg_still_requires_a_peak_and_positive_sample_count(self):
        probe = subprocess.CompletedProcess([], 0, stdout='{"streams":[{"index":0}]}')
        unsupported = subprocess.CompletedProcess([], 1, stderr="Option 'measure_perchannel' not found")
        unverified = 'Saved audio could not be verified. Review the recording before sharing.'
        for output, expected in (
            ('Peak level dB: -90\nNumber of samples: 4800', ''),
            ('Peak level dB: -90\nNumber of samples: 0', unverified),
            ('Number of samples: 4800', unverified),
        ):
            decoded = subprocess.CompletedProcess([], 0, stderr=output)
            with self.subTest(output=output), patch('untangle.engine.subprocess.run',
                    side_effect=[probe, unsupported, decoded]) as run:
                self.assertEqual(recording_audio_warning(Path('synthetic.wav')), expected)
                self.assertIn('astats=metadata=0:reset=0', run.call_args.args[0])

    def test_finish_checks_after_stop_and_propagates_warning(self):
        engine = Mock(audio_expected=True, errors=[])
        worker = FinishWorker(engine, Path('/fake/recording.mkv'))
        with patch('untangle.app.recording_audio_warning', return_value='Audio is silent.') as check:
            check.side_effect = lambda path, trace: (engine.stop.assert_called_once(), 'Audio is silent.')[1]
            worker.run()
        self.assertEqual(engine.errors, ['Audio is silent.'])

    def test_intentional_audio_off_skips_check(self):
        engine = Mock(audio_expected=False)
        with patch('untangle.app.recording_audio_warning') as check:
            FinishWorker(engine, Path('/fake/recording.mkv')).run()
        check.assert_not_called()
