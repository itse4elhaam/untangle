"""Pin useful camera preset defaults and the visible recording canvas, without IO."""
import unittest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from untangle.composition import camera_composition
import test_ui_clickthrough as ui

qt = ui.qt


class CanvasPresentationTests(unittest.TestCase):
    def setUp(self):
        self.case = ui.ClearlineClickthrough()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.window = self.case.window
        self.window.timer.stop()

    def test_selecting_camera_social_preset_fills_the_recording_canvas(self):
        w = self.window
        for preset in ('portrait', 'square', 'portrait45'):
            with self.subTest(preset=preset):
                self.case.choose_output(w.canvas, preset)
                self.assertEqual(w.framing.currentData(), 'fill',
                                 'Camera social presets must not default to a small letterboxed image')
                width, height = w.output_dimensions()
                crop, (x, y, scale) = camera_composition(width, height, 1920, 1080,
                                                          framing=w.framing.currentData())
                self.assertGreaterEqual(crop[2] * scale, width)
                self.assertGreaterEqual(crop[3] * scale, height)
                self.assertEqual(w.engine.set_camera_framing.call_args.kwargs['framing'], 'fill')

    def test_native_preview_matches_canvas_aspect_and_keeps_its_parent(self):
        w = self.window
        parent = w.preview.parentWidget()
        native_id = int(w.preview.winId())
        for preset, ratio in (('portrait', 9 / 16), ('square', 1), ('landscape', 16 / 9)):
            self.case.choose_output(w.canvas, preset)
            for size in ((960, 760), (1120, 840), (2400, 1000)):
                with self.subTest(preset=preset, size=size):
                    w.resize(*size)
                    qt.processEvents()
                    self.assertAlmostEqual(w.preview.width() / w.preview.height(), ratio, delta=.005)
                    self.assertIs(w.preview.parentWidget(), parent)
                    self.assertEqual(int(w.preview.winId()), native_id)
                    self.assertTrue(parent.rect().contains(w.preview.geometry()))
                    self.assertGreater(w.preview.height(), 300)

    def test_explicit_fit_survives_preference_restore(self):
        w = self.window
        self.case.choose_output(w.canvas, 'portrait')
        w.framing.setCurrentIndex(w.framing.findData('fit'))
        w.framing_selected()
        w.save_preferences()
        w.restore_preferences()
        self.assertEqual(w.framing.currentData(), 'fit')

    def test_previous_automatic_portrait_fit_is_corrected_without_touching_landscape(self):
        w = self.window
        w.engine = None
        for preset, expected in (('portrait', 'fill'), ('square', 'fill'),
                                 ('portrait45', 'fill'), ('landscape', 'fit')):
            with self.subTest(preset=preset):
                w.prefs.remove('framing_explicit')
                w.prefs.setValue('mode', 'camera')
                w.prefs.setValue('canvas', preset)
                w.prefs.setValue('framing', 'fit')
                w.restore_preferences()
                self.assertEqual(w.framing.currentData(), expected)

    def test_screen_portrait_preserves_whole_screen_by_default(self):
        w = self.window
        self.case.click(w.screen_button)
        w.canvas.setCurrentIndex(w.canvas.findData('portrait'))
        self.assertEqual(w.effective_framing(), 'fit')
        self.assertEqual(w.output_dimensions(), w.quality.currentData())
        self.assertFalse(w.canvas_panel.isVisible())
