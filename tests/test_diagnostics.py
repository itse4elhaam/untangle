"""Diagnostics use temporary logs and fake X11 data, never host windows/devices."""
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from untangle import diagnostics as d
from untangle.window_diagnostics import native_window_state


class DiagnosticTests(unittest.TestCase):
    def test_snapshot_handles_recorder_screen_selector_without_creating_windows(self):
        import test_app
        case = test_app.AppChecks()
        case.setUp()
        self.addCleanup(case.tearDown)
        owner = case.window
        from PySide6.QtWidgets import QWidget
        with patch.object(owner, 'winId', side_effect=AssertionError('native creation')), \
             self.assertLogs(d.logger) as captured:
            d.snapshot(owner, 'test')
        records = self.records(captured)
        self.assertEqual([r['event'] for r in records], ['window.snapshot', 'window.snapshot'])
        screen = QWidget.screen(owner).geometry()
        self.assertEqual(records[0]['screen_geometry'],
                         [screen.x(), screen.y(), screen.width(), screen.height()])

    def test_snapshot_without_a_log_handler_does_not_inspect_widgets(self):
        import logging
        with patch.object(d.logger, 'handlers', [logging.NullHandler()]), \
             patch.object(d, 'window_state') as inspect:
            d.snapshot(Mock(), 'test')
        inspect.assert_not_called()

    def test_window_state_does_not_create_a_native_window(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QWidget
        qt = QApplication.instance() or QApplication([])
        widget = QWidget()
        self.addCleanup(widget.close)
        self.assertFalse(widget.testAttribute(Qt.WA_WState_Created))
        self.assertIsNone(d.window_state(widget)['window_id'])
        self.assertFalse(widget.testAttribute(Qt.WA_WState_Created))

    def records(self, captured):
        return [json.loads(record.getMessage()) for record in captured.records]

    def test_failure_keeps_code_locations_but_no_message_or_payload(self):
        @d.observed('upload.test')
        def operation(token):
            raise RuntimeError('secret-token /private/recording.mp4')
        with self.assertLogs(d.logger) as captured:
            with self.assertRaises(RuntimeError):
                operation('secret-argument')
        records = self.records(captured)
        self.assertEqual([r['event'] for r in records], ['upload.test.start', 'upload.test.failed'])
        self.assertEqual(records[-1]['exception_type'], 'RuntimeError')
        self.assertTrue(records[-1]['frames'])
        self.assertNotIn('secret', json.dumps(records))
        self.assertNotIn('recording.mp4', json.dumps(records))

    def test_unknown_fields_and_logging_failure_cannot_affect_app(self):
        with self.assertLogs(d.logger) as captured:
            d.event('test', token='never-log', filename='never-log', recording=True)
        self.assertNotIn('never-log', captured.output[0])
        with patch.object(d.logger, 'info', side_effect=OSError('disk full')):
            d.event('test')

    def test_watchdog_reports_stall_once_then_resets_after_ui_heartbeat(self):
        now = [0.]
        watchdog = d.Heartbeat(clock=lambda: now[0])
        with self.assertLogs(d.logger) as captured:
            now[0] = 6.
            watchdog.check()
            watchdog.check()
            watchdog.beat()
            now[0] = 12.
            watchdog.check()
        self.assertEqual(len(captured.records), 2)
        self.assertEqual(self.records(captured)[0]['elapsed_ms'], 6000)

    def test_rotated_logs_are_bounded_private_and_startup_has_revision(self):
        handlers = list(d.logger.handlers)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(sys, 'excepthook'), patch.object(threading, 'excepthook'), \
             patch('PySide6.QtCore.qInstallMessageHandler'), patch.object(d, '_heartbeat'), \
             patch.object(d, 'revision', return_value='a' * 40), patch.object(threading, 'Thread'):
            try:
                d.logger.handlers = []
                d.install(directory)
                path = Path(directory) / 'diagnostics.jsonl'
                self.assertEqual(json.loads(path.read_text().splitlines()[0])['build_revision'], 'a' * 40)
                context = SimpleNamespace(category='test.category', file='/private/a.cpp', line=42)
                for _ in range(100):
                    d.install.qt_handler(1, context, 'secret-token')
                contents = path.read_text()
                self.assertEqual(contents.count('qt.message'), 1)
                self.assertNotIn('secret-token', contents)
                handler = d.logger.handlers[0]
                handler.maxBytes = 500
                for _ in range(100):
                    d.event('test.rotation')
                files = list(Path(directory).iterdir())
                self.assertLessEqual(len(files), 4)
                for file in files:
                    self.assertEqual(file.stat().st_mode & 0o777, 0o600)
                    self.assertLessEqual(file.stat().st_size, 500)
            finally:
                for handler in d.logger.handlers:
                    handler.close()
                d.logger.handlers = handlers

    def test_native_snapshot_includes_wm_frame_input_and_closes_connection(self):
        connection = Mock()
        root, client, frame = Mock(id=1), Mock(id=2), Mock(id=3)
        root.query_pointer.return_value.child = frame
        connection.screen.return_value.root = root
        connection.create_resource_object.return_value = client
        for window, parent, width, height in [(client, frame, 200, 200), (frame, root, 1920, 1080)]:
            window.query_tree.return_value.parent = parent
            window.get_geometry.return_value = SimpleNamespace(x=0, y=0, width=width, height=height)
            window.get_attributes.return_value = SimpleNamespace(map_state=2, override_redirect=False)
            window.shape_get_rectangles.return_value.rectangles = [
                SimpleNamespace(x=0, y=0, width=width, height=height)]
        with patch('Xlib.display.Display', return_value=connection):
            result = native_window_state(2)
        self.assertEqual(result['pointer_child'], 3)
        self.assertEqual(result['windows'][1]['input_bounds'], [0, 0, 1920, 1080])
        client.get_wm_name.assert_not_called()
        connection.close.assert_called_once()

    def test_native_snapshot_closes_connection_on_protocol_failure(self):
        connection = Mock()
        connection.create_resource_object.return_value.get_geometry.side_effect = RuntimeError('X11')
        with patch('Xlib.display.Display', return_value=connection):
            with self.assertRaises(RuntimeError):
                native_window_state(2)
        connection.close.assert_called_once()
