"""Synthetic export and recovery checks. No capture devices or audio output."""
import errno
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from untangle.editing import ExportCancelled, RecordingProject, _save


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg tools unavailable')
class ExportChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'original.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=size=160x90:rate=10', '-t', '2', '-an', '-c:v', 'libx264',
                        str(self.source)], check=True)
        self.original = self.source.read_bytes()
        self.project = RecordingProject(self.source)

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_trim_exports_actual_shorter_versions_and_keeps_original(self):
        first = self.project.export(.5, 1.5)
        second = self.project.export(0, 1)
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())
        duration = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
                                           'format=duration', '-of', 'csv=p=0', str(first)], text=True)
        self.assertAlmostEqual(float(duration), 1., delta=.15)
        self.assertEqual([v['status'] for v in self.project.history()], ['completed', 'completed'])
        metadata = json.loads(self.project.metadata.read_text())
        self.assertFalse(any(track['editable_layout'] for track in metadata['tracks']))

    def test_invalid_range_and_cancel_do_not_publish(self):
        for start, end in ((2, 1), (-1, 0), (0, float('nan')), (3, 0), (0, 10)):
            with self.assertRaises(ValueError):
                self.project.export(start, end)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ExportCancelled):
            self.project.export(0, 1, cancel)
        self.assertFalse(list(self.project.directory.glob('export-*.mp4')))

    def test_cancellation_during_encoder_stops_process_and_next_attempt_gets_new_version(self):
        cancel = threading.Event()
        real_popen = subprocess.Popen

        def start_encoder(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            cancel.set()
            return process

        with patch('untangle.editing.subprocess.Popen', side_effect=start_encoder):
            # subprocess.run for ffprobe uses Popen too, so cancel can arrive during probing.
            with self.assertRaises(ExportCancelled):
                self.project.export(0, 1, cancel)
        self.assertFalse(list(self.project.directory.glob('export-*.mp4')))
        self.assertFalse(list(self.project.directory.glob('*.partial.mp4')))
        output = self.project.export(0, 1)
        self.assertEqual(output.name, 'export-v0002.mp4')
        self.assertEqual(self.project.history()[0]['status'], 'cancelled')

    def test_disk_full_at_publish_leaves_source_and_recoverable_history(self):
        with patch('untangle.editing.os.link', side_effect=OSError(errno.ENOSPC, 'No space left')):
            with self.assertRaises(OSError):
                self.project.export(0, 1)
        self.assertFalse(list(self.project.directory.glob('export-*.mp4')))
        self.assertEqual(self.project.history()[0]['status'], 'failed')
        self.assertEqual(self.project.export(0, 1).name, 'export-v0002.mp4')

    def test_metadata_failure_after_publish_retains_recovered_export(self):
        calls = 0

        def save(path, data):
            nonlocal calls
            calls += 1
            if calls >= 2:
                raise OSError(errno.ENOSPC, 'No space left')
            return _save(path, data)

        with patch('untangle.editing._save', side_effect=save):
            with self.assertRaises(OSError):
                self.project.export(0, 1)
        self.assertTrue(self.project.output(1).is_file())
        self.assertEqual(self.project.history()[0]['status'], 'recovered')
        self.assertEqual(self.project.export(0, 1).name, 'export-v0002.mp4')

    def test_interrupted_partial_recovers_without_reusing_number(self):
        self.project.history()
        data = json.loads(self.project.metadata.read_text())
        data['versions'].append({'number': 1, 'start': 0, 'end': 1, 'status': 'pending'})
        _save(self.project.metadata, data)
        (self.project.directory / '.export-v0001.partial.mp4').write_bytes(b'partial')
        self.assertEqual(self.project.history()[0]['status'], 'interrupted')
        self.assertFalse(list(self.project.directory.glob('*.partial.mp4')))
        self.assertEqual(self.project.export(0, 1).name, 'export-v0002.mp4')

    def test_changed_source_refuses_existing_project(self):
        self.project.history()
        import os
        stat = self.source.stat()
        os.utime(self.source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10000))
        with self.assertRaisesRegex(ValueError, 'original changed'):
            self.project.export(0, 1)

    def test_busy_project_refuses_parallel_export(self):
        with self.project._lock():
            with self.assertRaisesRegex(RuntimeError, 'Another export'):
                self.project.export(0, 1)


class EditingDialogChecks(unittest.TestCase):
    def test_dialog_is_silent_validates_range_and_keeps_controls_available(self):
        from PySide6.QtWidgets import QApplication
        from untangle.editing_dialog import EditingDialog
        qt = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'take.mp4'
            source.write_bytes(b'synthetic')
            dialog = EditingDialog(source)
            dialog.start_time.setValue(10)
            dialog.end_time.setValue(5)
            with patch('untangle.editing_dialog.ExportWorker') as worker:
                dialog.export_button.click()
                worker.assert_not_called()
            self.assertIn('later than start', dialog.status.text())
            self.assertTrue(dialog.export_button.isEnabled())
            dialog.reject()
            dialog.deleteLater()
            qt.processEvents()

    def test_close_cancels_active_export_and_releases_worker_before_closing(self):
        import time
        from PySide6.QtWidgets import QApplication
        from untangle.editing_dialog import EditingDialog
        qt = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'take.mp4'
            source.write_bytes(b'synthetic')
            dialog = EditingDialog(source)
            entered = threading.Event()

            def export(start, end, cancel):
                entered.set()
                cancel.wait(3)
                raise ExportCancelled('Export cancelled. The original is unchanged.')

            with patch.object(dialog.project, 'export', side_effect=export):
                dialog.export_button.click()
                self.assertTrue(entered.wait(2))
                dialog.reject()
                self.assertIsNotNone(dialog.worker)
                deadline = time.monotonic() + 3
                while dialog.worker is not None and time.monotonic() < deadline:
                    qt.processEvents()
                    time.sleep(.01)
                self.assertIsNone(dialog.worker)
                self.assertIn('cancelled', dialog.status.text())
            self.assertEqual(source.read_bytes(), b'synthetic')
            dialog.deleteLater()
            qt.processEvents()
