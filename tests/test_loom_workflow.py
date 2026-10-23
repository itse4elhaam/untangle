"""Loom UI workflow with synthetic files and signal-driven, inert processes.

Run only this file: PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_loom_workflow.py -v
No app entry point, media backend, account command, upload, or capture runs.
"""
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

for _name in ('DISPLAY', 'WAYLAND_DISPLAY', 'RECIT_TEST_MIC_HARDWARE',
              'RECIT_HARDWARE_PRIVATE_DISPLAY', 'RECIT_NATIVE_PRIVATE_DISPLAY', 'RECIT_TEST_XVFB'):
    os.environ.pop(_name, None)
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtCore import QObject, QProcess, QTimer, Signal, QCoreApplication, QEvent
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QMessageBox, QPushButton
from untangle import app as glint, recordings
from untangle.loom import parse_upload_result, parse_video_info
import test_app as app_fixture

_spec = importlib.util.spec_from_file_location(
    'loom_render_helpers', Path(__file__).resolve().parents[1] / 'scripts/render-ui.py')
render_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_helpers)
qt = app_fixture.qt

URL = 'https://www.loom.com/share/abc123'
HELP = 'Usage: twg loom video upload [options] <file>\n'
MODERN_HELP = HELP + '  --visibility <visibility>\n  --title <title>\n'
ACCOUNT = json.dumps({'ok': True, 'data': {
    'accountId': 'synthetic-account', 'name': 'Synthetic User', 'email': 'user@example.invalid'}})


def video_response(**fields):
    return json.dumps({'ok': True, 'data': {'video': {
        'id': 'abc123', 'url': URL, 'name': 'Loom generated title',
        'isComplete': False, **fields}}})


class InertProcess(QObject):
    """Real Qt signals and ownership; never inherits or starts a real process."""
    finished = Signal(int, object)
    errorOccurred = Signal(object)
    readyReadStandardOutput = Signal()
    readyReadStandardError = Signal()
    NormalExit, CrashExit = QProcess.NormalExit, QProcess.CrashExit
    FailedToStart, Crashed = QProcess.FailedToStart, QProcess.Crashed
    NotRunning, Running = QProcess.NotRunning, QProcess.Running

    def __init__(self, parent=None):
        super().__init__(parent)
        self.program = None
        self.arguments = []
        self.stdout = self.stderr = b''
        self.started = self.killed = False

    def setProgram(self, value):
        self.program = value

    def setArguments(self, value):
        self.arguments = value

    def start(self):
        self.started = True

    def kill(self):
        self.killed = True

    def waitForFinished(self, timeout):
        return True

    def state(self):
        return self.Running if self.started and not self.killed else self.NotRunning

    def readAllStandardOutput(self):
        value, self.stdout = self.stdout, b''
        return value

    def readAllStandardError(self):
        value, self.stderr = self.stderr, b''
        return value

    def feed(self, value, *, errors=False):
        chunk = value.encode() if isinstance(value, str) else value
        if errors:
            self.stderr += chunk
            self.readyReadStandardError.emit()
        else:
            self.stdout += chunk
            self.readyReadStandardOutput.emit()

    def finish(self, output='', code=0, status=QProcess.NormalExit, errors=''):
        self.feed(output)
        self.feed(errors, errors=True)
        self.finished.emit(code, status)


