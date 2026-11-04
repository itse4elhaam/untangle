#!/usr/bin/env python3
"""Render real recorder/Settings widgets with synthetic capture and inert processes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'RECIT_TEST_MIC_HARDWARE',
             'RECIT_HARDWARE_PRIVATE_DISPLAY', 'RECIT_NATIVE_PRIVATE_DISPLAY', 'RECIT_TEST_XVFB'):
    os.environ.pop(name, None)
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_SCALE_FACTOR='1', QT_FONT_DPI='96')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
from PySide6.QtTest import QTest
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication, QScrollArea
from PySide6.QtGui import QIcon
import test_loom_workflow as workflow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/untangle-settings-ui'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    workflow.qt.setStyle('Fusion')
    manifest = {'disclosure': 'Actual Qt UI. Capture, media, subprocesses, account calls, transcription and inference mocked; synthetic files/preferences only.',
                'source_sha256': {}, 'images': {}}
    for name in ('src/untangle/app.py', 'src/untangle/theme.py', 'src/untangle/recordings.py',
                 'src/untangle/camera_framing.py', 'src/untangle/drive_help.py',
                 'scripts/render-settings-ui.py'):
        manifest['source_sha256'][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    for theme in ('light', 'dark'):
        case = workflow.LoomWorkflowChecks()
        try:
            case.setUp()
            w = case.window
            w.set_theme(theme)
            w.mirror.setChecked(False)
            w.configure_timer.stop()
            w.resize(960, 760)
            w.show()
            w.timer.stop()
            w.idle_audio.stop()
            w.microphone_meter.show_status(None)
            workflow.qt.processEvents()
            QTest.qWait(20)
            def save(widget, name):
                workflow.qt.processEvents()
                QTest.qWait(40)
                path = args.output / f'{name}-{theme}.png'
                assert widget.grab().save(str(path))
                manifest['images'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            save(w, 'recorder')
            w.details_toggle.setChecked(True)
            workflow.qt.processEvents()
            save(w, 'details-expanded')
            w.details_toggle.setChecked(False)
            w.camera_zoom.setValue(180)
            w.camera_offset_dragged(.25, -.15)
            w.set_mode('screen')
            w.configure_timer.stop()
            w.configure()
            w.idle_audio.stop()
            w.preview.mode = 'screen'
            workflow.qt.processEvents()
            save(w, 'screen')
            w.set_mode('camera')
            w.configure_timer.stop()
            w.configure()
            w.idle_audio.stop()
            w.preview.mode = 'camera'
            w.sidebar_button.setChecked(False)
            workflow.qt.processEvents()
            save(w, 'collapsed')
            w.sidebar_button.setChecked(True)
            with patch.object(workflow.glint, 'local_title_capability', return_value=(True, '')):
                w.open_settings()
            workflow.qt.processEvents()
            save(w.settings_dialog, 'settings')
            scroll = w.settings_dialog.findChild(QScrollArea)
            scroll.ensureWidgetVisible(w.audio_check_button, 0, 60)
            workflow.qt.processEvents()
            save(w.settings_dialog, 'settings-audio')
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
            workflow.qt.processEvents()
            save(w.settings_dialog, 'settings-crop')
            w.settings_dialog.accept()
            from untangle.drive_help import show_drive_setup_guide
            def capture_guide():
                dialog = QApplication.activeModalWidget()
                assert dialog is not None
                save(dialog, 'drive-guide')
                dialog.accept()
            QTimer.singleShot(40, capture_guide)
            show_drive_setup_guide(w)
            for index, name in enumerate(('Synthetic project review.mp4',
                    'Long synthetic walkthrough with camera and screen settings.mkv')):
                video = case.root / name
                video.write_bytes(b'Synthetic metadata, not playable media.')
                os.utime(video, (1700000000 + index, 1700000000 + index))
            page = case.open_library()
            workflow.qt.processEvents()
            thumbnail = workflow.render_helpers.thumbnail()
            for index in range(page.files.count()):
                page.files.item(index).setIcon(QIcon(thumbnail))
            save(w, 'library')
            assert page.player.source().isEmpty()
        finally:
            case.doCleanups()
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(args.output)


if __name__ == '__main__':
    main()
