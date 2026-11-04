"""Settings interaction and per-mode persistence using synthetic UI fixtures."""
import unittest
from unittest.mock import call
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from untangle.camera_framing import load_framing
import test_camera_controls as controls


class FramingPreferencesTests(unittest.TestCase):
    setUp = controls.CameraControlsTests.setUp
    reveal = controls.CameraControlsTests.reveal

    def test_modes_restore_zoom_offsets(self):
        w = self.window
        w.camera_zoom.setValue(180)
        w.camera_offset_dragged(.4, -.7)
        self.case.click(w.screen_button)
        QTest.qWait(220)
        self.assertEqual(w.camera_zoom.value(), 100)
        self.assertEqual(w.camera_offset(), (0., 0.))
        w.camera_zoom.setValue(240)
        w.camera_offset_dragged(-.8, .2)
        self.case.click(w.camera_button)
        QTest.qWait(220)
        self.assertEqual((w.camera_zoom.value(), w.camera_offset()), (180, (.4, -.7)))
        w.save_preferences()
        w.restore_preferences()
        self.assertEqual((w.camera_zoom.value(), w.camera_offset()), (180, (.4, -.7)))
        self.case.click(w.screen_button)
        QTest.qWait(220)
        self.assertEqual((w.camera_zoom.value(), w.camera_offset()), (240, (-.8, .2)))
        self.assertEqual(w.engine.configure.call_args.kwargs['camera_offset'], (-.8, .2))

    def test_settings_drag_keyboard_reset_and_idle_guard(self):
        w = self.window
        self.reveal(w.crop_position)
        geometry = w.bubble.geometry()
        shape, size = w.shape.currentData(), w.size.value()
        w.engine.reset_mock()
        pad = w.crop_position
        center = pad.rect().center()
        QTest.mousePress(pad, Qt.LeftButton, pos=center)
        QTest.mouseMove(pad, center + QPoint(20, -10))
        QTest.mouseRelease(pad, Qt.LeftButton, pos=center + QPoint(20, -10))
        self.assertGreater(w.camera_offset()[0], 0)
        self.assertLess(w.camera_offset()[1], 0)
        self.assertEqual(w.engine.set_camera_framing.call_args, call(camera_offset=w.camera_offset()))
        self.assertEqual((w.shape.currentData(), w.size.value(), w.bubble.geometry()), (shape, size, geometry))
        self.reveal(w.camera_offset_x)
        previous = w.camera_offset_x.value()
        QTest.keyClick(w.camera_offset_x, Qt.Key_Right)
        self.assertEqual(w.camera_offset_x.value(), previous + 1)
        self.reveal(w.camera_offset_reset)
        self.case.click(w.camera_offset_reset)
        self.assertEqual(w.camera_offset(), (0., 0.))
        w.engine.configure.assert_not_called()
        w.engine.close.assert_not_called()
        self.case.close_settings()
        for state in ('recording', 'busy', 'counting'):
            setattr(w, state, True)
            w.update_camera_controls()
            for control in (pad, w.camera_offset_x, w.camera_offset_y, w.camera_offset_reset):
                self.assertFalse(control.isEnabled())
            w.engine.reset_mock()
            w.camera_offset_dragged(1, 1)
            w.engine.set_camera_framing.assert_not_called()
            setattr(w, state, False)

    def test_preferences_persist_without_engine_and_legacy_migration_is_idempotent(self):
        w = self.window
        prefs = QSettings(str(self.case.root / 'framing.ini'), QSettings.IniFormat)
        prefs.setValue('camera_zoom', 175)
        self.assertEqual(load_framing(prefs, 'camera'), (175, (0., 0.)))
        prefs.setValue('camera_zoom_camera', 220)
        prefs.setValue('camera_zoom', 130)
        self.assertEqual(load_framing(prefs, 'camera')[0], 220)
        self.assertEqual(load_framing(prefs, 'screen')[0], 175)
        prefs.setValue('camera_offset_screen', [float('nan'), 1])
        prefs.setValue('camera_zoom_screen', 'broken')
        self.assertEqual(load_framing(prefs, 'screen'), (100, (0., 0.)))
        engine, w.engine = w.engine, None
        try:
            w.camera_zoom.setValue(190)
            w.camera_offset_dragged(.3, .6)
            w.restore_preferences()
            self.assertEqual((w.camera_zoom.value(), w.camera_offset()), (190, (.3, .6)))
        finally:
            w.engine = engine

    def test_live_preview_drag_preserves_widget_geometry_and_obeys_edit_toggle(self):
        w = self.window
        w.engine._camera_dimensions = (1920, 1080)
        w.camera_zoom.setValue(200)
        self.reveal(w.crop_drag_enabled)
        self.case.click(w.crop_drag_enabled)
        w.engine.reset_mock()
        preview_geometry = w.preview.geometry()
        center = w.preview.rect().center()
        QTest.mousePress(w.preview, Qt.LeftButton, pos=center)
        QTest.mouseMove(w.preview, center + QPoint(30, 15))
        QTest.mouseRelease(w.preview, Qt.LeftButton, pos=center + QPoint(30, 15))
        self.assertGreater(w.camera_offset()[0], 0)
        self.assertGreater(w.camera_offset()[1], 0)
        self.assertEqual(w.preview.geometry(), preview_geometry)
        self.assertEqual(w.engine.set_camera_framing.call_args, call(camera_offset=w.camera_offset()))
        self.case.close_settings()
        w.engine.reset_mock()
        QTest.mousePress(w.preview, Qt.LeftButton, pos=center)
        QTest.mouseMove(w.preview, center + QPoint(-30, -15))
        QTest.mouseRelease(w.preview, Qt.LeftButton, pos=center)
        w.engine.set_camera_framing.assert_not_called()

        self.case.click(w.screen_button)
        QTest.qWait(220)
        self.reveal(w.crop_drag_enabled)
        bubble_geometry = w.bubble.geometry()
        center = w.bubble.rect().center()
        QTest.mousePress(w.bubble, Qt.LeftButton, pos=center)
        QTest.mouseMove(w.bubble, center + QPoint(10, 0))
        QTest.mouseRelease(w.bubble, Qt.LeftButton, pos=center + QPoint(10, 0))
        self.assertGreater(w.camera_offset()[0], 0)
        self.assertEqual(w.camera_offset()[1], 0)  # No vertical crop at 1x.
        self.assertEqual(w.bubble.geometry(), bubble_geometry)
