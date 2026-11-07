#!/usr/bin/env python3
"""Record real Qt interactions on private Xvfb, using inert capture boundaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import time
from unittest.mock import MagicMock, patch

# Keep one narrow capability to encode only our private Xvfb desktop. The UI
# fixture continues blocking every application-triggered external process.
private_recorder_popen = subprocess.Popen

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--version', choices=('before', 'after'), required=True)
parser.add_argument('--source-root', type=Path)
parser.add_argument('--worker', action='store_true')
args = parser.parse_args()
if os.environ.get('UNTANGLE_SYNTHETIC_SANDBOX') != '1':
    raise SystemExit('Run through render-safe.sh; no host desktop access.')
args.output.mkdir(parents=True, exist_ok=True)
if not args.worker:
    xvfb = shutil.which('Xvfb')
    if not xvfb:
        raise SystemExit('Private Xvfb is required; no host-display fallback.')
    read_fd, write_fd = os.pipe()
    with (args.output / 'xvfb.log').open('w') as log:
        server = subprocess.Popen([xvfb, '-displayfd', str(write_fd), '-screen', '0',
            '1280x900x24', '-nolisten', 'tcp', '-ac'], pass_fds=(write_fd,), stdout=log, stderr=log)
        os.close(write_fd)
        try:
            if not select.select([read_fd], [], [], 10)[0]:
                raise RuntimeError('Private desktop startup timed out')
            number = os.read(read_fd, 32).decode().strip()
            if not number.isdigit():
                raise RuntimeError('Private desktop did not return a display number')
            env = dict(os.environ, DISPLAY=':' + number, UNTANGLE_COMPARISON_DISPLAY=':' + number,
                       QT_QPA_PLATFORM='xcb', QT_ACCESSIBILITY='0', LIBGL_ALWAYS_SOFTWARE='1')
            env.pop('WAYLAND_DISPLAY', None)
            env.pop('XAUTHORITY', None)
            command = [sys.executable, __file__, '--worker', '--output', str(args.output),
                       '--version', args.version]
            if args.source_root:
                command += ['--source-root', str(args.source_root)]
            result = subprocess.run(command, env=env, timeout=55)
            if result.returncode:
                raise SystemExit(result.returncode)
        finally:
            os.close(read_fd)
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
    raise SystemExit(0)

assert os.environ['DISPLAY'] == os.environ['UNTANGLE_COMPARISON_DISPLAY']
private_display = os.environ['DISPLAY']
from PySide6.QtWidgets import QApplication
qt = QApplication([])
assert qt.platformName() == 'xcb'
if args.source_root:
    sys.path.insert(0, str(args.source_root / 'src'))
    import untangle.app
from ux_session import Session, workflow
# Fixtures force offscreen environment defaults on import. The already-created
# QApplication remains bound to our private Xvfb; restore only that display.
os.environ.update(DISPLAY=private_display, QT_QPA_PLATFORM='xcb')
assert workflow.qt is qt
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget

session = Session(args.output)
w = session.window
w.configure_timer.stop()
w.preview.mode = 'screen'
w.mirror.setChecked(False)
w.resize(1100, 760)
w.move(90, 92)
scene = QWidget()
scene.setWindowFlags(Qt.FramelessWindowHint)
scene.setStyleSheet('background: #11151c; color: #f1f2f4;')
scene.setGeometry(0, 0, 1280, 900)
layout = QVBoxLayout(scene)
layout.setContentsMargins(32, 18, 32, 16)
heading = QLabel(args.version.upper() + ' · UNTANGLE RECORDING CONTROLS')
heading.setStyleSheet('font-size: 22px; font-weight: 600; color: #a5b4fc;')
caption = QLabel('Selected-window take: type in the shared window and keep Stop reachable.')
caption.setStyleSheet('font-size: 20px;')
layout.addWidget(heading)
layout.addWidget(caption)
editor = QTextEdit()
editor.setPlainText('Synthetic shared editor\n\nExplain the change. Pause for a correction. Resume, then review.\n\n'
                    'This is a private virtual desktop. No real user document is open.')
editor.setStyleSheet('background: #242a34; color: #f1f2f4; font-size: 22px; padding: 18px;')
layout.addWidget(editor, 1)
layout.addSpacing(135)
disclosure = QLabel('Real Qt interactions · synthetic capture / audio / saved-file events · no host devices or playback')
disclosure.setStyleSheet('font-size: 16px; color: #b6bdc7;')
layout.addWidget(disclosure)
scene.show()

with patch.object(w, 'configure'):
    w.set_mode('screen', configure=False)
    w.capture_kind.setCurrentIndex(w.capture_kind.findData('window'))
    w.capture_window.clear()
    w.capture_window.addItem('Synthetic shared editor', int(editor.winId()))
w.window_catalog.geometry = MagicMock(return_value=(0, 0, 1280, 900))
w.microphone.setCurrentIndex(w.microphone.findData(None))
w.selected_source = None
w.engine.stats.return_value = {'recording': True, 'encoder': 'synthetic'}
w.configuration_valid = True
w.configure_timer.stop()
w.lock_controls(True)
if hasattr(w, '_shortcut_available'):
    w._shortcut_available['F9'] = True  # Fixture event, never a host key grab.
w.hide()
w.begin_recording()
assert w.recording
if hasattr(w, 'recording_controls'):
    dock = w.recording_controls
    dock.move(dock.x(), dock.y() - 48)  # Keep the evidence disclosure unobscured.
w.engine.recording = True
w.started = time.monotonic()
workflow.qt.processEvents()
QTest.qWait(150)

errors = []
events = []
video_started = time.monotonic()
recorder_log = (args.output / 'ffmpeg.log').open('w')
record = private_recorder_popen(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
    '-f', 'x11grab', '-framerate', '15', '-video_size', '1280x900', '-i', os.environ['DISPLAY'],
    '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-movflags', '+faststart', str(args.output / 'raw.mp4')], stdin=subprocess.PIPE,
    stdout=recorder_log, stderr=recorder_log)


def update():
    w.update_recording_indicator()


def pause():
    caption.setText('Pause: the take freezes; the new controls show Resume and elapsed time.')
    if args.version == 'after':
        QTest.mouseClick(w.recording_controls.pause_button, Qt.LeftButton)
    else:
        w.toggle_pause()  # Represents the baseline shortcut; no native key grab.
    assert w.paused


def resume():
    caption.setText('Resume: keep working in the original shared window.')
    if args.version == 'after':
        QTest.mouseClick(w.recording_controls.pause_button, Qt.LeftButton)
    else:
        w.toggle_pause()
    assert not w.paused
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key_End, Qt.ControlModifier)
    QTest.keyClick(editor, Qt.Key_Return)
    QTest.keyClicks(editor, 'This text is typed through Qt during the take.')


def warning():
    caption.setText('Missing microphone samples: the new controls expose the input failure.')
    w.selected_source = 'synthetic-microphone'
    w.engine.audio_status.return_value = {'state': 'no_packets'}
    w.recording_error = 'Microphone samples stopped arriving. Review audio before sharing.'
    update()


def whole_screen():
    caption.setText('New synthetic whole-screen take: floating controls stay hidden while active.')
    w.recording = False
    w.selected_source = None
    w.recording_error = ''
    if hasattr(w, 'recording_controls'):
        w.recording_controls.finish()
    with patch.object(w, 'configure'):
        w.capture_kind.setCurrentIndex(w.capture_kind.findData('screen'))
    w.configure_timer.stop()
    w.configuration_valid = True
    w.begin_recording()
    assert w.recording
    w.started = time.monotonic()
    update()


def whole_pause():
    caption.setText('Whole-screen controls: pause before showing them.')
    if args.version == 'after':
        w.show_recording_controls()
        assert w.recording_controls.isVisible()
    else:
        w.toggle_pause()
    assert w.paused


def whole_resume():
    caption.setText('Resume: the new control window hides before capture continues.')
    if args.version == 'after':
        QTest.mouseClick(w.recording_controls.pause_button, Qt.LeftButton)
        assert not w.recording_controls.isVisible()
    else:
        w.toggle_pause()
    assert not w.paused


def saving():
    caption.setText('Stop and save: existing save path locks actions. Save events are synthetic.')
    with patch.object(workflow.glint.FinishWorker, 'start'):
        w.stop()
    assert w.busy
    w.show()
    w.raise_()


def saved():
    caption.setText('Saved take: review before sharing. The saved-file event is simulated.')
    w.recording = w.busy = w.paused = False
    w.engine.recording = False
    if hasattr(w, 'recording_controls'):
        w.recording_controls.finish()
    for button in (w.pause_button, w.restart_button, w.discard_button):
        button.hide()
    w.lock_controls(False)
    w.finish_save(session.case.path, '')
    assert w.review_saved_button.isVisible()


def run(action):
    try:
        action()
        update()
        events.append(dict(action=action.__name__, at=round(time.monotonic() - video_started, 3),
                           recording=w.recording, paused=w.paused, busy=w.busy))
        if record.poll() is not None:
            raise RuntimeError('Private desktop recording stopped early')
    except Exception as exc:
        errors.append(str(exc))
        workflow.qt.quit()


timer = QTimer()
timer.timeout.connect(update)
timer.start(100)
alarms = []
for milliseconds, action in ((3000, pause), (6000, resume), (9000, warning),
                             (13000, whole_screen), (16000, whole_pause),
                             (19000, whole_resume), (22000, saving), (25000, saved)):
    alarm = QTimer()
    alarm.setSingleShot(True)
    alarm.setTimerType(Qt.PreciseTimer)
    alarm.timeout.connect(lambda action=action: run(action))
    alarm.start(milliseconds)
    alarms.append(alarm)
end = QTimer()
end.setSingleShot(True)
end.setTimerType(Qt.PreciseTimer)
end.timeout.connect(workflow.qt.quit)
end.start(28000)
try:
    workflow.qt.exec()
finally:
    timer.stop()
    if record.poll() is None:
        record.communicate(b'q\n', timeout=10)
    recorder_log.close()
    scene.close()
    session.close()
if errors:
    raise RuntimeError('; '.join(errors))
if record.returncode:
    raise RuntimeError('FFmpeg failed; inspect ffmpeg.log')

source = Path(workflow.glint.__file__).resolve()
manifest = dict(version=args.version, platform='private Xvfb / xcb', events=events,
    app_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    renderer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    disclosure='Real Qt desktop recording; synthetic capture, microphone, file and save events. No host devices, playback, uploads or account operations.')
(args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
