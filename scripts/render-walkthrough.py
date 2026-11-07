#!/usr/bin/env python3
"""Capture a captioned, synthetic Qt walkthrough for before/after review.

No recording takes place. Input goes through production widgets and handlers;
the same inert boundaries as ux_session apply. A video builder holds these
observed steps long enough to read, rather than claiming a real-time capture.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

from ux_session import Session, workflow, ROOT
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtTest import QTest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', choices=('before', 'after'), required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = Session(args.output)
    w = session.window
    manifest = dict(version=args.version, source_sha256={}, steps=[],
                    disclosure='Captioned step captures of production Qt widgets. Synthetic camera/screen, files, engine, audio, playback, account and process boundaries. No native encoding, host capture, playback or upload. Elapsed time and save result are injected fixture events.')
    for name in ('app.py', 'recordings.py', 'theme.py'):
        manifest['source_sha256'][name] = hashlib.sha256((ROOT / 'src/untangle' / name).read_bytes()).hexdigest()

    def click(widget):
        QTest.mouseClick(widget, Qt.LeftButton)
        QTest.qWait(80)

    def capture(name, caption, seconds=5):
        workflow.qt.processEvents()
        QTest.qWait(50)
        image = w.grab()
        assert image.width() == 960 and image.height() == 760
        assert image.save(str(args.output / f'{name}-window.png'))
        frame = QPixmap(960, 850)
        frame.fill(QColor('#11151c'))
        painter = QPainter(frame)
        painter.setPen(QColor('#aabcf7'))
        painter.setFont(QFont('DejaVu Sans', 10, QFont.Bold))
        painter.drawText(20, 20, args.version.upper() + '  ·  UNTANGLE UI / UX')
        painter.setPen(QColor('#f1f2f4'))
        painter.setFont(QFont('DejaVu Sans', 14))
        painter.drawText(20, 47, caption)
        painter.drawPixmap(0, 60, image)
        painter.setPen(QColor('#b6bdc7'))
        painter.setFont(QFont('DejaVu Sans', 9))
        painter.drawText(20, 841, 'Actual Qt widgets · synthetic capture, audio, files and services · captioned task steps')
        painter.end()
        filename = f'{name}.png'
        assert frame.save(str(args.output / filename))
        manifest['steps'].append(dict(id=name, image=filename, seconds=seconds,
                                     caption=caption, library=w.in_library(),
                                     recording=w.recording, paused=w.paused))

    try:
        for index, name in enumerate(('Project walkthrough.mp4', 'Camera explanation.mp4', 'Design review.mp4')):
            path = session.case.root / name
            path.write_bytes(b'Synthetic metadata only, not playable video.')
            os.utime(path, (946684800 + index * 60, 946684800 + index * 60))
        os.utime(session.case.path, (946684800 + 180, 946684800 + 180))
        w.set_mode('camera', configure=False)
        w.mirror.setChecked(False)
        w.configure()
        w.idle_audio.stop()
        w.preview.mode = 'camera'
        capture('01-setup', 'Set up the camera, microphone and canvas. Find the recording action.')
        click(w.sidebar_button)
        capture('02-controls-hidden', 'Hide setup controls. Recording actions and navigation should stay reachable.')
        click(w.sidebar_button)
        click(w.library_button)
        page = w.recordings
        pixmap = workflow.render_helpers.thumbnail()
        from PySide6.QtGui import QIcon
        for index in range(page.files.count()):
            item = page.files.item(index)
            page.thumbnail_cache[item.data(Qt.UserRole + 1)] = pixmap
            item.setIcon(QIcon(pixmap))
        item = page.files.item(0)
        QTest.mouseClick(page.files.viewport(), Qt.LeftButton,
                         pos=page.files.visualItemRect(item).center())
        assert page.player.source().isEmpty()
        capture('03-review', 'Select a take. Read its title and review it before choosing a destination.', 6)
        click(page.search)
        QTest.keyClicks(page.search, 'Project')
        capture('04-search', 'Find a take by name. Selecting a file never starts playback.')
        click(page.back)
        w.microphone.setCurrentIndex(w.microphone.findData(None))
        w.selected_source = None
        w.audio_devices.prepare.return_value = None
        w.configuration_valid = True
        w.engine.stats.return_value = {'recording': True, 'encoder': 'ffmpeg_vaapi'}
        w.lock_controls(True)
        w.begin_recording()
        w.engine.recording = True
        w.started = time.monotonic() - 83
        w.tick()
        capture('05-recording', 'During a take: find the timer, pause and Stop and save.', 6)
        click(w.pause_button)
        w.tick()
        capture('06-paused', 'Pause the take. The timer must freeze and the action must say Resume.')
        click(w.pause_button)
        w.tick()
        click(w.library_button)
        capture('07-browse-during-take', 'Try Recordings during a take. Capture must continue and Stop must stay reachable.', 6)
        with patch.object(workflow.glint.FinishWorker, 'start'):
            click(w.record_button)
        capture('08-saving', 'Stop and save returns attention to the take. This save operation is mocked.')
        w.recording = w.paused = False
        w.engine.recording = False
        w.pause_button.hide()
        w.restart_button.hide()
        w.discard_button.hide()
        w.finish_save(session.case.path, '')
        capture('09-saved', 'A saved take has an explicit review action. The local original stays available.')
        click(w.review_saved_button)
        w.set_theme('light')
        capture('10-light', 'The same review workflow in light mode. Sharing remains a separate action.')
        (args.output / 'walkthrough.json').write_text(json.dumps(manifest, indent=2) + '\n')
    finally:
        session.close()


if __name__ == '__main__':
    main()
