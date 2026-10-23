#!/usr/bin/env python3
"""Render the real naming dialog with synthetic data; no app or capture launch."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ.pop('DISPLAY', None)
os.environ.pop('WAYLAND_DISPLAY', None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from untangle.naming_dialog import RecordingNameDialog
from untangle.theme import load_fonts, stylesheet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/untangle-naming-ui'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    qt = QApplication([])
    qt.setStyle('Fusion')
    load_fonts(qt)
    manifest = {'disclosure': 'Actual Qt dialog, synthetic path, no filesystem rename or app launch.',
                'sources': {}, 'images': {}}
    for name in ('src/untangle/naming_dialog.py', 'src/untangle/naming.py',
                 'src/untangle/theme.py', 'scripts/render-naming-ui.py'):
        manifest['sources'][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    for theme in ('light', 'dark'):
        qt.setStyleSheet(stylesheet(theme))
        for scene in ('finished', 'rename', 'error'):
            def rename(title):
                raise PermissionError('The folder is read-only. Choose Cancel to keep the current name.')
            dialog = RecordingNameDialog(None,
                Path('Project walkthrough - 2026-10-23 at 12.30.mp4'), rename,
                new_recording=scene == 'finished')
            dialog.show()
            qt.processEvents()
            if scene == 'error':
                dialog.name_edit.setText('Product demo')
                dialog.accept()
                qt.processEvents()
            name = f'{scene}-{theme}.png'
            assert dialog.grab().save(str(args.output / name))
            manifest['images'][name] = hashlib.sha256((args.output / name).read_bytes()).hexdigest()
            dialog.reject()
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(args.output)


if __name__ == '__main__':
    main()
