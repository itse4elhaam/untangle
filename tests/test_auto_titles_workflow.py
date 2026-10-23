"""Recording-name integration, with no processes, media, or inference."""
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal
from untangle import app
import test_app as fixture


class TitleJob(QObject):
    finished = Signal(str, str)

    def start(self, path):
        self.path = path

    def cancel(self):
        self.finished.emit('', 'Canceled')


class AutoTitleWorkflowTests(unittest.TestCase):
    setUp = fixture.AppChecks.setUp
    tearDown = fixture.AppChecks.tearDown

    def begin(self):
        path = self.root / 'saved.mp4'
        path.write_bytes(b'synthetic recording')
        self.window.prefs.setValue('auto_upload', True)
        self.window.auto_titles.setChecked(True)
        with patch.object(app, 'local_title_capability', return_value=(True, '')):
            self.window.finish_save(path, '')
        return path, self.window._title_job

    def test_generated_title_skips_prompt_and_uploads_renamed_file(self):
        with patch.object(app, 'LocalTitleJob', TitleJob), \
                patch.object(app, 'prompt_recording_name') as prompt, \
                patch.object(self.window, 'upload') as upload:
            path, job = self.begin()
            self.assertTrue(self.window.busy)
            upload.assert_not_called()
            prompt.assert_not_called()
            job.finished.emit('Database migration walkthrough', '')
            prompt.assert_not_called()
            upload.assert_called_once_with()
        self.assertEqual(self.window.last_file.name, 'Database migration walkthrough.mp4')
        self.assertEqual(self.window.last_file.read_bytes(), b'synthetic recording')
        self.assertFalse(path.exists())
        self.assertFalse(self.window.busy)

    def test_failed_generation_and_manual_cancel_keep_file(self):
        with patch.object(app, 'LocalTitleJob', TitleJob), \
                patch.object(app, 'prompt_recording_name', return_value=None) as prompt, \
                patch.object(self.window, 'upload') as upload:
            path, job = self.begin()
            job.finished.emit('', 'No usable speech')
            prompt.assert_called_once()
            upload.assert_called_once_with()
        self.assertEqual(self.window.last_file, path)
        self.assertTrue(path.is_file())
        self.assertFalse(self.window.busy)

    def test_skip_generation_opens_manual_name_once(self):
        with patch.object(app, 'LocalTitleJob', TitleJob), \
                patch.object(app, 'prompt_recording_name', return_value=None) as prompt, \
                patch.object(self.window, 'upload'):
            path, job = self.begin()
            self.window.cancel_automatic_title()
            job.finished.emit('Late stale generated title', '')
            prompt.assert_called_once()
        self.assertEqual(self.window.last_file, path)
        self.assertTrue(self.window.cancel_title_button.isHidden())

    def test_replaced_file_is_never_renamed_or_uploaded(self):
        with patch.object(app, 'LocalTitleJob', TitleJob), \
                patch.object(app, 'prompt_recording_name') as prompt, \
                patch.object(self.window, 'upload') as upload:
            path, job = self.begin()
            replacement = path.with_suffix('.new')
            replacement.write_bytes(b'replacement')
            replacement.replace(path)
            job.finished.emit('Original recording title', '')
            prompt.assert_not_called()
            upload.assert_not_called()
        self.assertEqual(path.read_bytes(), b'replacement')
        self.assertIn('changed while naming', self.window.status.text())

    def test_close_cancels_naming_without_prompt_or_upload(self):
        with patch.object(app, 'LocalTitleJob', TitleJob), \
                patch.object(app, 'prompt_recording_name') as prompt, \
                patch.object(self.window, 'upload') as upload:
            path, job = self.begin()
            self.window.close()
            self.assertTrue(self.window._closing)
            self.assertIsNone(self.window._title_job)
            job.finished.emit('Stale title after closing', '')
            prompt.assert_not_called()
            upload.assert_not_called()
        self.assertTrue(path.is_file())
