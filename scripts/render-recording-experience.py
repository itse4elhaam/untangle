#!/usr/bin/env python3
"""Observed production Qt states over a synthetic editor; no capture or encoding."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import MagicMock, patch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--version', choices=('before', 'after'), required=True)
parser.add_argument('--source-root', type=Path)
parser.add_argument('--theme', choices=('light', 'dark'), default='dark')
args = parser.parse_args()
if os.environ.get('UNTANGLE_SYNTHETIC_SANDBOX') != '1':
    raise SystemExit('Use render-safe.sh; synthetic sandbox required.')
if args.source_root:
    sys.path.insert(0, str(args.source_root / 'src'))
    import untangle.app  # Pin the baseline package before current fixture imports.
from ux_session import Session, workflow, ROOT
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QTextEdit

args.output.mkdir(parents=True, exist_ok=True)
session = Session(args.output, theme=args.theme)
w = session.window
editor = QTextEdit()
editor.setReadOnly(False)
editor.setPlainText('Design review — synthetic shared window\n\n'
                    '1. Explain the change\n2. Show the important interaction\n3. Pause for a correction\n4. Stop, review, then share\n\n'
                    'This editor is a synthetic target, not a real user document.\n'
                    'No host desktop, camera or microphone is accessed.')
editor.resize(820, 430)
editor.show()
manifest = dict(version=args.version, steps=[], disclosure=
    'Captioned production Qt widget captures composed over a synthetic QTextEdit. '
    'Engine, time, audio, save and device events are fixtures. No native encoding, host capture or playback. '
    'Separate private-Xvfb tests verify native input routing; this video does not verify saved pixels or audio.')
for name in ('app.py', 'theme.py', 'recording_controls.py'):
    source = (args.source_root or ROOT) / 'src/untangle' / name
    if source.exists():
        manifest.setdefault('source_sha256', {})[name] = hashlib.sha256(source.read_bytes()).hexdigest()


def capture(name, caption, seconds=6, main=False):
    workflow.qt.processEvents()
    QTest.qWait(40)
    frame = QPixmap(960, 850)
    frame.fill(QColor('#11151c'))
    painter = QPainter(frame)
    painter.setPen(QColor('#aabcf7'))
    painter.setFont(QFont('DejaVu Sans', 10, QFont.Bold))
    painter.drawText(22, 25, args.version.upper() + ' · DURING SCREEN RECORDING')
    painter.setPen(QColor('#f1f2f4'))
    painter.setFont(QFont('DejaVu Sans', 12))
    painter.drawText(22, 56, caption)
    if main:
        painter.drawPixmap(0, 75, w.grab().scaled(900, 710, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    else:
        painter.drawPixmap(70, 110, editor.grab())
        dock = getattr(w, 'recording_controls', None)
        if dock is not None and dock.isVisible():
            painter.drawPixmap((960 - dock.width()) // 2, 630, dock.grab())
    painter.setPen(QColor('#b6bdc7'))
    painter.setFont(QFont('DejaVu Sans', 9))
    painter.drawText(22, 815, 'Actual Qt widgets · synthetic editor, engine, time, audio and save events')
    painter.drawText(22, 838, 'Not a saved-video quality or host-hardware test. No capture, playback or upload.')
    painter.end()
    filename = name + '.png'
    assert frame.save(str(args.output / filename))
    manifest['steps'].append(dict(id=name, image=filename, seconds=seconds, caption=caption,
                                 recording=w.recording, paused=w.paused, busy=w.busy))

try:
    with patch.object(w, 'configure'):
        w.set_mode('screen', configure=False)
        w.capture_kind.setCurrentIndex(w.capture_kind.findData('window'))
        w.capture_window.clear()
        w.capture_window.addItem('Synthetic design review', 42)
    w.preview.mode = 'screen'
    w.mirror.setChecked(False)
    w.window_catalog.geometry = MagicMock(return_value=(0, 0, 820, 430))
    w.microphone.setCurrentIndex(w.microphone.findData(None))
    w.selected_source = None
    w.audio_devices.prepare.return_value = None
    w.configuration_valid = True
    w.engine.stats.return_value = {'recording': True, 'encoder': 'ffmpeg_vaapi'}
    w.lock_controls(True)
    if hasattr(w, '_shortcut_available'):
        w._shortcut_available['F9'] = True  # Synthetic registered shortcut, no host grab.
    w.hide()
    w.begin_recording()
    assert w.recording
    w.engine.recording = True
    w.started = time.monotonic() - 83
    w.tick()
    capture('01-window-take', 'Selected-window take: keep the editor visible; find time, pause and Stop.')
    if args.version == 'after':
        assert w.recording_controls.isVisible()
        QTest.mouseClick(w.recording_controls.pause_button, Qt.LeftButton)
    else:
        w.toggle_pause()  # Fixture represents the existing global shortcut.
    capture('02-paused', 'Pause: the clock freezes; Resume remains explicit.')
    w.toggle_pause()
    w.selected_source = 'synthetic-microphone'
    w.engine.audio_status.return_value = {'state': 'no_packets', 'source': 'synthetic-microphone'}
    w._audio_warning_since = ('no_packets', time.monotonic() - 6)
    w.tick()
    capture('03-input-warning', 'Missing microphone samples should reach controls while Untangle is hidden.', 7)
    w.selected_source = None
    w.recording_error = ''
    # A separate synthetic take exercises whole-screen policy, not a live
    # capture-source mutation. Existing capture inputs remain locked in takes.
    w.recording = False
    w.engine.recording = False
    if hasattr(w, 'recording_controls'):
        w.recording_controls.finish()
    with patch.object(w, 'configure'):
        w.capture_kind.setCurrentIndex(w.capture_kind.findData('screen'))
    w.configure_timer.stop()
    w.configuration_valid = True
    w.begin_recording()
    assert w.recording
    w.engine.recording = True
    w.started = time.monotonic() - 12
    w.tick()
    capture('04-full-screen', 'Whole-screen take: new floating controls stay hidden during active capture.')
    if args.version == 'after':
        w.show_recording_controls()
        assert w.recording_controls.isVisible()
    else:
        w.toggle_pause()
    assert w.paused
    capture('05-full-screen-paused', 'Whole-screen controls: pause first, then show time, Resume and Stop.')
    w.toggle_pause()
    assert w.recording and not w.paused
    capture('06-resumed-clean', 'Resume hides the new control window before capture continues.')
    with patch.object(workflow.glint.FinishWorker, 'start'):
        w.stop()
    assert w.busy and w.recording
    w.update_recording_indicator()
    capture('07-saving', 'Stop uses the existing save/recovery path; controls cannot start another action.', main=True)
    (args.output / 'walkthrough.json').write_text(json.dumps(manifest, indent=2) + '\n')
finally:
    editor.close()
    session.close()
