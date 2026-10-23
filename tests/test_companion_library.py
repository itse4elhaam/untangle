"""Companion library checks with synthetic files and detached playback output."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QBuffer, QIODevice, QProcess, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from untangle.recordings import Recordings

qt = QApplication.instance() or QApplication([])


class CompanionLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'First explanation.mp4'
        self.path.touch()
        # Individual tests enable only mocked or synthetic file decoding.
        with patch('untangle.recordings.shutil.which', return_value=None):
            self.library = Recordings(self.root)
        self.library.player.setAudioOutput(None)

    def tearDown(self):
        self.library.reject()
        self.library.deleteLater()
        qt.processEvents()
        self.temp.cleanup()

    def test_selection_refresh_and_search_never_start_playback(self):
        with patch.object(self.library.player, 'play') as play:
            self.library.files.setCurrentRow(0)
            self.assertEqual(self.library.selected_title.text(), 'First explanation')
            self.assertIn('MP4', self.library.metadata.text())
            self.assertTrue(self.library.player.source().isEmpty())
            self.assertTrue(self.library.toggle.isEnabled())
            self.library.refresh(self.path)
            self.library.search.setText('explanation')
            self.assertEqual(self.library.selected_path(), self.path)
            self.library.search.setText('missing')
            self.assertIsNone(self.library.selected_path())
            self.assertFalse(self.library.toggle.isEnabled())
            play.assert_not_called()

    def test_only_explicit_play_loads_selected_file(self):
        self.library.files.setCurrentRow(0)
        with patch.object(self.library.player, 'play') as play, patch.object(self.library.player, 'setSource') as source:
            self.library.toggle.click()
            self.assertEqual(source.call_args.args[0].toLocalFile(), str(self.path))
            play.assert_called_once()

    def test_theme_choice_emits_preference_without_local_palette(self):
        requested = []
        self.library.theme_requested.connect(requested.append)
        for name in ('light', 'dark'):
            self.library.theme_choice.setCurrentIndex(self.library.theme_choice.findData(name))
        self.assertEqual(requested[-1], 'dark')
        self.assertEqual(self.library.styleSheet(), '')
        self.assertEqual(self.library.files.objectName(), 'recordingFiles')

    def test_missing_file_before_play_preserves_file_actions_guard(self):
        self.library.files.setCurrentRow(0)
        self.path.unlink()
        with patch.object(self.library.player, 'play') as play:
            self.library.toggle.click()
            play.assert_not_called()
        self.assertIn('missing', self.library.message.text())
        self.assertFalse(self.library.copy.isEnabled())

    def test_thumbnail_cache_is_bounded_and_does_not_replace_status(self):
        self.library.files.setCurrentRow(0)
        for index in range(48):
            self.library.thumbnail_cache[(str(index), 0, 0)] = QPixmap(1, 1)
        key = self.library.files.currentItem().data(Qt.UserRole + 1)
        self.library.thumbnail_key = key
        self.library.thumbnail_queue.clear()
        pixmap = QPixmap(16, 9)
        pixmap.fill(Qt.blue)
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        pixmap.save(buffer, 'PNG')
        self.library.message.setText('File path copied.')
        with patch.object(self.library.thumbnail_process, 'readAllStandardOutput', return_value=buffer.data()):
            self.library.thumbnail_finished(0, QProcess.NormalExit)
        self.assertEqual(len(self.library.thumbnail_cache), 48)
        self.assertIn(key, self.library.thumbnail_cache)
        self.assertNotIn(('0', 0, 0), self.library.thumbnail_cache)
        self.assertIs(self.library.stage.currentWidget(), self.library.poster)
        self.assertEqual(self.library.message.text(), 'File path copied.')
        self.assertTrue(self.library.player.source().isEmpty())

    def test_refresh_invalidates_thumbnail_when_file_changes(self):
        key = self.library.files.item(0).data(Qt.UserRole + 1)
        self.library.thumbnail_cache[key] = QPixmap(16, 9)
        self.path.write_bytes(b'changed synthetic file')
        self.library.refresh(self.path)
        self.assertNotEqual(self.library.files.currentItem().data(Qt.UserRole + 1), key)
        self.assertIs(self.library.stage.currentWidget(), self.library.placeholder)
        self.assertTrue(self.library.player.source().isEmpty())

    def test_poster_fits_after_splitter_resize(self):
        key = self.library.files.item(0).data(Qt.UserRole + 1)
        self.library.thumbnail_cache[key] = QPixmap(384, 216)
        self.library.resize(960, 760)
        self.library.show()
        qt.processEvents()
        self.library.files.setCurrentRow(0)
        self.library.body.setSizes([480, 360])
        qt.processEvents()
        self.assertLessEqual(self.library.poster.pixmap().width(), self.library.stage.width())
        self.assertLessEqual(self.library.poster.pixmap().height(), self.library.stage.height())

    def test_thumbnail_failure_leaves_file_actions_available(self):
        self.library.files.setCurrentRow(0)
        self.library.thumbnail_queue.clear()
        self.library.thumbnail_key = self.library.files.currentItem().data(Qt.UserRole + 1)
        with patch.object(self.library.thumbnail_process, 'readAllStandardOutput', return_value=b''):
            self.library.thumbnail_finished(1, QProcess.NormalExit)
        self.assertTrue(self.library.copy.isEnabled())
        self.assertTrue(self.library.toggle.isEnabled())
        self.assertTrue(self.path.exists())
        self.assertIs(self.library.stage.currentWidget(), self.library.placeholder)

    def test_thumbnail_queue_bound_protocol_and_cleanup(self):
        for index in range(60):
            (self.root / f'take {index}.mkv').touch()
        self.library.refresh()
        self.assertLessEqual(len(self.library.thumbnail_queue), 48)
        self.library.ffmpeg = '/synthetic/ffmpeg'
        with patch.object(self.library.thumbnail_process, 'start') as start:
            self.library.start_thumbnail()
        arguments = start.call_args.args[1]
        self.assertEqual(arguments[arguments.index('-protocol_whitelist') + 1], 'file,pipe')
        self.assertIn('-an', arguments)
        self.assertTrue(self.library.thumbnail_timer.isActive())
        with (patch.object(self.library.thumbnail_process, 'state', return_value=QProcess.Running),
              patch.object(self.library.thumbnail_process, 'kill') as kill,
              patch.object(self.library.thumbnail_process, 'waitForFinished', return_value=True) as wait):
            self.library.reject()
        kill.assert_called_once()
        wait.assert_called_once_with(1000)
        self.assertEqual(self.library.thumbnail_queue, [])
        self.assertIsNone(self.library.thumbnail_key)
        self.assertFalse(self.library.thumbnail_timer.isActive())

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg required for synthetic thumbnail decoding')
    def test_real_thumbnail_from_silent_synthetic_video_without_player_loading(self):
        self.path.unlink()
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                        '-i', 'color=c=blue:size=160x90', '-t', '0.2', '-an',
                        '-c:v', 'libx264', str(self.path)], check=True)
        self.library.ffmpeg = shutil.which('ffmpeg')
        self.library.refresh(self.path)
        deadline = time.monotonic() + 5
        while not self.library.thumbnail_cache and time.monotonic() < deadline:
            qt.processEvents()
            time.sleep(.01)
        self.assertEqual(len(self.library.thumbnail_cache), 1)
        self.assertIs(self.library.stage.currentWidget(), self.library.poster)
        self.assertTrue(self.library.player.source().isEmpty())
        self.assertTrue(self.library.toggle.isEnabled())