class LoomWorkflowChecks(unittest.TestCase):
    # Delegate the fixture instead of inheriting and rediscovering AppChecks.
    def setUp(self):
        for replacement in (
            patch.object(glint, 'Preview', render_helpers.SoftwarePreview),
            patch.object(glint, 'QProcess', InertProcess),
            patch.object(recordings, 'QProcess', InertProcess),
            patch.object(recordings.Recordings, 'start_thumbnail'),
            patch.object(recordings, 'QMediaPlayer', render_helpers.silent_player_type()),
            patch.object(recordings, 'QAudioOutput', side_effect=render_helpers.silent_audio_output),
            patch.object(glint.WindowCatalog, 'list', return_value=[]),
            patch.object(glint.WindowCatalog, 'close'),
            patch.object(glint.Window, 'find_cli', return_value='/synthetic/twg'),
            patch.object(glint.QDesktopServices, 'openUrl', return_value=True),
            patch.object(glint.subprocess, 'Popen', side_effect=AssertionError('External launch forbidden')),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)
        app_fixture.AppChecks.setUp(self)
        self.addCleanup(app_fixture.AppChecks.tearDown, self)
        self.window.timer.stop()
        self.window.configure_timer.stop()
        self.path = self.root / 'Local walkthrough.mp4'
        self.path.write_bytes(b'Synthetic metadata only; not playable media.')
        self.window.set_last(self.path)
        qt.clipboard().setText('unchanged')

    def begin_upload(self, help_text=MODERN_HELP):
        self.window.upload()
        helper = self.window.process
        self.assertEqual(helper.arguments, ['loom', 'video', 'upload', '--help'])
        helper.finish(help_text)
        self.assertIsNot(self.window.process, helper)
        return self.window.process

    def assert_unlocked(self):
        self.assertFalse(self.window.busy)
        self.assertFalse(self.window._upload_active)
        self.assertFalse(self.window.upload_timer.isActive())
        self.assertTrue(self.window.library_button.isEnabled())
        self.assertTrue(self.window.sharing_button.isEnabled())
        self.assertTrue(self.window.record_button.isEnabled())
        self.assertTrue(self.path.is_file())

    def publish(self, *, help_text=MODERN_HELP, **fields):
        process = self.begin_upload(help_text)
        process.finish(video_response(**fields))
        if help_text == HELP:
            self.window.process.finish(code=1)

    def open_library(self):
        self.window.open_recordings(self.path)
        return self.window.recordings

    def inspect_sharing(self, inspect, response=ACCOUNT, code=0, errors=''):
        def probe(args, callback, **kwargs):
            callback(response, code, errors)
        def execute(dialog):
            qt.processEvents()  # Run the production initial asynchronous probe.
            inspect(dialog)
            return QDialog.Accepted
        with patch.object(self.window, 'loom_probe', side_effect=probe) as probe_mock, \
                patch.object(QDialog, 'exec', new=execute):
            self.window.sharing_settings()
        return probe_mock

    @staticmethod
    def buttons(dialog):
        return {button.text(): button for button in dialog.findChildren(QPushButton)}

    def test_progress_stream_handles_split_chunks_percent_and_processing(self):
        process = self.begin_upload()
        self.assertEqual(self.window.upload_progress.maximum(), 0)
        process.feed('Upload')
        process.feed('ing 4')
        process.feed('2.4%\r')
        self.assertEqual(self.window.upload_progress.maximum(), 100)
        self.assertEqual(self.window.upload_progress.value(), 42)
        self.assertIn('42.4%', self.window.upload_heading.text())
        process.feed('Processing video\n', errors=True)
        self.assertEqual(self.window.upload_progress.maximum(), 0)
        self.assertIn('processing', self.window.upload_heading.text())
        self.assertTrue(self.window.busy)
        self.assertNotIn('copied', self.window.upload_detail.text())

    def test_result_byte_counts_never_become_transfer_progress(self):
        process = self.begin_upload()
        process.feed('{"bytes":99,"total":100,"name":"Uploading 99%"}\n')
        self.assertEqual(self.window.upload_progress.maximum(), 0)
        self.assertTrue(self.window._upload_active)

    def test_actual_video_name_and_completion_fields(self):
        for complete, state in ((False, 'processing'), (True, 'uploaded')):
            with self.subTest(complete=complete):
                output = video_response(isComplete=complete)
                upload = parse_upload_result(output)
                self.assertEqual(upload['title'], 'Loom generated title')
                self.assertEqual(upload['status'], state)
                info = parse_video_info(output)
                self.assertEqual(info['title'], 'Loom generated title')
                self.assertIs(info['is_complete'], complete)

    def test_visibility_failure_preserves_url_title_and_duplicate_guard(self):
        self.window.prefs.setValue('visibility', 'owner')
        process = self.begin_upload(HELP)
        self.window.prefs.setValue('visibility', 'public')
        process.finish(video_response())
        visibility = self.window.process
        self.assertEqual(visibility.arguments, [
            'loom', 'video', 'visibility', 'set', URL, '--visibility', 'owner',
            '-o', 'json', '--output-summary', 'none'])
        self.assertEqual(self.window.upload_store.get(self.path)['title'], 'Loom generated title')
        self.assertEqual(qt.clipboard().text(), 'unchanged')
        visibility.finish(code=1)
        state = self.window.upload_store.get(self.path)
        self.assertEqual(state['url'], URL)
        self.assertEqual(state['title'], 'Loom generated title')
        self.assertEqual(state['status'], 'processing')
        self.assertTrue(state['visibility_warning'])
        self.assertFalse(self.window.upload_copy.isHidden())
        self.assert_unlocked()
        self.window.copy_uploaded_link()
        self.assertEqual(qt.clipboard().text(), URL)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Cancel) as confirm:
            self.window.retry_upload()
        confirm.assert_called_once()
        self.assertIs(self.window.process, visibility)
        self.assertEqual(self.window.upload_store.get(self.path)['url'], URL)
        persisted = json.loads((self.root / 'uploads.json').read_text())['uploads'][str(self.path)]
        self.assertEqual(persisted['url'], URL)
        self.assertEqual(persisted['title'], 'Loom generated title')
        self.assertTrue(persisted['visibility_warning'])

    def test_success_copies_url_and_processing_stays_explicit(self):
        self.publish()
        self.assert_unlocked()
        self.assertEqual(qt.clipboard().text(), URL)
        self.assertEqual(self.window.upload_store.get(self.path)['status'], 'processing')
        self.assertIn('processing', self.window.upload_heading.text())
        self.assertIn('no measurable progress', self.window.upload_detail.text())
        self.assertTrue(self.window.upload_progress.isHidden())

    def test_default_title_preference_omits_supported_title_override(self):
        process = self.begin_upload()
        self.assertNotIn('--title', process.arguments)
        self.assertEqual(process.arguments[:4], ['loom', 'video', 'upload', str(self.path)])
        self.assertIn('--visibility', process.arguments)

    def test_manual_title_preference_is_snapshotted_before_help_returns(self):
        self.window.prefs.setValue('loom_auto_titles', False)
        self.window.upload()
        helper = self.window.process
        self.window.prefs.setValue('loom_auto_titles', True)
        helper.finish(MODERN_HELP)
        self.assertEqual(self.window.process.arguments[-2:], ['--title', 'Local walkthrough'])

    def test_manual_title_without_advertised_support_fails_before_transfer(self):
        self.window.prefs.setValue('loom_auto_titles', False)
        self.window.upload()
        helper = self.window.process
        helper.finish(HELP)
        self.assertIs(self.window.process, helper)
        self.assert_unlocked()
        self.assertIn('syntax could not be verified', self.window.status.text().lower())

    def test_failed_and_crashed_transfers_unlock_and_keep_local_file(self):
        for code, status, output, expected in (
            (77, QProcess.NormalExit, '{"ok":false,"error":{"code":"AUTH_REQUIRED"}}', 'failed'),
            (1, QProcess.CrashExit, '', 'uncertain'),
        ):
            with self.subTest(status=status):
                self.window.upload_store.remove(self.path)
                process = self.begin_upload()
                process.finish(output, code, status)
                self.assert_unlocked()
                self.assertEqual(self.window.upload_store.get(self.path)['status'], expected)
                self.assertEqual(qt.clipboard().text(), 'unchanged')

    def test_failed_upload_retry_uses_same_file_without_duplicate_prompt(self):
        process = self.begin_upload()
        process.finish('{"ok":false,"error":{"code":"AUTH_REQUIRED"}}', 77)
        with patch.object(QMessageBox, 'question') as confirm:
            self.window.retry_upload()
        confirm.assert_not_called()
        self.assertTrue(self.window._upload_active)
        self.assertEqual(self.window._upload_file, self.path)
        self.assertIsNot(self.window.process, process)

    def test_structured_auth_failure_marks_connection_disconnected(self):
        self.window.loom_account = {'status': 'connected', 'name': 'Synthetic User'}
        process = self.begin_upload()
        process.finish('{"ok":false,"error":{"code":"AUTH_REQUIRED"}}', 77)
        self.assert_unlocked()
        self.assertEqual(self.window.loom_account['status'], 'disconnected')
        self.assertIn('connect your Loom account', self.window.status.text())

    def test_cancel_needs_confirmation_then_ignores_late_finished_signal(self):
        process = self.begin_upload()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Cancel):
            self.window.retry_upload()
        self.assertFalse(process.killed)
        self.assertTrue(self.window._upload_active)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            self.window.retry_upload()
        self.assertTrue(process.killed)
        self.assert_unlocked()
        process.finish(video_response(isComplete=True))
        self.assertEqual(self.window.upload_store.get(self.path)['status'], 'uncertain')
        self.assertEqual(qt.clipboard().text(), 'unchanged')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Cancel) as confirm:
            self.window.retry_upload()
        confirm.assert_called_once()
        self.assertFalse(self.window._upload_active)

    def test_process_launch_error_is_terminal_only_once(self):
        self.window.upload()
        process = self.window.process
        with patch.object(self.window, 'upload_end', wraps=self.window.upload_end) as ended:
            process.errorOccurred.emit(QProcess.FailedToStart)
            process.finished.emit(1, QProcess.CrashExit)
            process.errorOccurred.emit(QProcess.FailedToStart)
            self.assertEqual(ended.call_count, 1)
        self.assert_unlocked()
        self.assertEqual(self.window.upload_store.get(self.path)['status'], 'failed')

    def test_sharing_launch_failure_and_timeout_preserve_processing_metadata(self):
        for outcome in ('failed_start', 'timeout'):
            with self.subTest(outcome=outcome):
                self.window.upload_store.remove(self.path)
                process = self.begin_upload(HELP)
                timers = set(self.window.findChildren(QTimer))
                process.finish(video_response())
                visibility = self.window.process
                self.assertIsNot(visibility, process)
                if outcome == 'failed_start':
                    visibility.errorOccurred.emit(QProcess.FailedToStart)
                else:
                    created = set(self.window.findChildren(QTimer)) - timers
                    self.assertEqual(len(created), 1)
                    next(iter(created)).timeout.emit()
                    self.assertTrue(visibility.killed)
                self.assert_unlocked()
                state = self.window.upload_store.get(self.path)
                self.assertEqual(state['status'], 'processing')
                self.assertEqual(state['url'], URL)
                self.assertEqual(state['title'], 'Loom generated title')
                self.assertTrue(state['visibility_warning'])
                self.assertIn('processing', self.window.upload_heading.text())
                self.assertEqual(qt.clipboard().text(), 'unchanged')

    def test_launch_failure_disposes_check_timer_without_waiting_twenty_seconds(self):
        timers = set(self.window.findChildren(QTimer))
        self.window.upload()
        created = set(self.window.findChildren(QTimer)) - timers
        self.window.process.errorOccurred.emit(QProcess.FailedToStart)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        remaining = set(self.window.findChildren(QTimer)) & created
        self.assertFalse(remaining, 'Failed-to-start check left an owned timeout callback behind')

    def replace_source(self):
        replacement = self.path.with_suffix('.replacement')
        replacement.write_bytes(b'Synthetic replacement recording')
        replacement.replace(self.path)

    def test_replaced_source_during_transfer_never_gets_original_link(self):
        process = self.begin_upload()
        self.replace_source()
        process.finish(video_response(isComplete=True))
        self.assert_unlocked()
        self.assertEqual(self.window.upload_store.get(self.path), {})
        self.assertIsNone(self.window._upload_url)
        self.assertTrue(self.window.upload_copy.isHidden())
        self.assertIn('changed during upload', self.window.upload_detail.text())
        self.window.copy_uploaded_link()
        self.assertEqual(qt.clipboard().text(), 'unchanged')

    def test_replaced_source_during_visibility_never_gets_original_link(self):
        process = self.begin_upload(HELP)
        process.finish(video_response(isComplete=True))
        self.replace_source()
        self.window.process.finish()
        self.assert_unlocked()
        self.assertEqual(self.window.upload_store.get(self.path), {})
        self.assertIsNone(self.window._upload_url)
        self.assertTrue(self.window.upload_copy.isHidden())
        self.assertEqual(qt.clipboard().text(), 'unchanged')

    def test_replaced_source_invalidates_unsaved_link_before_copy(self):
        with patch.object(self.window.upload_store, 'update', side_effect=OSError('Synthetic disk full')):
            self.publish(isComplete=True)
        self.replace_source()
        qt.clipboard().setText('unchanged')
        self.window.copy_uploaded_link()
        self.assertEqual(qt.clipboard().text(), 'unchanged')
        self.assertTrue(self.window.upload_panel.isHidden())

    def test_forget_invalidates_link_after_final_metadata_write_fails(self):
        process = self.begin_upload(HELP)
        process.finish(video_response(isComplete=True))
        self.assertEqual(self.window.upload_store.get(self.path)['url'], URL)
        with patch.object(self.window.upload_store, 'update', side_effect=OSError('Synthetic disk full')):
            self.window.process.finish()
        self.assertTrue(self.window._upload_metadata_warning)
        page = self.open_library()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            page.forget_selected_loom()
        self.window.back_to_recorder()
        self.assertEqual(self.window.upload_store.get(self.path), {})
        self.assertTrue(self.window.upload_panel.isHidden())
        qt.clipboard().setText('unchanged')
        self.window.copy_uploaded_link()
        self.assertEqual(qt.clipboard().text(), 'unchanged')

    def test_metadata_failure_warns_but_keeps_visible_copyable_url(self):
        with patch.object(self.window.upload_store, 'update', side_effect=OSError('Synthetic disk full')):
            process = self.begin_upload()
            process.finish(video_response(isComplete=True))
        self.assert_unlocked()
        self.assertIn('could not be saved locally', self.window.upload_detail.text())
        self.assertFalse(self.window.upload_copy.isHidden())
        qt.clipboard().setText('unchanged')
        self.window.copy_uploaded_link()
        self.assertEqual(qt.clipboard().text(), URL)

    def test_sharing_connected_identity_hides_connect_and_ai_claims_are_limited(self):
        def inspect(dialog):
            buttons = self.buttons(dialog)
            self.assertTrue(buttons['Reconnect Loom account ↗'].isHidden())
            self.assertFalse(buttons['Disconnect TWG account…'].isHidden())
            self.assertIn('Synthetic User', self.window.cli_status.text())
            self.assertIn('user@example.invalid', self.window.cli_status.text())
            checks = dialog.findChildren(QCheckBox)
            self.assertTrue(checks[1].isChecked())
            text = ' '.join(label.text() for label in dialog.findChildren(QLabel))
            self.assertIn('not confirmed', text)
            self.assertIn('cannot read or enable', text)
            self.assertIn('30 seconds', text)
            checks[1].setChecked(False)
        probe = self.inspect_sharing(inspect)
        self.assertEqual(probe.call_args.args[0], ['whoami', '-o', 'json', '--output-summary', 'none'])
        self.assertFalse(self.window.prefs.value('loom_auto_titles', True, type=bool))

    def test_sharing_optout_initial_description_matches_saved_preference(self):
        self.window.prefs.setValue('loom_auto_titles', False)
        def inspect(dialog):
            titles = dialog.findChildren(QCheckBox)[1]
            self.assertFalse(titles.isChecked())
            labels = [label.text() for label in dialog.findChildren(QLabel)]
            self.assertTrue(any('request your local recording title' in text for text in labels))
            self.assertFalse(any('Enabled here:' in text for text in labels))
        self.inspect_sharing(inspect)

    def test_sharing_unknown_disconnected_and_missing_cli_states(self):
        for response, code, text, title in (
            ('', 1, 'not been verified', 'Reconnect Loom account ↗'),
            ('{"error":{"code":"AUTH_REQUIRED"}}', 77, 'disconnected', 'Connect Loom account ↗'),
        ):
            with self.subTest(code=code):
                def inspect(dialog):
                    buttons = self.buttons(dialog)
                    self.assertIn(text, self.window.cli_status.text())
                    self.assertFalse(buttons[title].isHidden())
                    self.assertTrue(buttons[title].isEnabled())
                    self.assertTrue(buttons['Disconnect TWG account…'].isHidden())
                self.inspect_sharing(inspect, response, code)
        with patch.object(self.window, 'find_cli', return_value=None):
            def inspect_missing(dialog):
                self.assertIn('Install', self.window.cli_status.text())
                self.assertFalse(self.buttons(dialog)['Check connection'].isEnabled())
            self.inspect_sharing(inspect_missing)

    def test_sharing_can_recheck_after_external_connection(self):
        responses = iter([('', 1, ''), (ACCOUNT, 0, '')])
        def probe(args, callback, **kwargs):
            callback(*next(responses))
        def execute(dialog):
            qt.processEvents()
            buttons = self.buttons(dialog)
            self.assertFalse(buttons['Reconnect Loom account ↗'].isHidden())
            buttons['Reconnect Loom account ↗'].click()
            buttons['Check connection'].click()
            self.assertIn('Connected as Synthetic User', self.window.cli_status.text())
            self.assertTrue(buttons['Reconnect Loom account ↗'].isHidden())
            return QDialog.Accepted
        with patch.object(self.window, 'loom_probe', side_effect=probe), \
                patch.object(self.window, 'connect_loom') as connect, \
                patch.object(QDialog, 'exec', new=execute):
            self.window.sharing_settings()
        connect.assert_called_once_with()

    def test_logout_blocks_checks_even_after_reopening_sharing(self):
        pending = []
        def probe(args, callback, **kwargs):
            pending.append((args[0], callback))
        def first_dialog(dialog):
            qt.processEvents()
            pending.pop()[1](ACCOUNT, 0, '')
            buttons = self.buttons(dialog)
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                buttons['Disconnect TWG account…'].click()
            self.assertEqual([item[0] for item in pending], ['logout'])
            self.assertFalse(buttons['Check connection'].isEnabled())
            buttons['Check connection'].click()
            self.assertEqual(len(pending), 1)
            return QDialog.Accepted
        def second_dialog(dialog):
            qt.processEvents()
            buttons = self.buttons(dialog)
            self.assertEqual([item[0] for item in pending], ['logout'])
            self.assertFalse(buttons['Check connection'].isEnabled())
            pending.pop()[1]('{}', 0, '')
            self.assertEqual(self.window.loom_account['status'], 'disconnected')
            self.assertIn('disconnected', self.window.cli_status.text())
            self.assertTrue(buttons['Check connection'].isEnabled())
            return QDialog.Accepted
        with patch.object(self.window, 'loom_probe', side_effect=probe):
            with patch.object(QDialog, 'exec', new=first_dialog):
                self.window.sharing_settings()
            with patch.object(QDialog, 'exec', new=second_dialog):
                self.window.sharing_settings()

    def test_pending_account_check_blocks_logout_in_reopened_dialog(self):
        pending = []
        def probe(args, callback, **kwargs):
            pending.append(callback)
        def first_dialog(dialog):
            qt.processEvents()
            return QDialog.Accepted
        def second_dialog(dialog):
            qt.processEvents()
            buttons = self.buttons(dialog)
            self.assertFalse(buttons['Disconnect TWG account…'].isEnabled())
            self.assertEqual(len(pending), 1)
            pending.pop()(ACCOUNT, 0, '')
            self.assertTrue(buttons['Disconnect TWG account…'].isEnabled())
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                buttons['Disconnect TWG account…'].click()
            pending.pop()('{}', 0, '')
            self.assertEqual(self.window.loom_account['status'], 'disconnected')
            return QDialog.Accepted
        self.window.loom_account = {'status': 'connected'}
        with patch.object(self.window, 'loom_probe', side_effect=probe):
            with patch.object(QDialog, 'exec', new=first_dialog):
                self.window.sharing_settings()
            with patch.object(QDialog, 'exec', new=second_dialog):
                self.window.sharing_settings()

    def test_logout_requires_explicit_confirmation(self):
        calls = []
        def probe(args, callback, **kwargs):
            calls.append(args)
            callback(ACCOUNT if args[0] == 'whoami' else '{}', 0, '')
        def execute(dialog):
            qt.processEvents()
            disconnect = self.buttons(dialog)['Disconnect TWG account…']
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Cancel):
                disconnect.click()
            self.assertEqual(len(calls), 1)
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                disconnect.click()
            self.assertEqual(calls[-1], ['logout', '-o', 'json', '--output-summary', 'none'])
            self.assertIn('disconnected', self.window.cli_status.text())
            return QDialog.Accepted
        with patch.object(self.window, 'loom_probe', side_effect=probe), \
                patch.object(QDialog, 'exec', new=execute):
            self.window.sharing_settings()

    def test_remote_available_refreshes_title_and_completion_in_library(self):
        self.publish()
        page = self.open_library()
        self.window.check_loom_video(self.path)
        probe = next(iter(self.window.loom_probes))
        self.assertEqual(probe.arguments[:4], ['loom', 'video', 'get', 'abc123'])
        probe.finish(video_response(name='Refreshed upstream title', isComplete=True))
        self.assertEqual(self.window.upload_store.get(self.path)['status'], 'uploaded')
        self.assertIn('Refreshed upstream title', page.loom_title.text())
        self.assertFalse(page.copy_loom.isHidden())

    def test_remote_deleted_hides_library_and_recorder_links(self):
        self.publish(isComplete=True)
        page = self.open_library()
        self.window.check_loom_video(self.path)
        next(iter(self.window.loom_probes)).finish(video_response(status='DELETED'))
        self.assertTrue(page.copy_loom.isHidden())
        self.assertTrue(page.open_loom.isHidden())
        self.assertEqual(self.window.upload_store.get(self.path)['status'], 'deleted')
        self.window.back_to_recorder()
        self.assertTrue(self.window.upload_panel.isHidden())
        qt.clipboard().setText('unchanged')
        self.window.copy_uploaded_link()
        self.assertEqual(qt.clipboard().text(), 'unchanged')
        self.assertTrue(self.path.is_file())

    def test_unknown_or_offline_remote_keeps_valid_saved_url(self):
        self.publish(isComplete=True)
        page = self.open_library()
        for output, code in (('', 1), ('{"ok":false,"error":{"code":"NOT_FOUND"}}', 1),
                             (video_response(status='PRIVATE'), 0)):
            with self.subTest(output=output):
                self.window.check_loom_video(self.path)
                next(iter(self.window.loom_probes)).finish(output, code)
                self.assertEqual(self.window.upload_store.get(self.path)['url'], URL)
                self.assertFalse(page.copy_loom.isHidden())
                self.assertIn('unchanged', page.message.text())

    def test_pending_remote_checks_are_deduplicated_then_retryable(self):
        self.publish(isComplete=True)
        self.window.check_loom_video(self.path)
        process = next(iter(self.window.loom_probes))
        self.window.check_loom_video(self.path)
        self.assertEqual(self.window.loom_probes, {process})
        process.finish(code=1)
        self.assertFalse(self.window.loom_probes)
        self.window.check_loom_video(self.path)
        self.assertEqual(len(self.window.loom_probes), 1)
        self.assertNotIn(process, self.window.loom_probes)

    def test_stale_remote_result_cannot_overwrite_changed_metadata(self):
        self.publish(isComplete=True)
        self.window.check_loom_video(self.path)
        process = next(iter(self.window.loom_probes))
        self.window.upload_store.update(self.path, title='Newer local metadata', status='uploading')
        expected = self.window.upload_store.get(self.path)
        process.finish(video_response(status='DELETED'))
        self.assertEqual(self.window.upload_store.get(self.path), expected)
        self.assertFalse(self.window.upload_panel.isHidden())

    def test_stale_remote_result_after_forget_does_not_restore_metadata(self):
        self.publish(isComplete=True)
        self.window.check_loom_video(self.path)
        process = next(iter(self.window.loom_probes))
        self.window.upload_store.remove(self.path)
        process.finish(video_response(name='Late remote result', isComplete=True))
        self.assertEqual(self.window.upload_store.get(self.path), {})
        self.window.refresh_upload_link()
        self.assertTrue(self.window.upload_panel.isHidden())

    def test_remote_title_refresh_metadata_failure_is_visible_in_library(self):
        self.publish(isComplete=True)
        page = self.open_library()
        self.window.check_loom_video(self.path)
        process = next(iter(self.window.loom_probes))
        with patch.object(self.window.upload_store, 'update', side_effect=OSError('Synthetic disk full')):
            process.finish(video_response(name='Unsaved remote title', isComplete=True))
        self.assertEqual(self.window.upload_store.get(self.path)['title'], 'Loom generated title')
        self.assertIn('could not', page.message.text().lower())
        self.assertNotIn('title is refreshed', page.message.text())

    def test_local_delete_and_forget_clear_recorder_link_after_navigation(self):
        for action in ('forget_selected_loom', 'delete_selected'):
            with self.subTest(action=action):
                if not self.path.exists():
                    self.path.write_bytes(b'Synthetic replacement')
                    self.window.set_last(self.path)
                self.publish(isComplete=True)
                page = self.open_library()
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                    getattr(page, action)()
                self.window.back_to_recorder()
                self.assertTrue(self.window.upload_panel.isHidden())
                qt.clipboard().setText('unchanged')
                self.window.copy_uploaded_link()
                self.assertEqual(qt.clipboard().text(), 'unchanged')
                self.assertEqual(self.window.upload_store.get(self.path), {})

    def test_local_delete_clears_unsaved_success_link_after_metadata_failure(self):
        with patch.object(self.window.upload_store, 'update', side_effect=OSError('Synthetic disk full')):
            self.publish(isComplete=True)
        self.assertTrue(self.window._upload_metadata_warning)
        page = self.open_library()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            page.delete_selected()
        self.window.back_to_recorder()
        self.assertFalse(self.path.exists())
        self.assertTrue(self.window.upload_panel.isHidden())
        qt.clipboard().setText('unchanged')
        self.window.copy_uploaded_link()
        self.assertEqual(qt.clipboard().text(), 'unchanged')

    def test_probe_success_failure_timeout_are_once_and_cleanup_timers(self):
        for outcome in ('success', 'failed_start', 'timeout'):
            with self.subTest(outcome=outcome):
                callback = MagicMock()
                process = self.window.loom_probe(['whoami'], callback)
                timer = process.findChild(QTimer)
                self.assertTrue(timer.isActive())
                if outcome == 'success':
                    process.feed('{"ok":')
                    process.finish('true}')
                    callback.assert_called_once_with('{"ok":true}', 0, '')
                elif outcome == 'failed_start':
                    process.errorOccurred.emit(QProcess.FailedToStart)
                else:
                    timer.timeout.emit()
                    self.assertTrue(process.killed)
                self.assertFalse(timer.isActive())
                process.finished.emit(1, QProcess.CrashExit)
                self.assertEqual(callback.call_count, 1)
                self.assertNotIn(process, self.window.loom_probes)
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_probe_close_never_reports_after_window_close(self):
        callback = MagicMock()
        process = self.window.loom_probe(['whoami'], callback)
        self.window.close()
        self.assertTrue(process.killed)
        process.finish(ACCOUNT)
        callback.assert_not_called()
        self.assertFalse(self.window.loom_probes)

    def test_closed_sharing_does_not_run_queued_account_probe(self):
        # A dialog can close before its zero-delay initial probe is dispatched.
        with patch.object(QDialog, 'exec', return_value=QDialog.Rejected), \
                patch.object(self.window, 'loom_probe') as probe:
            self.window.sharing_settings()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            qt.processEvents()
        probe.assert_not_called()


if __name__ == '__main__':
    unittest.main()
