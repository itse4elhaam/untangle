#!/usr/bin/env python3
"""Render integrated Loom widgets with synthetic data and inert Qt processes.

    .venv/bin/python scripts/render-loom-ui.py --output /tmp/untangle-loom-ui

No app entry point, real processes, media, capture, authentication or uploads.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

for _name in ('DISPLAY', 'WAYLAND_DISPLAY', 'RECIT_TEST_MIC_HARDWARE',
              'RECIT_HARDWARE_PRIVATE_DISPLAY', 'RECIT_NATIVE_PRIVATE_DISPLAY', 'RECIT_TEST_XVFB'):
    os.environ.pop(_name, None)
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_STYLE_OVERRIDE='Fusion',
                  QT_SCALE_FACTOR='1', QT_FONT_DPI='96')
REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / 'src'), str(REPO / 'tests')]

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QPoint, Qt, qVersion
from PySide6.QtGui import QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QPushButton, QScrollArea
import test_loom_workflow as workflow


def save(widget, output, name, overlay=None):
    image = widget.grab()
    if overlay is not None:
        painter = QPainter(image)
        offset = overlay.mapToGlobal(QPoint(0, 0)) - widget.mapToGlobal(QPoint(0, 0))
        painter.drawPixmap(offset, overlay.grab())
        painter.end()
    assert image.devicePixelRatio() == 1
    assert image.save(str(output / name)), name
    return {'width': image.width(), 'height': image.height(),
            'sha256': hashlib.sha256((output / name).read_bytes()).hexdigest()}


def render(case, scene, theme, size, output):
    w = case.window
    w.set_theme(theme)
    w.mirror.setChecked(False)  # Keep the synthetic source disclosure readable.
    w.configure_timer.stop()
    w.resize(*size)
    w.show()
    workflow.qt.processEvents()
    w.idle_audio.stop()
    w.microphone_meter.show_status(None)
    w.preview.mode = w.mode
    name = f'{scene}-{theme}-{size[0]}x{size[1]}.png'
    details = []
    if scene == 'library-uploaded':
        case.publish(isComplete=True, name='Synthetic Loom title')
        page = case.open_library()
        workflow.qt.processEvents()
        QTest.qWait(30)
        assert page.loom_title.isVisible()
        assert page.loom_title.text() == 'Loom title: Synthetic Loom title'
        assert page.loom_status.isVisible()
        assert page.loom_status.text() == 'Uploaded to Loom'
        for button in (page.open_loom, page.copy_loom, page.check_loom, page.forget_loom):
            assert button.isVisible() and button.isEnabled(), button.text()
        assert page.selected_loom_url() == workflow.URL
        assert page.player.source().isEmpty(), 'Library render must not load media'
        assert (w.width(), w.height()) == size, f'Unexpected actual widget size {w.size()}'
        return {**save(w, output, name),
                'upstream_title': page.loom_title.text(), 'upload_status': page.loom_status.text(),
                'saved_url': page.selected_loom_url(),
                'visible_link_actions': [button.text() for button in
                    (page.open_loom, page.copy_loom, page.check_loom, page.forget_loom)],
                'details': ['Production upload completion and library navigation using the existing synthetic fixture file. Upstream data.video.name/isComplete and saved link drive real library labels and visible enabled link actions. Thumbnail processes and media backends remain mocked; no media is loaded.']}
    if scene.startswith('recorder-'):
        if scene == 'recorder-uploading':
            process = case.begin_upload()
            process.feed('Upload')
            process.feed('ing 42%\r')
            w._upload_started -= 43
            w.update_upload_elapsed()
            details.append('Production upload/help/progress handlers driven with inert Qt process signals, split text chunks and synthetic 42% progress. Elapsed time pinned to 43 seconds.')
        elif scene == 'recorder-success':
            case.publish(isComplete=True, name='Synthetic Loom title')
            details.append('Production upload completion parses data.video.name/isComplete and saves a synthetic Loom URL in temporary metadata. Offscreen clipboard only.')
        elif scene == 'recorder-failure':
            process = case.begin_upload()
            process.finish('{"ok":false,"error":{"code":"AUTH_REQUIRED"}}', 77)
            details.append('Structured synthetic auth failure through production completion handler. No real account is inspected or changed.')
        else:
            raise ValueError(scene)
        w.upload_timer.stop()
        QTest.qWait(30)
        assert (w.width(), w.height()) == size, f'Unexpected actual widget size {w.size()}'
        panel = w.upload_panel
        panel_rect = panel.rect().translated(panel.mapTo(w, QPoint(0, 0)))
        assert w.rect().contains(panel_rect), f'Upload panel clipped: {panel_rect}'
        for button in panel.findChildren(QPushButton):
            if button.isVisible():
                rect = button.rect().translated(button.mapTo(w, QPoint(0, 0)))
                assert w.rect().contains(rect), f'Upload action clipped: {button.text()}'
        return {**save(w, output, name), 'details': details,
                'upload_heading': w.upload_heading.text(), 'upload_detail': w.upload_detail.text()}

    assert scene in ('sharing-connected', 'sharing-ai-settings')
    results = {}
    def probe(args, callback, **kwargs):
        assert args[0] == 'whoami', 'Renderer must never issue a mutation command'
        callback(workflow.ACCOUNT, 0, '')
    def execute(dialog):
        # Render the actual production modal within the actual recorder tree.
        dialog.resize(700, 700)
        dialog.move(w.mapToGlobal(QPoint((w.width() - 700) // 2, (w.height() - 700) // 2)))
        dialog.show()
        workflow.qt.processEvents()
        QTest.qWait(30)
        buttons = case.buttons(dialog)
        assert buttons['Reconnect Loom account ↗'].isHidden()
        assert not buttons['Disconnect TWG account…'].isHidden()
        assert 'Synthetic User' in w.cli_status.text()
        if scene == 'sharing-ai-settings':
            titles = next(item for item in dialog.findChildren(QCheckBox)
                          if item.text() == 'Let Loom generate titles when available')
            scroll = dialog.findChild(QScrollArea)
            scroll.ensureWidgetVisible(titles)
            titles.setChecked(False)
            QTest.qWait(30)
            results['title_preference_checked'] = titles.isChecked()
        # Qt's top-level grab excludes its separate modal. Composite both real
        # widget grabs at their actual relative positions, without painted UI.
        results.update(save(w, output, name, overlay=dialog))
        results['dialog_size'] = [dialog.width(), dialog.height()]
        results['text'] = [item.text() for item in dialog.findChildren(QLabel) if item.text()]
        dialog.hide()
        return QDialog.Rejected
    with patch.object(w, 'loom_probe', side_effect=probe), patch.object(QDialog, 'exec', new=execute):
        w.sharing_settings()
    results['details'] = ['Actual production Sharing dialog, synthetic successful whoami, temporary preferences. The connected account hides the connect action. AI preference is local; the UI discloses remote availability and import limitations.']
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/untangle-loom-ui'))
    parser.add_argument('--sizes', nargs='+', default=['960x760', '1120x840'])
    args = parser.parse_args()
    sizes = [tuple(map(int, value.split('x'))) for value in args.sizes]
    if any(width < 960 or height < 760 for width, height in sizes):
        parser.error('Use sizes at least 960x760.')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    workflow.qt.setQuitOnLastWindowClosed(False)
    workflow.qt.setStyle('Fusion')
    sources = [REPO / name for name in (
        'src/untangle/app.py', 'src/untangle/loom.py', 'src/untangle/upload_store.py',
        'src/untangle/theme.py', 'src/untangle/recordings.py',
        'tests/test_loom_workflow.py', 'tests/test_app.py',
        'scripts/render-loom-ui.py', 'scripts/render-ui.py')]
    manifest = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'qt': qVersion(), 'pyside': pyside_version,
        'platform': workflow.qt.platformName(), 'style': workflow.qt.style().objectName(),
        'source_sha256': {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sources},
        'disclosure': 'Actual production widgets, layouts, styles, signal handlers and local UploadStore. Offscreen Fusion at scale 1 and 96 DPI. AppChecks fixture is delegated, not subclassed. Only synthetic temporary files and INI preferences are used. OBS, devices, hotkeys, initialization, subprocess/account/network actions and media backends are mocked. QProcess is replaced with a QObject that emits real Qt signals and cannot run commands. Native Preview is replaced with the software synthetic frame from render-ui.py. No normal app launch, capture, playback, login, upload, installation or speech setting changes.',
        'images': {},
    }
    for size in sizes:
        for theme in ('light', 'dark'):
            for scene in ('recorder-uploading', 'recorder-success', 'recorder-failure',
                          'sharing-connected', 'sharing-ai-settings', 'library-uploaded'):
                case = workflow.LoomWorkflowChecks()
                try:
                    case.setUp()
                    name = f'{scene}-{theme}-{size[0]}x{size[1]}.png'
                    manifest['images'][name] = render(case, scene, theme, size, output)
                    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
                    print(name, flush=True)
                finally:
                    case.doCleanups()
    print(f'{len(manifest["images"])} actual Qt renders: {output / "manifest.json"}', flush=True)


if __name__ == '__main__':
    main()
