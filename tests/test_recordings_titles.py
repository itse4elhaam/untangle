"""Title editing with temporary files and mocked media playback, never capture."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication
from untangle.recordings import Recordings
from untangle.naming import recording_title
from untangle.app import Window

qt = QApplication.instance() or QApplication([])


class RecordingTitleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'Earlier take.mkv'
        self.source.write_bytes(b'synthetic placeholder')
        self.dialog = Recordings(self.root)
        # File action tests need no decoder or output device.
        self.dialog.player.setAudioOutput(None)
        self.play = patch.object(self.dialog.player, 'play')
        self.set_source = patch.object(self.dialog.player, 'setSource')
        self.play.start()
        self.source_mock = self.set_source.start()
        self.dialog.files.setCurrentRow(0)

    def tearDown(self):
        self.dialog.reject()
        self.play.stop()
        self.set_source.stop()
        self.dialog.deleteLater()
        qt.processEvents()
        self.temp.cleanup()

    def rename(self, title, accepted=True):
        def prompt(parent, path, rename):
            if accepted:
                try:
                    return rename(title)
                except (OSError, ValueError):
                    pass
            return None
        with patch('untangle.recordings.prompt_recording_name', side_effect=prompt):
            self.dialog.rename_selected()

    def test_rename_releases_player_keeps_visible_selection_and_emits_paths(self):
        self.dialog.search.setText('Earlier')
        changes = []
        self.dialog.recording_renamed.connect(lambda old, new: changes.append((old, new)))
        from untangle.naming import rename_recording
        def check_released(path, title):
            self.assertTrue(self.dialog.player.source().isEmpty())
            self.source_mock.assert_called()
            self.assertTrue(self.source_mock.call_args.args[0].isEmpty())
            return rename_recording(path, title)
        with patch('untangle.recordings.rename_recording', side_effect=check_released):
            self.rename('My 演示')
        target = self.root / 'My 演示.mkv'
        self.assertEqual(self.dialog.selected_path(), target)
        self.assertFalse(self.dialog.files.currentItem().isHidden())
        self.assertEqual(self.dialog.search.text(), '')
        self.assertIn(recording_title(target), self.dialog.files.currentItem().text())
        self.assertEqual(changes, [(str(self.source), str(target))])
        self.assertTrue(self.dialog.upload.isEnabled())
        self.assertTrue(self.dialog.copy.isEnabled())
        self.assertTrue(self.dialog.delete.isEnabled())

    def test_cancel_and_error_keep_file_and_selection(self):
        self.rename('changed', False)
        self.assertEqual(self.dialog.selected_path(), self.source)
        with patch('untangle.recordings.rename_recording', side_effect=PermissionError('read only')):
            self.rename('changed')
        self.assertEqual(self.dialog.selected_path(), self.source)
        self.assertTrue(self.source.exists())
        self.assertIn('Could not rename', self.dialog.message.text())
        self.assertTrue(self.dialog.toggle.isEnabled())
        self.assertTrue(self.source_mock.call_args.args[0].isEmpty())
        self.rename('')
        self.assertTrue(self.source.exists())

    def test_busy_and_modal_state_change_block_rename(self):
        self.dialog.deletion_blocked = lambda path: True
        self.dialog.update_actions()
        self.assertFalse(self.dialog.rename.isEnabled())
        with patch('untangle.recordings.prompt_recording_name') as prompt:
            self.dialog.rename_selected()
        prompt.assert_not_called()
        self.dialog.deletion_blocked = lambda path: False
        def became_busy(parent, path, rename):
            self.dialog.deletion_blocked = lambda path: True
            with self.assertRaisesRegex(ValueError, 'in use'):
                rename('Changed')
            return None
        with patch('untangle.recordings.prompt_recording_name', side_effect=became_busy):
            self.dialog.rename_selected()
        self.assertTrue(self.source.exists())
        self.assertIn('in use', self.dialog.message.text())

    def test_app_handler_changes_only_matching_latest_reference(self):
        window = MagicMock(last_file=self.source)
        target = self.root / 'renamed.mkv'
        Window.recording_renamed(window, str(self.source), str(target))
        window.set_last.assert_called_once_with(str(target))
        window.set_last.reset_mock()
        Window.recording_renamed(window, str(self.root / 'other.mp4'), str(target))
        window.set_last.assert_not_called()
