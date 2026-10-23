"""Synthetic title-job checks. No capture, recordings, inference, or auth calls."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QProcess, Signal
from shiboken6 import isValid

from untangle import local_titles as titles


HELP = '\n'.join('  ' + flag + ' VALUE' for flag in (
    '--ignore-user-config', '--strict-config', '--ephemeral', '--output-schema',
    '--output-last-message', '--sandbox', '--skip-git-repo-check', '--model', '--json'))
TRANSCRIPT = 'We fixed duplicate order imports by storing the external order identifier.'
TITLE = 'Preventing duplicate order imports'
EVENTS = '\n'.join(json.dumps(event) for event in (
    {'type': 'thread.started', 'thread_id': 'synthetic'},
    {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps({'title': TITLE})}},
    {'type': 'turn.completed', 'usage': {}}))


class InertProcess(QObject):
    started = Signal()
    finished = Signal(int, object)
    errorOccurred = Signal(object)
    readyReadStandardOutput = Signal()
    readyReadStandardError = Signal()
    NormalExit, CrashExit = QProcess.NormalExit, QProcess.CrashExit
    FailedToStart, NotRunning, Running = QProcess.FailedToStart, QProcess.NotRunning, QProcess.Running
    UnixProcessParameters, UnixProcessFlag = QProcess.UnixProcessParameters, QProcess.UnixProcessFlag
    instances = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self.instances.append(self)
        self.output = self.errors = b''
        self.input = b''
        self.running = self.killed = self.input_closed = False

    def setUnixProcessParameters(self, parameters):
        self.parameters = parameters

    def setWorkingDirectory(self, path):
        self.cwd = path

    def setProgram(self, program):
        self.program = program

    def setArguments(self, args):
        self.arguments = args

    def start(self):
        self.running = True
        self.started.emit()

    def write(self, data):
        self.input += data

    def closeWriteChannel(self):
        self.input_closed = True

    def state(self):
        return self.Running if self.running else self.NotRunning

    def processId(self):
        return 99999999 if self.running else 0

    def kill(self):
        self.killed = True
        self.running = False
        self.finished.emit(-9, self.CrashExit)

    def waitForFinished(self, timeout):
        return not self.running

    def readAllStandardOutput(self):
        data, self.output = self.output, b''
        return data

    def readAllStandardError(self):
        data, self.errors = self.errors, b''
        return data

    def feed(self, output=b'', errors=b''):
        self.output += output.encode() if isinstance(output, str) else output
        self.errors += errors.encode() if isinstance(errors, str) else errors
        self.readyReadStandardOutput.emit()

    def finish(self, output='', code=0, status=NormalExit, errors=''):
        self.running = False
        self.feed(output, errors)
        self.finished.emit(code, status)


class LocalTitleJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='untangle-title-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / 'synthetic.mp4'
        self.video.write_bytes(b'Not real media. Never processed.')
        self.model = self.root / 'ggml-base.en.bin'
        self.model.write_bytes(b'Synthetic model path only.')
        InertProcess.instances = []
        for replacement in (patch.object(titles, 'QProcess', InertProcess),
                            patch.object(titles, '_dependencies', return_value=(
                                '/synthetic/ffmpeg', '/synthetic/whisper-cli', '/synthetic/codex', self.model)),
                            patch.object(titles.os, 'killpg')):
            replacement.start()
            self.addCleanup(replacement.stop)
        self.parent = QObject()
        self.job = titles.LocalTitleJob(self.parent)
        self.results = []
        self.job.finished.connect(lambda title, error: self.results.append((title, error)))
        self.addCleanup(self.dispose)

    def dispose(self):
        if self.job is not None and isValid(self.job):
            self.job.cancel()
        if self.parent is not None and isValid(self.parent):
            self.parent.deleteLater()
        self.qt.sendPostedEvents(None, QEvent.DeferredDelete)

    @property
    def process(self):
        return InertProcess.instances[-1]

    def begin(self):
        self.job.start(self.video)
        self.assertEqual(self.results, [])
        self.qt.processEvents()
        return self.process

    def reach_transcript(self):
        self.begin().finish(HELP)
        self.process.finish()  # Synthetic ffmpeg completion.
        self.assertEqual(self.job._timer.interval(), 90000)
        return self.process

    def reach_title(self):
        process = self.reach_transcript()
        self.job._root.joinpath('transcript.txt').write_text(TRANSCRIPT, encoding='utf-8')
        process.finish()
        self.assertEqual(self.job._timer.interval(), 45000)
        return self.process

    def finish_title(self, title=TITLE, events=EVENTS):
        self.job._root.joinpath('title.json').write_text(json.dumps({'title': title}), encoding='utf-8')
        self.process.finish(events)

    def assert_failure(self, text=None):
        self.assertEqual(len(self.results), 1)
        title, error = self.results[0]
        self.assertEqual(title, '')
        self.assertTrue(error)
        if text:
            self.assertIn(text, error)
        self.assertFalse(self.job._timer.isActive())
        self.assertIsNone(self.job._resources.temp)

    def test_success_is_async_exactly_once_and_never_renames(self):
        process = self.reach_title()
        root = self.job._root
        self.assertTrue(root.exists())
        self.assertTrue(process.input_closed)
        self.finish_title()
        self.assertEqual(self.results, [(TITLE, '')])
        self.assertFalse(root.exists())
        self.assertEqual(self.video.read_bytes(), b'Not real media. Never processed.')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['ggml-base.en.bin', 'synthetic.mp4'])
        process.finished.emit(0, QProcess.NormalExit)
        self.job.cancel()
        self.assertEqual(len(self.results), 1)
        with self.assertRaises(RuntimeError):
            self.job.start(self.video)

    def test_verified_commands_pin_model_effort_priority_and_keep_transcript_off_argv(self):
        process = self.reach_title()
        args = process.arguments
        self.assertEqual(args[args.index('--model') + 1], 'gpt-6-luna')
        self.assertIn('model_reasoning_effort="medium"', args)
        self.assertIn('service_tier="priority"', args)
        self.assertEqual(args[args.index('--sandbox') + 1], 'read-only')
        for value in ('--ignore-user-config', '--strict-config', '--ephemeral',
                      'features.shell_tool=false', 'features.hooks=false', 'features.plugins=false',
                      'features.multi_agent_v2=false', 'web_search="disabled"'):
            self.assertIn(value, args)
        self.assertNotIn(str(self.video), args)
        self.assertNotIn(TRANSCRIPT, ' '.join(args))
        self.assertIn(json.dumps(TRANSCRIPT), process.input.decode())
        self.assertIn('untrusted quoted data', process.input.decode())
        self.assertEqual(args[-1], '-')
        audio = InertProcess.instances[1]
        self.assertEqual(audio.arguments[audio.arguments.index('-i') + 1], str(self.video))
        self.assertIn('-nostdin', audio.arguments)
        self.assertEqual(audio.arguments[audio.arguments.index('-protocol_whitelist') + 1], 'file,pipe')
        self.assertEqual(audio.arguments[audio.arguments.index('-t') + 1], '120')
        self.assertEqual(InertProcess.instances[2].arguments[1], str(self.model))
        self.assertEqual(process.parameters.flags, QProcess.UnixProcessFlag.CreateNewSession)

    def test_unavailable_capability_completes_without_process(self):
        with patch.object(titles, '_dependencies', side_effect=titles.TitleError('Need a local model.')):
            self.assertEqual(titles.local_title_capability(), (False, 'Need a local model.'))
            self.job.start(self.video)
            self.qt.processEvents()
        self.assertEqual(InertProcess.instances, [])
        self.assert_failure('local model')

    def test_available_capability_never_starts_a_helper(self):
        self.assertEqual(titles.local_title_capability(), (True, ''))
        self.assertEqual(InertProcess.instances, [])

    def test_cancel_before_queued_start_and_repeated_cancel(self):
        self.job.cancel()  # Before start is a no-op.
        self.job.start(self.video)
        self.job.cancel()
        self.qt.processEvents()
        self.job.cancel()
        self.assert_failure('cancelled')
        self.assertEqual(InertProcess.instances, [])

    def test_cancel_stops_cli_group_and_cleans_up_before_completion(self):
        process = self.reach_title()
        root = self.job._root
        self.job.cancel()
        self.assertTrue(process.killed)
        titles.os.killpg.assert_called_once()
        self.assertFalse(root.exists())
        self.assert_failure('cancelled')
        process.finished.emit(0, QProcess.NormalExit)
        self.assertEqual(len(self.results), 1)

    def test_timeout_kills_process_and_returns_manual_fallback(self):
        process = self.reach_title()
        self.job._timer.timeout.emit()
        self.assertTrue(process.killed)
        self.assert_failure('timed out')

    def test_parent_destruction_stops_helpers_and_removes_temp_files(self):
        process = self.reach_title()
        root = self.job._root
        self.parent.deleteLater()
        self.qt.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertTrue(process.killed)
        self.assertFalse(root.exists())
        # The job wrapper is deleted; avoid calling it from normal cleanup.
        self.job = self.parent = None

    def test_failed_process_diagnostics_do_not_leak(self):
        self.reach_title().finish(code=1, errors='Private transcript and account details')
        self.assert_failure('Codex title generation failed')
        self.assertNotIn('Private', self.results[0][1])

    def test_failed_start_has_one_completion_without_finished_signal(self):
        process = self.begin()
        process.running = False
        process.errorOccurred.emit(QProcess.FailedToStart)
        self.assert_failure('could not start')
        process.finished.emit(-1, QProcess.CrashExit)
        self.assertEqual(len(self.results), 1)

    def test_incompatible_cli_never_extracts_audio(self):
        self.begin().finish('old codex help')
        self.assert_failure('required safe execution options')
        self.assertEqual(len(InertProcess.instances), 1)

    def test_stdout_and_stderr_share_output_bound(self):
        process = self.begin()
        process.feed(b'x' * (titles.MAX_PROCESS_BYTES // 2))
        process.feed(errors=b'y' * (titles.MAX_PROCESS_BYTES // 2 + 1))
        self.assertTrue(process.killed)
        self.assert_failure('size limit')

    def test_empty_transcript_does_not_call_codex_generation(self):
        process = self.reach_transcript()
        self.job._root.joinpath('transcript.txt').write_text('  [silence]  ')
        process.finish()
        self.assert_failure('No usable speech')
        self.assertEqual(len(InertProcess.instances), 3)

    def test_oversized_transcript_does_not_call_codex_generation(self):
        process = self.reach_transcript()
        self.job._root.joinpath('transcript.txt').write_bytes(b'x' * (titles.MAX_TRANSCRIPT_BYTES + 1))
        process.finish()
        self.assert_failure('size limit')
        self.assertEqual(len(InertProcess.instances), 3)

    def test_stale_helper_signals_cannot_advance_pipeline(self):
        old = self.begin()
        old.finish(HELP)
        current = self.process
        old.finished.emit(0, QProcess.NormalExit)
        old.feed(b'x' * (titles.MAX_PROCESS_BYTES + 1))
        self.assertIs(self.process, current)
        self.assertEqual(len(InertProcess.instances), 2)
        self.assertEqual(self.results, [])

    def test_missing_recording_fails_without_process(self):
        self.video.unlink()
        self.job.start(self.video)
        self.qt.processEvents()
        self.assert_failure('no longer available')
        self.assertEqual(InertProcess.instances, [])

    def test_failed_turn_cannot_use_an_existing_title_file(self):
        self.reach_title()
        self.finish_title(events='{"type":"turn.failed","error":{"message":"model unavailable"}}')
        self.assert_failure('could not generate')

    def test_reported_model_fallback_is_rejected(self):
        self.reach_title()
        self.finish_title(events='{"type":"turn.completed","model":"different-model"}')
        self.assert_failure('unexpected model')

    def test_tool_actions_are_rejected(self):
        self.reach_title()
        self.finish_title(events='{"type":"item.completed","item":{"type":"command_execution"}}\n' + EVENTS)
        self.assert_failure('tool action')


class LocalTitleValidationTests(unittest.TestCase):
    def test_title_requires_a_specific_bounded_single_line(self):
        self.assertEqual(titles._title(json.dumps({'title': TITLE})), TITLE)
        for value in ('', 'Screen recording', 'A new screen recording', 'A quick demo',
                      'No speech', 'Title: Duplicate order imports', '# Duplicate order imports',
                      'Duplicate\norder imports', 'Duplicate/order imports',
                      'Duplicate order\u202e imports', 'x ' * 50):
            with self.subTest(value=value), self.assertRaises(titles.TitleError):
                titles._title(json.dumps({'title': value}))
        for value in ('{broken', 'null', '[]', '{"title":1}', '{"title":"Useful order title","other":1}'):
            with self.subTest(value=value), self.assertRaises(titles.TitleError):
                titles._title(value)

    def test_dependency_discovery_has_no_auth_or_model_download(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / 'model.bin'
            model.write_bytes(b'fixture')
            with patch.dict(os.environ, {'UNTANGLE_WHISPER_MODEL': str(model)}), \
                    patch.object(titles.shutil, 'which', side_effect=lambda name: '/bin/' + name):
                self.assertEqual(titles._dependencies(), ('/bin/ffmpeg', '/bin/whisper-cli', '/bin/codex', model))
            model.unlink()
            with patch.dict(os.environ, {'UNTANGLE_WHISPER_MODEL': str(model)}), \
                    patch.object(titles.shutil, 'which', side_effect=lambda name: '/bin/' + name):
                self.assertFalse(titles.local_title_capability()[0])


if __name__ == '__main__':
    unittest.main()
