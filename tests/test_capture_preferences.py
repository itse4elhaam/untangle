"""Recorder choices across launches, with synthetic devices and isolated settings."""
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QRect, QSettings

from untangle import app as glint
from untangle.camera_devices import camera_ids
from untangle.camera_framing import load_framing
import test_ui_clickthrough as ui


class CapturePreferencesTests(unittest.TestCase):
    def setUp(self):
        self.case = ui.ClearlineClickthrough()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()

    def restart(self, cameras):
        self.case.close_window()
        with patch.object(glint, 'cameras', return_value=cameras):
            self.case.window = glint.Window()
        return self.case.window

    def test_missing_camera_retains_identity_until_reconnected_or_switched_off(self):
        w = self.case.window
        w.camera.setCurrentIndex(w.camera.findData('/dev/video-second'))
        w = self.restart([('Test camera', '/dev/video-second')])
        self.assertEqual(w.camera.currentIndex(), -1)
        self.assertIn('Second camera', w.camera.placeholderText())
        w.camera_toggle.click()
        self.assertEqual(w.camera.currentIndex(), -1)
        w.clean_microphone.click()
        self.assertEqual(w.prefs.value('camera'), 'Second camera')
        w = self.restart([('Second camera', '/dev/video-new')])
        self.assertEqual(w.camera.currentData(), '/dev/video-new')
        w.camera_toggle.click()
        w = self.restart([('Test camera', '/dev/video-test'), ('Second camera', '/dev/video-moved')])
        self.assertEqual(w.camera.currentText(), 'Camera off')
        w.camera_toggle.click()
        self.assertEqual(w.camera.currentData(), '/dev/video-moved')

    def test_stable_camera_ids_prefer_by_id_over_by_path(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            device = root / 'video8'
            device.touch()
            for prefix in ('by-id', 'by-path'):
                (root / prefix).mkdir()
                (root / prefix / 'camera-index0').symlink_to(device)
            self.assertEqual(camera_ids([('Camera', str(device))], root),
                             {str(device): str(root / 'by-id/camera-index0')})

    def test_unplugged_legacy_microphone_keeps_its_name_until_a_user_selects_an_input(self):
        w = self.case.window
        w.engine = None
        w.prefs.setValue('microphone', 'Portable mic')
        w.prefs.remove('microphone_id')
        w.restore_preferences()
        self.assertEqual(w.microphone.currentIndex(), -1)
        w.clean_microphone.click()
        self.assertEqual(w.prefs.value('microphone'), 'Portable mic')
        self.assertFalse(w.prefs.contains('microphone_id'))
        w.microphone.setCurrentIndex(0)
        self.assertEqual(w.prefs.value('microphone_id'), 'default')

    def test_cameras_with_the_same_label_use_their_stable_hardware_identity(self):
        devices = [('Webcam', '/dev/video0'), ('Webcam', '/dev/video2')]
        ids = {'/dev/video0': '/dev/v4l/by-id/first', '/dev/video2': '/dev/v4l/by-id/second'}
        with patch.object(glint, 'camera_ids', return_value=ids):
            w = self.restart(devices)
            w.camera.setCurrentIndex(w.camera.findData('/dev/video2'))
            with patch.object(w, 'camera_adjustments', SimpleNamespace(device='/dev/video2')):
                w.save_camera_image('Webcam', {'contrast': 40})
        reordered = {'/dev/video0': ids['/dev/video2'], '/dev/video2': ids['/dev/video0']}
        with patch.object(glint, 'camera_ids', return_value=reordered):
            w = self.restart(devices)
        self.assertEqual(w.camera.currentData(), '/dev/video0')
        self.assertEqual(w.saved_camera_image('/dev/video0', 'Webcam'), {'contrast': 40})
        self.assertIsNone(w.saved_camera_image('/dev/video2', 'Webcam'))
        with patch.object(glint, 'camera_ids', return_value={'/dev/video0': ids['/dev/video0']}):
            w = self.restart(devices[:1])
        self.assertEqual(w.camera.currentIndex(), -1)

    def test_crop_and_widget_coordinates_survive_the_on_disk_ini_representation(self):
        w = self.case.window
        w.camera_offset_dragged(.25, -.75)
        w.bubble.placement_changed.emit(.125, .875)
        # A second QSettings for the same path shares Qt's in-memory cache.
        copy = self.case.root / 'reopened.ini'
        copyfile(w.prefs.fileName(), copy)
        reopened = QSettings(str(copy), QSettings.IniFormat)
        self.assertEqual(load_framing(reopened, w.mode)[1], (.25, -.75))
        self.assertEqual(glint.Window.saved_camera_placement(SimpleNamespace(prefs=reopened)),
                         (.125, .875))

    def test_removed_display_never_becomes_another_choice_and_restores_after_reorder(self):
        w = self.case.window
        def screen(name):
            display = Mock()
            display.name.return_value = name
            display.geometry.return_value = QRect(0, 0, 1280, 720)
            display.devicePixelRatio.return_value = 1.
            return display
        left, right = screen('left'), screen('right')
        w.engine = None
        with patch.object(glint.QApplication, 'screens', return_value=[left, right]):
            w.populate_displays()
            w.screen.setCurrentIndex(1)
        self.assertEqual(w.prefs.value('screen_name'), 'right')
        with patch.object(glint.QApplication, 'screens', return_value=[left]):
            w.populate_displays()
            w.set_mode('screen')
            self.assertEqual(w.screen.currentIndex(), -1)
            self.assertEqual(w.prefs.value('screen_name'), 'right')
        with patch.object(glint.QApplication, 'screens', return_value=[right, left]):
            w.populate_displays()
            self.assertEqual(w.screen.currentData(), 0)
            self.assertIn('right', w.screen.currentText())

    def test_window_mode_forgets_target_and_retains_zoom_crop_and_placement(self):
        w = self.case.window
        w.set_mode('screen')
        w.capture_kind.setCurrentIndex(w.capture_kind.findData('window'))
        self.assertEqual(w.capture_window.currentData(), 4242)
        w.crop_drag_enabled.setChecked(True)
        w.zoom_amount.setCurrentIndex(w.zoom_amount.findData(2.5))
        w.bubble.placement_changed.emit(.25, .625)
        self.assertEqual(w.prefs.value('capture_kind'), 'window')
        self.assertEqual(w.prefs.value('zoom_amount'), '2.5×')
        w = self.restart([('Test camera', '/dev/video-test')])
        self.assertEqual(w.mode, 'screen')
        self.assertEqual(w.capture_kind.currentData(), 'window')
        self.assertIsNone(w.capture_window.currentData())
        w.refresh_windows()
        self.assertIsNone(w.capture_window.currentData())
        self.assertEqual(w.zoom_amount.currentData(), 2.5)
        self.assertTrue(w.crop_drag_enabled.isChecked())
        self.assertEqual(w.saved_camera_placement(), (.25, .625))
        w.position.setCurrentIndex((w.position.currentIndex() + 1) % w.position.count())
        self.assertIsNone(w.saved_camera_placement())
