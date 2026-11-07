#!/usr/bin/env python3
"""A bounded observation/action interface for synthetic production Qt widgets.

Use render-safe.sh OUTPUT session --actions FILE, or send JSON lines on stdin.
All media, capture, devices and external processes use the existing inert fixture.
"""
import argparse
import json
import os
from pathlib import Path
import select
import sys
import time

if os.environ.get('UNTANGLE_SYNTHETIC_SANDBOX') != '1':
    raise SystemExit('Use scripts/render-safe.sh; synthetic sandbox required.')

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QLineEdit
import test_loom_workflow as workflow


class Session:
    def __init__(self, output, theme='dark'):
        self.output = output
        self.case = workflow.LoomWorkflowChecks()
        self.case.setUp()
        self.window = w = self.case.window
        self.started = time.monotonic()
        self.steps = []
        workflow.qt.setStyle('Fusion')
        w.set_theme(theme)
        w.timer.stop()
        w.configure_timer.stop()
        w.idle_audio.stop()
        w.resize(960, 760)
        w.show()
        workflow.qt.processEvents()

    def controls(self):
        w = self.window
        result = {name: getattr(w, name) for name in (
            'record_button', 'pause_button', 'library_button', 'sidebar_button',
            'camera_button', 'screen_button', 'settings_button', 'camera',
            'microphone', 'canvas', 'details_toggle', 'review_saved_button')}
        if w.recordings is not None:
            result.update({'library.' + name: getattr(w.recordings, name) for name in
                           ('back', 'search', 'files', 'toggle', 'copy', 'upload')})
        return result

    def observe(self):
        workflow.qt.processEvents()
        image_path = self.output / f'step-{len(self.steps):02d}.png'
        if not self.window.grab().save(str(image_path)):
            raise RuntimeError('Screenshot failed')
        controls = []
        for name, widget in self.controls().items():
            if not widget.isVisible():
                continue
            point = widget.mapTo(self.window, QPoint())
            text = (widget.currentText() if isinstance(widget, QComboBox) else
                    widget.text() if hasattr(widget, 'text') else widget.accessibleName())
            controls.append(dict(id=name, text=text, enabled=widget.isEnabled(),
                                 bounds=[point.x(), point.y(), widget.width(), widget.height()]))
        observation = dict(image=image_path.name, controls=controls,
                           recording=self.window.recording,
                           library=self.window.in_library(),
                           disclosure='Production Qt widgets; synthetic devices, preview, files, playback and processes.')
        (self.output / 'observation.json').write_text(json.dumps(observation, indent=2) + '\n')
        return observation

    def act(self, command):
        if len(self.steps) >= 30 or time.monotonic() - self.started > 120:
            raise ValueError('Session budget exceeded')
        operation = command.get('action')
        if operation == 'wait':
            milliseconds = command.get('milliseconds', 100)
            if type(milliseconds) is not int or not 0 <= milliseconds <= 1000:
                raise ValueError('Wait must be between 0 and 1000 milliseconds')
            QTest.qWait(milliseconds)
        else:
            widget = self.controls().get(command.get('target'))
            if widget is None or not widget.isVisible() or not widget.isEnabled():
                raise ValueError('Target must be a visible, enabled fixture control')
            if operation == 'click':
                QTest.mouseClick(widget, Qt.LeftButton)
            elif operation == 'type' and isinstance(widget, QLineEdit):
                text = command.get('text', '')
                if not isinstance(text, str) or len(text) > 200:
                    raise ValueError('Text must have at most 200 characters')
                widget.setFocus()
                QTest.keyClick(widget, Qt.Key_A, Qt.ControlModifier)
                QTest.keyClicks(widget, text)
            elif operation == 'select' and widget is getattr(self.window.recordings, 'files', None):
                row = command.get('row')
                if type(row) is not int or not 0 <= row < widget.count():
                    raise ValueError('Select an existing fixture row')
                item = widget.item(row)
                if item.isHidden():
                    raise ValueError('Row is hidden')
                widget.scrollToItem(item)
                QTest.mouseClick(widget.viewport(), Qt.LeftButton,
                                 pos=widget.visualItemRect(item).center())
            elif operation == 'key' and command.get('key') in ('Tab', 'Return', 'Escape', 'Space'):
                QTest.keyClick(widget, getattr(Qt, 'Key_' + command['key']))
            else:
                raise ValueError('Unsupported action for this control')
        QTest.qWait(40)
        self.steps.append(command)
        (self.output / 'actions.json').write_text(json.dumps(self.steps, indent=2) + '\n')
        return self.observe()

    def close(self):
        self.case.doCleanups()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--actions', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = Session(args.output)
    try:
        print(json.dumps(session.observe()), flush=True)
        if args.actions:
            actions = json.loads(args.actions.read_text())
            if not isinstance(actions, list) or len(actions) > 30:
                raise ValueError('Provide an array of at most 30 actions')
            for action in actions:
                print(json.dumps(session.act(action)), flush=True)
        else:
            while time.monotonic() - session.started < 120:
                ready, _, _ = select.select([sys.stdin], [], [], 1)
                if not ready:
                    workflow.qt.processEvents()
                    continue
                line = sys.stdin.readline()
                if not line:
                    break
                print(json.dumps(session.act(json.loads(line))), flush=True)
    finally:
        session.close()


if __name__ == '__main__':
    main()
