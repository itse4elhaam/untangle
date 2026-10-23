"""Real recorder initialization and composition transitions with mocked OBS only."""
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtTest import QTest
from untangle import app as glint
from untangle.composition import canvas_dimensions
import test_app

initialize = glint.Window.initialize


class CanvasLifecycleTests(unittest.TestCase):
    setUp = test_app.AppChecks.setUp
    tearDown = test_app.AppChecks.tearDown

    def factory(self):
        def create(*args, **kwargs):
            engine = MagicMock()
            engine.errors = []
            engine.recording = False
            return engine
        return patch('untangle.engine.Engine', side_effect=create)

    def test_real_initialize_uses_canvas_dimensions_and_current_framing(self):
        w = self.window
        w.timer.stop()
        with self.factory() as factory:
            for quality in ((1920, 1080), (3840, 2160)):
                for preset in ('landscape', 'portrait', 'square', 'portrait45'):
                    with self.subTest(quality=quality, preset=preset):
                        w.engine = None
                        w.quality.setCurrentIndex(next(i for i in range(w.quality.count())
                                                     if w.quality.itemData(i) == quality))
                        w.canvas.setCurrentIndex(w.canvas.findData(preset))
                        w.framing.setCurrentIndex(w.framing.findData('fill'))
                        w.camera_zoom.setValue(175)
                        initialize(w)
                        expected = canvas_dimensions(quality, preset)
                        self.assertEqual(factory.call_args.args[1:], expected)
                        self.assertEqual(factory.call_args.kwargs, dict(fps=30))
                        self.assertEqual(w.engine.configure.call_args.kwargs['framing'], 'fill')
                        self.assertEqual(w.engine.configure.call_args.kwargs['camera_zoom'], 1.75)
                        self.assertTrue(w.configuration_valid)
                        self.assertTrue(w.record_button.isEnabled())
                        w.engine.close()
            w.configure_timer.stop()

    def test_rapid_canvas_changes_cancel_stale_debounce_and_create_one_engine(self):
        w = self.window
        w.timer.stop()
        previous = w.engine
        w.initialize = initialize.__get__(w)
        with self.factory() as factory:
            w.schedule_configure()
            self.assertTrue(w.configure_timer.isActive())
            w.canvas.setCurrentIndex(w.canvas.findData('portrait'))
            w.canvas.setCurrentIndex(w.canvas.findData('square'))
            self.assertFalse(w.configure_timer.isActive())
            QTest.qWait(220)
            previous.close.assert_called_once()
            factory.assert_called_once()
            self.assertEqual(factory.call_args.args[1:], (2160, 2160))
            self.assertTrue(w.configuration_valid)
            self.assertTrue(w.record_button.isEnabled())
            self.assertEqual(w.prefs.value('canvas'), 'square')

    def test_floating_and_composited_overlay_transitions_and_recovery(self):
        w = self.window
        w.timer.stop()
        w.show()
        w.initialize = initialize.__get__(w)
        with self.factory():
            w.set_mode('screen', configure=False)
            for preset, framing, floating in (
                ('landscape', 'fit', True), ('landscape', 'fill', False),
                ('portrait', 'fill', False), ('square', 'fit', False),
                ('landscape', 'fit', True),
            ):
                with self.subTest(preset=preset, framing=framing):
                    w.canvas.setCurrentIndex(w.canvas.findData(preset))
                    w.framing.setCurrentIndex(w.framing.findData(framing))
                    QTest.qWait(220)
                    w.configure()
                    self.assertEqual(w.engine.configure.call_args.kwargs['floating_camera'], floating)
                    self.assertEqual(w.bubble.isVisible(), floating)
                    if floating:
                        w.engine.attach_camera_preview.assert_called()
                    else:
                        w.engine.detach_camera_preview.assert_called()
            with patch.object(w.window_catalog, 'list', return_value=[('Editor', 4242)]), \
                    patch.object(w.window_catalog, 'geometry', return_value=(0, 0, 800, 600)):
                w.capture_kind.setCurrentIndex(w.capture_kind.findData('window'))
                w.configure()
                self.assertFalse(w.engine.configure.call_args.kwargs['floating_camera'])
                self.assertEqual(w.engine.configure.call_args.kwargs['window_id'], 4242)
                self.assertTrue(w.bubble.isVisible())
            w.camera.setCurrentIndex(w.camera.findData(None))
            w.configure()
            self.assertFalse(w.bubble.isVisible())
            w.capture_kind.setCurrentIndex(w.capture_kind.findData('screen'))
            w.camera.setCurrentIndex(w.camera.findData('/dev/video-test'))
            w.engine.configure.side_effect = RuntimeError('synthetic failure')
            w.configure()
            self.assertFalse(w.configuration_valid)
            self.assertFalse(w.bubble.isVisible())
            w.engine.configure.side_effect = None
            w.configure()
            self.assertTrue(w.configuration_valid)
            self.assertTrue(w.bubble.isVisible())
            w.configure_timer.stop()

    def test_expand_camera_hides_canvas_controls_without_changing_output(self):
        w = self.window
        w.show()
        dimensions = w.output_dimensions()
        w.focus_button.setChecked(True)
        test_app.qt.processEvents()
        self.assertFalse(w.canvas_panel.isVisible())
        self.assertEqual(w.output_dimensions(), dimensions)
        w.focus_button.setChecked(False)
        test_app.qt.processEvents()
        self.assertTrue(w.canvas_panel.isVisible())
