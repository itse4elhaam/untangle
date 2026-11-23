"""Recording-name integration, with no processes, media, or inference."""
import unittest
from unittest.mock import MagicMock, patch

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

    def test_old_ai_defaults_reset_once_and_new_opt_in_survives_restart(self):
        self.window.prefs.remove('manual_titles_default_v1')
        self.window.prefs.setValue('auto_titles', True)
        self.window.prefs.setValue('loom_auto_titles', True)
        self.window.close()
        self.window = app.Window()
        self.assertFalse(self.window.auto_titles.isChecked())
        self.assertFalse(self.window.prefs.value('loom_auto_titles', type=bool))
        self.window.auto_titles.setChecked(True)
        self.window.prefs.setValue('loom_auto_titles', True)
        self.window.close()
        self.window = app.Window()
        self.assertTrue(self.window.auto_titles.isChecked())
        self.assertTrue(self.window.prefs.value('loom_auto_titles', type=bool))

    def begin(self):
        path = self.root / 'saved.mp4'
        path.write_bytes(b'synthetic recording')
        self.window._take_sharing = None  # Local-only naming keeps its original workflow.
        self.window.auto_titles.setChecked(True)
        with patch.object(app, 'local_title_capability', return_value=(True, '')):
            self.window.finish_save(path, '')
        return path, self.window._title_job

    def test_generated_title_skips_prompt_and_renames_local_file(self):
        with patch.object(app, 'LocalTitleJob', TitleJob), \
                patch.object(app, 'prompt_recording_name') as prompt, \
                patch.object(self.window, 'upload') as upload:
            path, job = self.begin()
            self.assertTrue(self.window.busy)
            upload.assert_not_called()
            prompt.assert_not_called()
            job.finished.emit('Database migration walkthrough', '')
            prompt.assert_not_called()
            upload.assert_not_called()
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
            upload.assert_not_called()
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

    def test_shared_take_can_be_named_after_the_link_is_ready(self):
        w = self.window
        path = self.root / 'saved.mp4'
        path.write_bytes(b'synthetic')
        w._upload_file = path
        w._upload_identity = w.upload_store.file_identity(path)
        w.upload_store.update(path, status='uploaded', url='https://www.loom.com/share/abc123')
        w._upload_generate_name = True
        w.set_last(path)
        done = []
        with patch.object(app, 'LocalTitleJob', TitleJob), patch.object(app, 'local_title_capability', return_value=(True, '')):
            w.finish_auto_upload_naming(lambda: done.append(w._upload_title))
            self.assertEqual(w._upload_name_job.path, path)
            w._upload_name_job.finished.emit('Project walkthrough', '')
        renamed = self.root / 'Project walkthrough.mp4'
        self.assertEqual(done, ['Project walkthrough'])
        self.assertEqual(w._upload_file, renamed)
        self.assertEqual(w.upload_store.get(renamed)['url'], 'https://www.loom.com/share/abc123')
        self.assertEqual(w.last_file, renamed)

    def test_metadata_move_failure_keeps_verified_link_during_background_rename(self):
        w = self.window
        path = self.root / 'local.mp4'
        path.write_bytes(b'synthetic')
        w._upload_file = path
        w._upload_identity = w.upload_store.file_identity(path)
        w._upload_url = 'https://www.loom.com/share/abc123'
        w._upload_generate_name = True
        w._upload_setting_title = True
        with patch.object(app, 'LocalTitleJob', TitleJob), patch.object(app, 'local_title_capability', return_value=(True, '')), \
                patch.object(w.upload_store, 'rename', side_effect=OSError('read-only')):
            w.finish_auto_upload_naming(w.refresh_upload_link)
            w._upload_name_job.finished.emit('Shared video', '')
        self.assertEqual(w._upload_url, 'https://www.loom.com/share/abc123')
        self.assertTrue(w._upload_file.exists())

    def test_background_naming_keeps_file_in_use_by_player(self):
        w = self.window
        path = self.root / 'playing.mp4'
        path.write_bytes(b'synthetic')
        w._upload_file = path
        w._upload_identity = w.upload_store.file_identity(path)
        w._upload_generate_name = True
        library = MagicMock()
        library.player.source.return_value = app.QUrl.fromLocalFile(str(path))
        with patch.object(w, 'recordings', library), patch.object(app, 'LocalTitleJob', TitleJob), \
                patch.object(app, 'local_title_capability', return_value=(True, '')):
            w.finish_auto_upload_naming(lambda: None)
            w._upload_name_job.finished.emit('Shared title', '')
        self.assertTrue(path.exists())
        self.assertEqual(w._upload_title, 'Shared title')
        library.refresh.assert_not_called()

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
