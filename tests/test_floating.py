"""Shape, drag, and zoom checks without live capture."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import tempfile
from pathlib import Path
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QApplication
from untangle.floating import CameraBubble, ZoomMotion, release_window_input
from unittest.mock import Mock, patch

qt = QApplication.instance() or QApplication([])


class FloatingChecks(unittest.TestCase):
    def test_native_grab_is_released_even_without_a_qwidget_grabber(self):
        widget = Mock()
        with patch('untangle.floating.QApplication.activePopupWidget', return_value=None), \
             patch('untangle.floating.QWidget.mouseGrabber', return_value=None):
            release_window_input(widget)
        widget.windowHandle.return_value.setMouseGrabEnabled.assert_called_once_with(False)

    def test_popup_and_qwidget_grabs_are_closed_before_native_ungrab(self):
        order = Mock()
        widget = Mock()
        widget.windowHandle.return_value = order.native
        with patch('untangle.floating.QApplication.activePopupWidget', return_value=order.popup), \
             patch('untangle.floating.QWidget.mouseGrabber', return_value=order.grabber):
            release_window_input(widget)
        self.assertEqual([c[0] for c in order.mock_calls],
                         ['popup.close', 'grabber.releaseMouse', 'native.setMouseGrabEnabled'])

    def test_hiding_bubble_releases_native_grab_without_waiting_for_mouse_move(self):
        bubble = CameraBubble()
        bubble.show()
        bubble._drag_offset = QPoint(10, 10)
        with patch('untangle.floating.release_window_input') as release:
            bubble.hide()
        release.assert_called_once_with(bubble)
        self.assertIsNone(bubble._drag_offset)
        self.assertEqual(bubble.cursor().shape(), Qt.OpenHandCursor)
        bubble.close()

    def test_missed_release_does_not_keep_dragging_camera(self):
        bubble = CameraBubble()
        bubble.move(100, 100)
        bubble._drag_offset = QPoint(10, 10)
        original = bubble.pos()
        event = QMouseEvent(QEvent.MouseMove, QPointF(20, 20), QPointF(300, 300),
                            Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        bubble.mouseMoveEvent(event)
        self.assertEqual(bubble.pos(), original)
        self.assertIsNone(bubble._drag_offset)
        self.assertEqual(bubble.cursor().shape(), Qt.OpenHandCursor)
        bubble.close()

    def test_circle_clips_corners(self):
        bubble = CameraBubble()
        bubble.resize(200, 200)
        frame = QImage(200, 200, QImage.Format_ARGB32_Premultiplied)
        frame.fill('white')
        bubble.set_frame(frame)
        bubble.apply_shape('circle')
        image = bubble.frame_image(1)
        self.assertEqual(image.pixelColor(100, 100).alpha(), 255)
        self.assertEqual(image.pixelColor(2, 2).alpha(), 0)
        self.assertTrue(bubble.mask().isEmpty())  # Visual alpha must stay fractional.
        bubble.apply_shape('square')
        self.assertEqual(bubble.frame_image(1).pixelColor(2, 2).alpha(), 255)
        bubble.close()

    def test_bubble_starts_inside_selected_screen_at_bottom(self):
        bubble = CameraBubble()
        screen = qt.primaryScreen()
        bubble.arrange(screen, .23, 'bottom-right', 'circle')
        self.assertTrue(screen.availableGeometry().contains(bubble.geometry()))
        self.assertLess(screen.availableGeometry().bottom() - bubble.geometry().bottom(), 25)
        bubble.close()

    def test_dragged_position_survives_recording_setup_until_preset_changes(self):
        bubble = CameraBubble()
        self.addCleanup(bubble.close)
        screen = qt.primaryScreen()
        bubble.arrange(screen, .23, 'bottom-right', 'circle')
        start = bubble.pos() + QPoint(10, 10)
        bubble.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress,
            QPointF(10, 10), QPointF(start), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        end = start - QPoint(80, 60)
        bubble.mouseMoveEvent(QMouseEvent(QEvent.MouseMove,
            QPointF(10, 10), QPointF(end), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        bubble.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease,
            QPointF(10, 10), QPointF(end), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        dragged = bubble.pos()
        bubble.arrange(screen, .23, 'bottom-right', 'rounded')
        self.assertEqual(bubble.pos(), dragged)
        bubble.arrange(screen, .3, 'bottom-right', 'circle')
        self.assertTrue(screen.availableGeometry().contains(bubble.geometry()))
        bubble.arrange(screen, .3, 'top-left', 'circle')
        self.assertEqual(bubble.pos(), screen.availableGeometry().topLeft() + QPoint(20, 20))

    def resize_drag(self, bubble, local, delta, *, release=True):
        start = bubble.pos() + local
        bubble.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress,
            QPointF(local), QPointF(start), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        bubble.mouseMoveEvent(QMouseEvent(QEvent.MouseMove,
            QPointF(local), QPointF(start + delta), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        if release:
            bubble.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease,
                QPointF(local), QPointF(start + delta), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))

    def test_boundary_resize_preserves_shape_anchor_and_clamps_on_offset_screen(self):
        screen = Mock()
        bounds = QRect(-1200, 100, 1200, 800)
        screen.availableGeometry.return_value = bounds
        for shape in ('circle', 'rounded', 'square', 'custom'):
            with self.subTest(shape=shape):
                bubble = CameraBubble()
                self.addCleanup(bubble.close)
                bubble.arrange(screen, .25, 'bottom-right', 'square')
                if shape == 'custom':
                    # A supplied alpha image stays the same shape when resized.
                    directory = tempfile.TemporaryDirectory()
                    self.addCleanup(directory.cleanup)
                    path = Path(directory.name) / 'mask.png'
                    mask = QImage(40, 40, QImage.Format_ARGB32_Premultiplied)
                    mask.fill('white')
                    self.assertTrue(mask.save(str(path)))
                    bubble.apply_shape(shape, path)
                else:
                    bubble.apply_shape(shape)
                frame = QImage(20, 20, QImage.Format_ARGB32_Premultiplied)
                frame.fill('orange')
                bubble.set_frame(frame)
                values = []
                bubble.resized.connect(values.append)
                original = bubble.geometry()
                self.resize_drag(bubble, QPoint(1, bubble.height() // 2), QPoint(-70, 0))
                self.assertEqual(bubble.width(), 270)
                self.assertEqual(bubble.height(), 270)
                self.assertEqual(bubble.geometry().right(), original.right())
                self.assertEqual(bubble.frame_image(1).pixelColor(0, 0).alpha() > 0,
                                 shape in ('square', 'custom'))
                self.assertAlmostEqual(values[-1], 270 / 800)
                for delta, expected in ((QPoint(-5000, 0), 336), (QPoint(5000, 0), 100)):
                    self.resize_drag(bubble, QPoint(1, bubble.height() // 2), delta)
                    self.assertEqual(bubble.width(), expected)
                    self.assertEqual(bubble.height(), expected)
                    self.assertTrue(bounds.contains(bubble.geometry()))
                bubble.arrange(screen, values[-1], 'bottom-right', shape if shape != 'custom' else 'square')
                self.assertTrue(bounds.contains(bubble.geometry()))

    def test_resize_stops_on_lost_release_and_recording_lock_preserves_move(self):
        bubble = CameraBubble()
        self.addCleanup(bubble.close)
        bubble.arrange(qt.primaryScreen(), .25, 'bottom-right', 'rounded')
        self.resize_drag(bubble, QPoint(1, bubble.height() // 2), QPoint(-20, 0), release=False)
        original = bubble.geometry()
        bubble.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(1, 50), QPointF(0, 0),
            Qt.NoButton, Qt.NoButton, Qt.NoModifier))
        self.assertEqual(bubble.geometry(), original)
        for attr in ('recording', 'resize_enabled'):
            setattr(bubble, attr, attr == 'recording')
            size = bubble.size()
            self.resize_drag(bubble, QPoint(1, bubble.height() // 2), QPoint(-20, -20))
            self.assertEqual(bubble.size(), size)
            self.assertNotEqual(bubble.pos(), original.topLeft())
            setattr(bubble, attr, attr != 'recording')

    def test_zoom_starts_at_pointer_and_eases_back(self):
        motion = ZoomMotion()
        motion.enabled = True
        now = motion.last_time
        value, x, y = motion.step(2., .9, .1, now + .016)
        self.assertGreater(value, 1.)
        self.assertLess(value, 2.)
        self.assertAlmostEqual(x, .9)
        self.assertAlmostEqual(y, .1)
        for i in range(1, 100):
            value, _, _ = motion.step(2., .9, .1, now + .016 * (i + 1))
        self.assertEqual(value, 2.)
        motion.enabled = False
        for i in range(100, 200):
            value, _, _ = motion.step(2., .9, .1, now + .016 * (i + 1))
        self.assertEqual(value, 1.)

    def test_zoom_clamps_bad_input(self):
        motion = ZoomMotion()
        motion.enabled = True
        for i in range(100):
            value, x, y = motion.step(20, 4, -3, motion.last_time + .05)
        self.assertEqual(value, 3.)
        self.assertEqual((x, y), (1., 0.))


if __name__ == '__main__':
    unittest.main()
