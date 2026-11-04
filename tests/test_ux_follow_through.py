"""Recovery navigation with inert capture, audio and process boundaries."""
from pathlib import Path
from unittest.mock import patch
import unittest

import test_ui_clickthrough as ui


class FollowThroughTests(unittest.TestCase):
    def setUp(self):
        self.case = ui.ClearlineClickthrough()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.w = self.case.window

    def test_review_tracks_final_name_and_stays_silent(self):
        w = self.w
        path = Path(self.case.temp.name) / 'final title.mp4'
        path.write_bytes(b'synthetic video')
        with patch.object(w, 'open_recordings') as library:
            w.complete_saved_video(path, '', prompt=False)
            self.assertEqual(w._review_path, path)
            library.assert_not_called()
            w.review_saved_recording()
            library.assert_called_once_with(path)
        renamed = path.with_name('renamed.mp4')
        path.rename(renamed)
        w.recording_renamed(str(path), str(renamed))
        self.assertEqual(w._review_path, renamed)
        renamed.unlink()
        with patch.object(w, 'open_recordings') as library:
            w.review_saved_recording()
            library.assert_not_called()
        self.assertTrue(w.review_saved_button.isHidden())

    def test_preflight_and_shortcuts_do_not_change_configuration(self):
        w = self.w
        before = (w.camera.currentData(), w.microphone.currentData())
        summary = w.preflight_summary()
        self.assertIn('Microphone:', summary)
        self.assertIn('Desktop audio:', summary)
        self.assertIn('does not verify saved speech', summary)
        self.assertIn('Ctrl+Shift+F9', w.shortcut_reference.text())
        self.assertIn('Right-click', w.shortcut_reference.text())
        self.assertEqual(before, (w.camera.currentData(), w.microphone.currentData()))

    def test_audience_unknown_and_permission_failure_stay_explicit(self):
        w = self.w
        path = Path(self.case.temp.name) / 'sharing.mp4'
        path.write_bytes(b'synthetic')
        w._upload_file = path
        w._upload_url = 'https://www.loom.com/share/' + 'a' * 32
        w.upload_store.update(path, status='uploaded', visibility='workspace',
                              visibility_verified=True, title_warning='Title could not be set')
        w.update_audience_status()
        self.assertIn('Loom workspace', w.upload_audience.text())
        self.assertIn('command accepted', w.upload_audience.text())
        w.upload_store.update(path, visibility_warning='Permission check failed')
        w.update_audience_status()
        self.assertIn('UNVERIFIED', w.upload_audience.text())
