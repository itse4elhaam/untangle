#!/usr/bin/env python3
"""Render production Qt widgets safely; no OBS, desktop, devices, or playback.

Run from any directory, using the repository venv:
    .venv/bin/python scripts/render-ui.py --output docs/ui-baselines
Use --scenes recorder library while another contributor changes other views.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import faulthandler
import json
import os
from pathlib import Path
import sys
import time
import subprocess
from unittest.mock import MagicMock, patch

# Apply before importing Qt or any fixture. These cannot be overridden by callers.
for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'RECIT_TEST_MIC_HARDWARE',
             'RECIT_HARDWARE_PRIVATE_DISPLAY', 'RECIT_NATIVE_PRIVATE_DISPLAY', 'RECIT_TEST_XVFB'):
    os.environ.pop(name, None)
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_STYLE_OVERRIDE='Fusion',
                  QT_SCALE_FACTOR='1', QT_FONT_DPI='96', TZ='UTC')
time.tzset()
REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / 'src'), str(REPO / 'tests')]

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QRect, QRectF, Qt, QUrl, Signal, qVersion
from PySide6.QtGui import QColor, QFontInfo, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from untangle import app as glint
from untangle import recordings
from untangle import audio_check
from test_ui_clickthrough import ClearlineClickthrough, qt

faulthandler.enable()


def paint_scene(painter, rect, mode):
    """Only the unavailable capture content is painted, never app chrome."""
    painter.save()
    painter.translate(rect.topLeft())
    painter.scale(rect.width() / 640, rect.height() / 360)
    rect = QRect(0, 0, 640, 360)
    painter.fillRect(rect, QColor('#223349'))
    painter.setPen(QPen(QColor('#526780'), 1))
    for fraction in (1 / 3, 2 / 3):
        painter.drawLine(round(rect.width() * fraction), 0,
                         round(rect.width() * fraction), rect.height())
        painter.drawLine(0, round(rect.height() * fraction),
                         rect.width(), round(rect.height() * fraction))
    painter.setPen(QColor('#ffffff'))
    painter.drawText(rect.adjusted(35, 35, -35, -35), Qt.AlignCenter,
                     f'SYNTHETIC {mode.upper()} FRAME\nSoftware paint only\nNo camera or desktop capture')
    for text, area in (
        ('TL', QRect(8, 8, 28, 24)),
        ('TR', QRect(rect.width() - 36, 8, 28, 24)),
        ('BL', QRect(8, rect.height() - 32, 28, 24)),
        ('BR', QRect(rect.width() - 36, rect.height() - 32, 28, 24)),
    ):
        painter.fillRect(area, QColor('#f1cf63'))
        painter.setPen(QColor('#172231'))
        painter.drawText(area, Qt.AlignCenter, text)
    painter.setPen(QPen(QColor('#f1cf63'), 2))
    painter.drawRect(rect.adjusted(1, 1, -2, -2))
    painter.restore()


class SoftwarePreview(QWidget):
    """Replace the native OBS sink only, with the same production layout contract."""
    resized = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.mode = 'camera'
        self.setMinimumSize(320, 180)
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def paintEvent(self, event):
        painter = QPainter(self)
        w = self.window()
        width, height = w.output_dimensions()
        scale = min(self.width() / width, self.height() / height)
        target = QRectF((self.width() - width * scale) / 2,
                        (self.height() - height * scale) / 2,
                        width * scale, height * scale)
        painter.fillRect(self.rect(), QColor('#10151d'))
        painter.setClipRect(target)
        painter.translate(target.topLeft())
        painter.scale(scale, scale)
        painter.fillRect(QRectF(0, 0, width, height), Qt.black)
        # Source pixels are synthetic; crop/placement follows production helpers.
        source = QPixmap(1280, 720)
        source_painter = QPainter(source)
        paint_scene(source_painter, source.rect(), self.mode)
        source_painter.end()
        def draw_camera(destination, canvas_width, canvas_height, mode):
            from untangle.composition import camera_composition
            crop, (x, y, camera_scale) = camera_composition(
                canvas_width, canvas_height, source.width(), source.height(),
                mode=mode, camera_zoom=w.camera_zoom.value() / 100,
                framing=w.framing.currentData(), size=w.size.value() / 100,
                position=w.position.currentData())
            left, top, crop_width, crop_height = crop
            destination.save()
            destination.translate(x, y)
            destination.scale(camera_scale, camera_scale)
            if mode == 'screen' and w.shape.currentData() != 'square':
                mask = QPainterPath()
                rect = QRectF(0, 0, crop_width, crop_height)
                if w.shape.currentData() == 'circle':
                    mask.addEllipse(rect)
                else:
                    mask.addRoundedRect(rect, crop_width * .16, crop_height * .16)
                destination.setClipPath(mask, Qt.IntersectClip)
            if w.mirror.isChecked():
                destination.translate(crop_width, 0)
                destination.scale(-1, 1)
            destination.drawPixmap(QRectF(0, 0, crop_width, crop_height), camera_source,
                                   QRectF(left, top, crop_width, crop_height))
            destination.restore()

        camera_source = QPixmap(1280, 720)
        camera_painter = QPainter(camera_source)
        paint_scene(camera_painter, camera_source.rect(), 'camera')
        camera_painter.end()
        if self.mode == 'camera':
            draw_camera(painter, width, height, 'camera')
        else:
            from untangle.engine import screen_transform
            if w.camera.currentData() and w.uses_floating_camera():
                # XShm includes the physical bubble in the screen source. Paint
                # its synthetic equivalent before the screen transform too.
                source_painter = QPainter(source)
                draw_camera(source_painter, source.width(), source.height(), 'screen')
                source_painter.end()
            x, y, source_scale = screen_transform(
                width, height, source.width(), source.height(), 1, .5, .5,
                framing=w.framing.currentData())
            painter.drawPixmap(QRectF(x, y, source.width() * source_scale,
                                      source.height() * source_scale), source,
                               QRectF(source.rect()))
            if w.camera.currentData() and not w.uses_floating_camera():
                draw_camera(painter, width, height, 'screen')
        painter.end()

    def resizeEvent(self, event):
        self.resized.emit(self.width(), self.height())
        super().resizeEvent(event)


def thumbnail():
    pixmap = QPixmap(640, 360)
    painter = QPainter(pixmap)
    paint_scene(painter, pixmap.rect(), 'library fixture')
    painter.end()
    return pixmap


def silent_player_type():
    """No multimedia backend is needed to render a paused/empty review panel.

    Qt 6.11's offscreen media-player construction intermittently segfaulted even
    before play(), including in fresh processes. Keep its data/signals mocked;
    every surrounding production widget still renders and receives real input.
    """
    def create(*args, **kwargs):
        player = MagicMock(spec=QMediaPlayer)
        player.source.return_value = QUrl()
        player.setSource.side_effect = lambda url: setattr(player.source, 'return_value', url)
        player.playbackState.return_value = QMediaPlayer.StoppedState
        player.mediaStatus.return_value = QMediaPlayer.NoMedia
        player.position.return_value = 0
        player.duration.return_value = 0
        player.isSeekable.return_value = False
        return player
    player_type = MagicMock(side_effect=create)
    for name in ('PlayingState', 'PausedState', 'StoppedState', 'EndOfMedia', 'NoMedia'):
        setattr(player_type, name, getattr(QMediaPlayer, name))
    return player_type


def wait(predicate, message):
    deadline = time.monotonic() + 4
    while not predicate() and time.monotonic() < deadline:
        qt.processEvents()
        time.sleep(.005)  # Release the GIL for the mocked audio worker callback.
    if not predicate():
        raise AssertionError(message)
    qt.processEvents()


def populate(case):
    for index, name in enumerate(('Project walkthrough.mp4', 'Camera explanation.mkv', 'Short take.mp4')):
        path = case.root / name
        path.write_bytes(b'Synthetic metadata-only fixture. Not a video.')
        # Fixed metadata makes names/dates reproducible without real media decode.
        os.utime(path, (946684800 + index * 60, 946684800 + index * 60))


def prepare(case, scene):
    w = case.window
    disclosure = []
    if scene.startswith('library'):
        if scene == 'library-populated':
            populate(case)
        case.click(w.library_button)
        page = w.recordings
        if scene == 'library-populated':
            pixmap = thumbnail()
            for index in range(page.files.count()):
                item = page.files.item(index)
                page.thumbnail_cache[item.data(Qt.UserRole + 1)] = pixmap
                item.setIcon(QIcon(pixmap))
            item = page.files.item(0)
            QTest.mouseClick(page.files.viewport(), Qt.LeftButton,
                             pos=page.files.visualItemRect(item).center())
            assert page.player.source().isEmpty()
            disclosure.append('Metadata-only MP4/MKV placeholders, fixed year-2000 mtimes; injected software thumbnail cache; no media decoding or playback.')
    elif scene.startswith('screen-canvas-') or scene.startswith('canvas-') or scene in ('camera-zoom', 'camera-reset', 'framing-fit', 'framing-fill'):
        screen_canvas = scene.startswith('screen-canvas-')
        case.click(w.screen_button if screen_canvas else w.camera_button)
        QTest.qWait(220)
        canvas = (scene.removeprefix('screen-canvas-').removesuffix('-fill') if screen_canvas else
                  scene.removeprefix('canvas-') if scene.startswith('canvas-') else 'portrait')
        case.choose_output(w.canvas, canvas)
        if screen_canvas and scene.endswith('-fill'):
            case.choose(w.framing, 'fill')
        if scene.startswith('framing-'):
            case.choose(w.framing, scene.removeprefix('framing-'))
        if scene in ('camera-zoom', 'camera-reset'):
            case.click(w.camera_zoom)
            QTest.keyClick(w.camera_zoom, Qt.Key_End)
            QTest.qWait(220)
            if scene == 'camera-reset':
                case.click(w.camera_zoom_reset)
                QTest.qWait(220)
        disclosure.append(f'Production canvas {w.canvas.currentData()}, output {w.output_dimensions()}, '
                          f'framing {w.framing.currentData()}, camera zoom {w.camera_zoom.value()}%. '
                          'Synthetic 1280×720 source cropped and placed with production composition helpers; '
                          'output is letterboxed within the real preview widget.')
    elif scene == 'advanced':
        case.click(w.screen_button)
        QTest.qWait(220)
        w.controls_panel.ensureWidgetVisible(w.setup_sections[0])
        QTest.qWait(20)
        case.click(w.setup_sections[0])
        disclosure.append('More options opened by QTest; production disclosure automatically scrolls its body into view.')
    elif scene == 'expanded':
        case.click(w.focus_button)
    elif scene == 'audio-silence':
        from untangle.audio_check import AudioSample
        from test_audio_check import feed
        sample = AudioSample(MagicMock(), 123)
        feed(sample, muted=True)
        w.engine.begin_audio_check.return_value = sample
        w.audio_devices.restore.return_value = True
        case.click(w.audio_check_button)
        dialog = w.audio_check_dialog
        case.click(dialog.record)
        wait(lambda: dialog.capturing and dialog.worker is None, 'Synthetic check did not start')
        case.click(dialog.stop)
        wait(lambda: dialog.worker is None and 'silence' in dialog.status.text().lower(),
             'Production audio-check silence result did not arrive')
        assert not dialog.capturing
        disclosure.append('Real AudioSample receives synthetic zero-valued float planes through the existing test feed helper; production stop/validation handlers generate silence guidance. No input device is opened.')
    elif scene in ('recording', 'paused', 'saving', 'error'):
        # Drive production state transitions with a mocked engine. No start timer
        # or FinishWorker is allowed to initiate device capture or media work.
        case.choose(w.microphone, None)
        w.engine.audio_status.return_value = {'state': 'off', 'peak_db': float('-inf')}
        case.click(w.record_button)
        w.count_timer.stop()
        w.counting = False
        w.selected_source = None
        w.engine.stats.return_value = {'recording': True, 'encoder': 'ffmpeg_vaapi'}
        w.begin_recording()
        assert w.recording
        w.engine.recording = True
        w.started = time.monotonic() - 83
        w.tick()
        if scene == 'paused':
            case.click(w.pause_button)
            w.tick()
        elif scene in ('saving', 'error'):
            with patch.object(glint.FinishWorker, 'start'):
                case.click(w.record_button)
            if scene == 'error':
                path = case.root / 'Synthetic original.mkv'
                path.write_bytes(b'Synthetic recoverable source')
                w.engine.recording = False
                w.stopped(str(path), 'Synthetic encoder failure')
        disclosure.append('Microphone selected off; mocked audio status off and selected_source None agree. Production begin_recording/tick, Pause, Stop and stopped handlers with a mocked engine and suspended FinishWorker.start. No encoder or recording runs; elapsed time injected as 1:23. Error details are a synthetic engine event.')
    else:
        case.click(getattr(w, scene + '_button'))
        QTest.qWait(220)
    w.preview.mode = w.mode
    w.preview.update()
    qt.processEvents()
    return disclosure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/untangle-ui-render'))
    parser.add_argument('--scenes', nargs='+', choices=('recorder', 'library', 'audio', 'advanced', 'states', 'expanded', 'canvas'),
                        default=['recorder', 'library', 'audio', 'advanced', 'states', 'expanded', 'canvas'])
    parser.add_argument('--single-scene', help=argparse.SUPPRESS)
    parser.add_argument('--single-size', help=argparse.SUPPRESS)
    parser.add_argument('--single-theme', choices=('light', 'dark'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.single_scene:
        faulthandler.dump_traceback_later(15)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    qt.setQuitOnLastWindowClosed(False)
    qt.setStyle('Fusion')
    source_paths = [REPO / 'src/untangle' / name for name in
                    ('app.py', 'engine.py', 'composition.py', 'theme.py', 'audio_check.py', 'recordings.py', 'microphone_meter.py')]
    source_paths += [Path(__file__).resolve(), REPO / 'tests/test_ui_clickthrough.py']
    source_paths += sorted((REPO / 'assets').rglob('*.svg'))
    source_paths += sorted((REPO / 'assets/fonts').glob('*.ttf'))
    manifest_path = output / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest.update({
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'command': '.venv/bin/python scripts/render-ui.py --output docs/ui-baselines',
        'qt': qVersion(), 'pyside': pyside_version,
        'platform': qt.platformName(), 'style': qt.style().objectName(),
        'scale_factor': 1, 'font_dpi': 96,
        'timezone': 'UTC',
        'screen_geometry': [[screen.geometry().width(), screen.geometry().height()]
                            for screen in qt.screens()],
        'disclosure': 'Actual production Qt widgets and styles. Reuses ClearlineClickthrough hardware-mocked fixture. Offscreen Fusion; temporary INI preferences and synthetic files only. Native OBS preview replaced by a software QWidget with four edge markers and an explicit synthetic label. Engine, device enumeration, audio devices, hotkeys, initialization and the non-widget QMediaPlayer backend are mocked. Native QMediaPlayer construction intermittently segfaulted in Qt 6.11 offscreen before playback, including with isolated processes; this renderer replaces that backend explicitly. No normal app launch, OBS, hardware, desktop/profile/settings changes, login or uploads. Thumbnail decoding is disabled. These are visual evidence, not a claim of native OBS/media backend fidelity or pixel-equality tests.',
        'images': manifest.get('images', {}),
    })
    scenes = []
    if 'recorder' in args.scenes:
        scenes += [(scene, size) for scene in ('screen', 'camera') for size in ((1120, 840), (960, 760))]
    if 'library' in args.scenes:
        scenes += [(scene, size) for scene in ('library-populated', 'library-empty') for size in ((1120, 840), (960, 760))]
    for group, names in (
        ('audio', ('audio-silence',)), ('advanced', ('advanced',)),
        ('expanded', ('expanded',)), ('states', ('recording', 'paused', 'saving', 'error')),
        ('canvas', ('canvas-landscape', 'canvas-portrait', 'canvas-square', 'canvas-portrait45',
                    'camera-zoom', 'camera-reset', 'framing-fit', 'framing-fill',
                    'screen-canvas-portrait', 'screen-canvas-portrait-fill', 'screen-canvas-square')),
    ):
        if group in args.scenes:
            scenes += [(scene, size) for scene in names
                       for size in (((960, 760), (1120, 840)) if group == 'canvas' else ((960, 760),))]
    if not args.single_scene:
        # Qt native surfaces and media widgets should not survive into the next
        # baseline. A fresh offscreen process per image also resets global style.
        for scene, size in scenes:
            for theme in ('light', 'dark'):
                subprocess.run([
                    sys.executable, str(Path(__file__).resolve()), '--output', str(output),
                    '--single-scene', scene, '--single-size', f'{size[0]}x{size[1]}',
                    '--single-theme', theme,
                ], check=True, timeout=25)
        print(f'Render matrix completed: {output / "manifest.json"}', flush=True)
        return
    scenes = [(args.single_scene, tuple(map(int, args.single_size.split('x'))))]
    with ExitStack() as stack:
        stack.enter_context(patch.object(glint, 'Preview', SoftwarePreview))
        stack.enter_context(patch('untangle.engine.Engine', side_effect=AssertionError('Native engine forbidden in renderer')))
        stack.enter_context(patch.object(recordings, 'QMediaPlayer', silent_player_type()))
        stack.enter_context(patch.object(audio_check, 'QMediaPlayer', silent_player_type()))
        stack.enter_context(patch.object(recordings.shutil, 'which', return_value=None))
        for scene, size in scenes:
            for theme in (args.single_theme,):
                case = ClearlineClickthrough()
                try:
                    case.setUp()
                    w = case.window
                    w.timer.stop()
                    w.resize(*size)
                    case.choose(w.theme_choice, theme)
                    wait(lambda: not w.audio_worker or not w.audio_worker.isRunning(), 'Fixture audio worker still running')
                    w.idle_audio.stop()
                    details = prepare(case, scene)
                    QTest.qWait(30)
                    assert (w.width(), w.height()) == size, f'Unexpected render size {w.size()}'
                    name = f'{scene}-{theme}-{size[0]}x{size[1]}.png'
                    image = w.grab()
                    assert image.devicePixelRatio() == 1
                    assert image.save(str(output / name)), f'Could not save {name}'
                    font = QFontInfo(w.font())
                    manifest['images'][name] = {
                        'scene': scene, 'theme': theme, 'width': image.width(), 'height': image.height(),
                        'font_family': font.family(), 'font_pixel_size': font.pixelSize(),
                        'source_sha256': {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
                                          for path in source_paths},
                        'png_sha256': hashlib.sha256((output / name).read_bytes()).hexdigest(),
                        'details': details,
                    }
                    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
                    print(name, flush=True)
                finally:
                    case.doCleanups()
    print(f'{len(manifest["images"])} images recorded in {manifest_path}', flush=True)


if __name__ == '__main__':
    main()
