"""Real X11 event routing on a private synthetic desktop, never host capture."""
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import unittest


class OverlayInputTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('Xvfb'), 'requires Xvfb for private X11 input routing')
    def test_original_window_selection_and_camera_drag(self):
        self.assertEqual(os.environ.get('UNTANGLE_SYNTHETIC_SANDBOX'), '1',
                         'Run through scripts/test.sh, never on the host desktop')
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ)
            for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'QT_SCALE_FACTOR'):
                env.pop(key, None)
            read_fd, write_fd = os.pipe()
            try:
                with open(Path(directory) / 'xvfb.log', 'w+') as log:
                    server = subprocess.Popen([shutil.which('Xvfb'), '-displayfd', str(write_fd),
                        '-screen', '0', '1280x900x24', '-nolisten', 'tcp', '-ac'],
                        pass_fds=(write_fd,), stdout=log, stderr=log, env=env)
                    os.close(write_fd)
                    write_fd = None
                    try:
                        self.assertTrue(select.select([read_fd], [], [], 10)[0], 'Xvfb startup timed out')
                        number = os.read(read_fd, 32).decode().strip()
                        log.seek(0)
                        self.assertTrue(number.isdigit(), log.read())
                        env.update(DISPLAY=':' + number, UNTANGLE_OVERLAY_TEST_DISPLAY=':' + number,
                                   QT_QPA_PLATFORM='xcb', QT_ACCESSIBILITY='0', LIBGL_ALWAYS_SOFTWARE='1')
                        for scale in ('1', '1.5'):
                            env['QT_SCALE_FACTOR'] = scale
                            for backend in ('mock', 'obs'):
                                child = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                    '--overlay-worker', backend], env=env,
                                    capture_output=True, text=True, timeout=30)
                                self.assertEqual(child.returncode, 0,
                                                 f'{backend}, scale {scale}: ' + child.stdout + child.stderr)
                                self.assertIn('original window selection and camera drag passed', child.stdout)
                    finally:
                        server.terminate()
                        try:
                            server.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            server.kill()
                            server.wait(timeout=5)
            finally:
                os.close(read_fd)
                if write_fd is not None:
                    os.close(write_fd)


