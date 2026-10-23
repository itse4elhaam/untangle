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
                path = args.output / f'{name}-{theme}.png'
                assert widget.grab().save(str(path))
                manifest['images'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            save(w, 'recorder')
            w.sidebar_button.setChecked(False)
            workflow.qt.processEvents()
            save(w, 'collapsed')
            w.sidebar_button.setChecked(True)
            with patch.object(workflow.glint, 'local_title_capability', return_value=(True, '')):
                w.open_settings()
            workflow.qt.processEvents()
            save(w.settings_dialog, 'settings')
            w.settings_dialog.accept()
            page = case.open_library()
            workflow.qt.processEvents()
            save(w, 'library')
            assert page.player.source().isEmpty()
        finally:
            case.doCleanups()
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(args.output)


if __name__ == '__main__':
    main()
