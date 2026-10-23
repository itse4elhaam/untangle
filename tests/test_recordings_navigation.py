"""Synthetic library navigation with no player, processes, capture, or devices."""
from contextlib import ExitStack
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtWidgets import QApplication, QPushButton, QStackedWidget, QWidget

from untangle import app
from untangle.recordings import Recordings


qt = QApplication.instance() or QApplication([])


class LibraryNavigationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.player = MagicMock()
        self.player.source.return_value = QUrl()
        self.player.duration.return_value = self.player.position.return_value = 0
        self.audio = MagicMock()
        self.audio.volume.return_value = .5
        self.audio.isMuted.return_value = False
        self.stack.enter_context(patch('untangle.recordings.QMediaPlayer', return_value=self.player))
        self.stack.enter_context(patch('untangle.recordings.QAudioOutput', return_value=self.audio))
        self.stack.enter_context(patch('untangle.recordings.QVideoWidget', QWidget))
        self.stack.enter_context(patch('untangle.recordings.shutil.which', return_value=None))
        self.library = Recordings(self.directory)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.library)
        self.recorder = QWidget()
        self.pages.addWidget(self.recorder)
        self.pages.resize(1000, 700)
        self.pages.show()
        qt.processEvents()
        self.addCleanup(self.close_pages)
        self.process = self.library.thumbnail_process = MagicMock()
        self.process.state.return_value = QProcess.Running
        self.process.readAllStandardOutput.return_value = b''
        self.blocked_ms = 0

        def wait_for_finished(timeout):
            # Account for the whole timeout without spending it on the test thread.
            self.blocked_ms += timeout
            return False

        self.process.waitForFinished.side_effect = wait_for_finished
        self.library.thumbnail_key = ('old.mp4', 1, 1)
        self.library.thumbnail_queue = [('queued.mp4', 2, 2)]
        self.library.thumbnail_timer.start(5000)

    def close_pages(self):
        self.process.state.return_value = QProcess.NotRunning
        self.library.stop_thumbnails()
        self.pages.close()
        self.pages.deleteLater()
        qt.processEvents()

    def test_back_button_does_not_wait_for_thumbnail_exit_or_reconfigure_valid_scene(self):
        window = SimpleNamespace(
            recordings=self.library, pages=self.pages, recorder_page=self.recorder,
            refresh_upload_link=MagicMock(), preview=QWidget(), tray_record=QPushButton(),
            engine=MagicMock(), configure=MagicMock(), restore_preview=MagicMock(),
            configuration_valid=True, _configure_pending=False,
        )
        self.library.back_requested.connect(lambda: app.Window.back_to_recorder(window))
        self.player.reset_mock()
        with patch.object(app.QTimer, 'singleShot'):
            self.library.back.click()
        self.assertEqual(self.blocked_ms, 0, 'Back blocks the UI waiting for thumbnail exit')
        self.assertIs(self.pages.currentWidget(), self.recorder)
        window.configure.assert_not_called()
        self.process.kill.assert_called()
        self.assertEqual(self.library.thumbnail_queue, [])
        self.assertIsNone(self.library.thumbnail_key)
        self.assertFalse(self.library.thumbnail_timer.isActive())
        self.player.stop.assert_called()
        self.player.setSource.assert_called_with(QUrl())
        self.assertIs(self.library.stage.currentWidget(), self.library.placeholder)
        self.assertFalse(self.library.toggle.isEnabled())
        self.assertFalse(self.library.seek.isEnabled())
        self.process.state.return_value = QProcess.NotRunning
        self.library.thumbnail_finished(-1, QProcess.CrashExit)
        self.process.start.assert_not_called()
        self.assertEqual(len(self.library.thumbnail_cache), 0)

    def test_refresh_waits_for_cancelled_child_signal_before_starting_new_thumbnail(self):
        clip = self.directory / 'new.mp4'
        clip.touch()
        self.library.ffmpeg = '/synthetic/ffmpeg'
        self.library.refresh()
        self.assertEqual(self.blocked_ms, 0)
        self.process.start.assert_not_called()
        self.assertIsNone(self.library.thumbnail_key)
        self.assertEqual(len(self.library.thumbnail_queue), 1)
        self.process.state.return_value = QProcess.NotRunning
        self.library.thumbnail_finished(-1, QProcess.CrashExit)
        self.process.start.assert_called_once()
        self.assertEqual(self.library.thumbnail_key[0], str(clip))
        self.assertEqual(self.library.thumbnail_queue, [])
        self.assertTrue(self.library.thumbnail_timer.isActive())
        self.assertEqual(len(self.library.thumbnail_cache), 0)

    def test_settings_button_requests_settings_and_hidden_theme_api_still_emits(self):
        settings = MagicMock()
        themes = []
        self.library.settings_requested.connect(settings)
        self.library.theme_requested.connect(themes.append)
        self.assertTrue(self.library.settings_button.isVisible())
        self.assertTrue(self.library.theme_choice.isHidden())
        self.assertIs(self.library.theme_choice.parent(), self.library)
        self.library.settings_button.click()
        settings.assert_called_once_with()
        self.library.theme_choice.setCurrentIndex(1 - self.library.theme_choice.currentIndex())
        self.assertEqual(themes, [self.library.theme_choice.currentData()])


if __name__ == '__main__':
    unittest.main()