def overlay_worker():
    assert os.environ.get('UNTANGLE_SYNTHETIC_SANDBOX') == '1'
    assert os.environ['DISPLAY'] == os.environ['UNTANGLE_OVERLAY_TEST_DISPLAY']
    from Xlib import X, XK, display
    from Xlib.ext import shape, xtest
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QImage, QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QTextEdit
    from unittest.mock import patch
    import test_app

    case = test_app.AppChecks()
    case.setUp()  # OBS, camera discovery, audio and global hotkeys are mocked.
    recorder = case.window
    target = QTextEdit('select these words in the original application')
    target.setGeometry(30, 30, 500, 350)
    target.show()
    connection = display.Display()
    root = connection.screen().root
    bubble = recorder.bubble
    ratio = target.devicePixelRatioF()

    def settle():
        connection.sync()
        QTest.qWait(30)

    def pointer(point):
        xtest.fake_input(connection, X.MotionNotify,
                         x=round(point.x() * ratio), y=round(point.y() * ratio))
        settle()

    def button(kind):
        xtest.fake_input(connection, kind, 1)
        settle()

    def select_text():
        cursor = target.textCursor()
        cursor.setPosition(0)
        target.setTextCursor(cursor)
        start = target.viewport().mapToGlobal(QPoint(5, 12))
        pointer(start)
        button(X.ButtonPress)
        pointer(start + QPoint(230, 0))
        button(X.ButtonRelease)
        assert len(target.textCursor().selectedText()) > 5, 'overlay blocked original text selection'

    try:
        settle()
        target_window = connection.create_resource_object('window', int(target.winId()))
        recorder.show()
        if sys.argv[-1] == 'obs':
            import ctypes as C
            from untangle import engine as module

            class SyntheticEngine(module.Engine):
                def _load_modules(self):
                    # The only capture target is our synthetic text window on
                    # private Xvfb. Never load camera or audio capture plugins.
                    for name in ('linux-capture', 'image-source', 'obs-filters'):
                        plugin = module.P()
                        code = self._obs.obs_open_module(C.byref(plugin),
                            f'/usr/lib/x86_64-linux-gnu/obs-plugins/{name}.so'.encode(),
                            f'/usr/share/obs/obs-plugins/{name}'.encode())
                        assert code == 0 and self._obs.obs_init_module(plugin), name
                    self._obs.obs_post_load_modules()

                def _source(self, kind, name, settings):
                    if kind == 'v4l2_input':
                        kind, settings = 'image_source', {'file': str(camera_path)}
                    assert kind in ('xcomposite_input', 'image_source',
                                    'crop_filter', 'mask_filter_v2'), kind
                    if kind == 'xcomposite_input':
                        assert settings['capture_window'] == str(target_window.id)
                    return super()._source(kind, name, settings)

            camera_path = case.root / 'synthetic-camera.png'
            frame = QImage(320, 180, QImage.Format_ARGB32_Premultiplied)
            frame.fill('orange')
            assert frame.save(str(camera_path))
            recorder.engine = SyntheticEngine(int(recorder.preview.winId()), 640, 360)
            with patch.object(module, 'camera_settings', return_value={}):
                recorder.engine.configure(mode='screen', camera=str(camera_path),
                    window_id=target_window.id, shape='circle', microphone=None, desktop_audio=False)
            recorder.configure_timer.stop()

        target_window.set_input_focus(X.RevertToParent, X.CurrentTime)
        settle()
        recorder.hide_for_capture()
        assert not recorder.isVisible(), 'recording must leave the original application visible'
        recorder.show_bubble()
        frame = QImage(100, 100, QImage.Format_ARGB32_Premultiplied)
        frame.fill('orange')
        bubble.set_frame(frame)
        bubble.apply_shape('circle')
        # Keep the camera clear of the text but over the target's lower area.
        bubble.move(280, 180)
        settle()
        assert not bubble._input_passthrough, 'native input region failed; camera cannot be dragged'
        native = connection.create_resource_object('window', int(bubble.winId()))
        assert native.get_attributes().override_redirect, 'camera must have no window-manager frame'
        assert native.query_tree().parent.id == root.id
        assert native.get_wm_hints().input == 0, 'camera must not request keyboard focus'
        assert connection.get_input_focus().focus.id == target_window.id
        assert native.get_geometry().width < root.get_geometry().width // 2
        visible = {window.id for window in root.query_tree().children
                   if window.get_attributes().map_state == X.IsViewable
                   and window.get_geometry().width > 16 and window.get_geometry().height > 16}
        assert visible == {native.id, target_window.id}, 'unexpected window above the original app'
        select_text()

        # Transparent corners must route to the original target, not the camera.
        corner = bubble.mapToGlobal(QPoint(1, 1))
        pointer(corner)
        assert root.query_pointer().child.id == target_window.id
        origin = bubble.pos()
        center = bubble.mapToGlobal(bubble.rect().center())
        pointer(center)
        assert root.query_pointer().child.id == native.id
        button(X.ButtonPress)
        pointer(center + QPoint(45, 25))
        button(X.ButtonRelease)
        assert (bubble.pos() - origin - QPoint(45, 25)).manhattanLength() <= 2
        assert connection.get_input_focus().focus.id == target_window.id
        select_text()

        # The captured app remains a normal window that can resize and accept
        # keyboard input. OBS has no replacement window above it.
        target.move(35, 35)
        target.resize(510, 360)
        settle()
        select_text()
        target.moveCursor(QTextCursor.End)
        key = connection.keysym_to_keycode(XK.string_to_keysym('x'))
        xtest.fake_input(connection, X.KeyPress, key)
        xtest.fake_input(connection, X.KeyRelease, key)
        settle()
        assert target.toPlainText().endswith('x'), 'keyboard input did not reach the original app'

        # Hidden and shown overlays must keep their native input regions in sync.
        dragged = bubble.pos()
        recorder.hide_bubble()
        settle()
        assert not native.shape_get_rectangles(shape.SK.Input).rectangles
        select_text()
        recorder.show_bubble()
        settle()
        assert (bubble.pos() - dragged).manhattanLength() <= 2, 'camera position changed on reattachment'
        assert native.shape_get_rectangles(shape.SK.Input).rectangles
        assert not bubble._input_passthrough
        select_text()
        if sys.argv[-1] == 'obs':
            for _ in range(30):
                if not bubble._frame.isNull():
                    break
                settle()
            assert not bubble._frame.isNull(), 'OBS did not deliver synthetic camera pixels'
        print('original window selection and camera drag passed')
    finally:
        target.close()
        case.tearDown()
        connection.close()


if __name__ == '__main__' and '--overlay-worker' in sys.argv:
    overlay_worker()
