"""Encoded synthetic XSHM pixels; execution requires the isolated test runner."""
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


class ControlStripPixels(unittest.TestCase):
    @unittest.skipUnless(shutil.which('Xvfb'), 'requires Xvfb')
    def test_encoded_strip_exclusion(self):
        self.assertEqual(os.environ.get('UNTANGLE_SYNTHETIC_SANDBOX'), '1')
        for scale in ('1', '1.5'):
            with self.subTest(scale=scale), tempfile.TemporaryDirectory() as directory:
                env = dict(os.environ)
                for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY'):
                    env.pop(key, None)
                read_fd, write_fd = os.pipe()
                server = None
                try:
                    server = subprocess.Popen([shutil.which('Xvfb'), '-displayfd', str(write_fd),
                        '-screen', '0', '1280x900x24', '-nolisten', 'tcp', '-ac'],
                        pass_fds=(write_fd,), env=env, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
                    os.close(write_fd)
                    write_fd = None
                    self.assertTrue(select.select([read_fd], [], [], 10)[0], 'Xvfb timeout')
                    number = os.read(read_fd, 32).decode().strip()
                    self.assertTrue(number.isdigit(), 'Xvfb failed')
                    env.update(DISPLAY=':' + number, UNTANGLE_PIXEL_DISPLAY=':' + number,
                               QT_QPA_PLATFORM='xcb', QT_SCALE_FACTOR=scale,
                               QT_ACCESSIBILITY='0', LIBGL_ALWAYS_SOFTWARE='1')
                    child = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                        '--pixel-worker', directory], env=env, capture_output=True,
                        text=True, timeout=90)
                    self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
                    print(child.stdout, end='')
                finally:
                    os.close(read_fd)
                    if write_fd is not None:
                        os.close(write_fd)
                    if server:
                        server.terminate()
                        try:
                            server.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            server.kill()
                            server.wait(timeout=5)


def worker(directory):
    assert os.environ.get('UNTANGLE_SYNTHETIC_SANDBOX') == '1'
    assert os.environ['DISPLAY'] == os.environ['UNTANGLE_PIXEL_DISPLAY']
    import ctypes as C
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from untangle import engine as module
    from untangle.recording_controls import RecordingControls

    class Engine(module.Engine):
        def _load_modules(self):
            for name in ('linux-capture', 'image-source', 'obs-filters', 'obs-x264',
                         'obs-ffmpeg', 'obs-outputs'):
                plugin = module.P()
                code = self._obs.obs_open_module(C.byref(plugin),
                    f'/usr/lib/x86_64-linux-gnu/obs-plugins/{name}.so'.encode(),
                    f'/usr/share/obs/obs-plugins/{name}'.encode())
                assert code == 0 and self._obs.obs_init_module(plugin), name
            self._obs.obs_post_load_modules()

        def _source(self, kind, name, settings):
            assert kind in ('xshm_input', 'crop_filter'), kind
            return super()._source(kind, name, settings)

    app = QApplication([])

    def tick(milliseconds):
        # OBS invokes Python display callbacks on its render thread. Release
        # the GIL between Qt event pumps so the encoded timeline really runs.
        until = time.monotonic() + milliseconds / 1000
        while time.monotonic() < until:
            app.processEvents()
            time.sleep(.01)

    target = QWidget()
    target.setWindowFlags(Qt.FramelessWindowHint)
    target.setGeometry(app.primaryScreen().geometry())
    target.setStyleSheet('background: rgb(0,0,255)')
    target.show()
    preview = QWidget()
    preview.resize(160, 90)
    controls = RecordingControls()
    controls.setStyleSheet('QFrame#recordingDock { background: rgb(255,0,255); }')
    engine = None
    try:
        engine = Engine(int(preview.winId()), 640, 360, fps=10)
        engine.encoders = [e for e in engine.encoders if e != 'ffmpeg_vaapi']
        for name, cut, zoom in (('baseline', 0, False), ('cropped',
                round(120 * app.primaryScreen().devicePixelRatio()), False),
                ('zoom', round(120 * app.primaryScreen().devicePixelRatio()), True)):
            engine.configure(camera=None, microphone=None, desktop_audio=False,
                             screen_cut_bottom=cut)
            controls.show_in_strip(app.primaryScreen(), 120)
            tick(300)
            assert controls.isVisible()
            path = Path(directory) / (name + '.mkv')
            engine.start(path)
            assert engine.encoder == 'obs_x264', engine.encoder
            for index in range(4):
                target.setStyleSheet('background: rgb(0,0,255)' if index % 2 == 0
                                    else 'background: rgb(0,255,0)')
                if zoom:
                    engine.set_screen_zoom(2., .5, 1. if index % 2 else 0.)
                tick(1200)
                assert controls.isVisible()
            engine.stop()
            raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path),
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                capture_output=True, timeout=20, check=True).stdout
            frame_bytes = 640 * 360 * 3
            assert len(raw) % frame_bytes == 0
            assert len(raw) >= frame_bytes * 30, 'too few decoded frames'
            # One bit in each byte represents a threshold match for one pixel.
            # C-backed translations and big-int masks check EVERY decoded pixel
            # without sampling, downscaling, or a NumPy dependency.
            high = bytes(value > 180 for value in range(256))
            low = bytes(value < 90 for value in range(256))
            red, green, blue = raw[0::3], raw[1::3], raw[2::3]
            rh = int.from_bytes(red.translate(high), 'little')
            rl = int.from_bytes(red.translate(low), 'little')
            gh = int.from_bytes(green.translate(high), 'little')
            gl = int.from_bytes(green.translate(low), 'little')
            bh = int.from_bytes(blue.translate(high), 'little')
            bl = int.from_bytes(blue.translate(low), 'little')
            counts = [(rh & bh & gl).bit_count(), (bh & rl & gl).bit_count(),
                      (gh & rl & bl).bit_count()]
            print(f'DPR={app.primaryScreen().devicePixelRatio()} {name}: magenta/blue/green={counts}')
            assert counts[0] > 1000 if name == 'baseline' else counts[0] == 0, counts
            assert counts[1] > 10000 and counts[2] > 10000, counts
    finally:
        if engine:
            engine.close()
        controls.close()
        target.close()
        preview.close()


if __name__ == '__main__' and '--pixel-worker' in sys.argv:
    worker(sys.argv[-1])
