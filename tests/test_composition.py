"""Pure canvas checks, without Qt, OBS or capture devices."""
import unittest

from untangle.composition import canvas_dimensions


class CanvasDimensionsTests(unittest.TestCase):
    def test_presets_keep_quality_short_edge_and_even_dimensions(self):
        expected = {
            'landscape': (1920, 1080), 'portrait': (1080, 1920),
            'square': (1080, 1080), 'portrait45': (1080, 1350),
        }
        for multiplier in (1, 2):
            quality = (1920 * multiplier, 1080 * multiplier)
            self.assertEqual(canvas_dimensions(quality), quality)
            for preset, dimensions in expected.items():
                with self.subTest(quality=quality, preset=preset):
                    actual = canvas_dimensions(quality, preset)
                    self.assertEqual(actual, tuple(value * multiplier for value in dimensions))
                    self.assertTrue(all(value % 2 == 0 for value in actual))

    def test_invalid_quality_or_preset(self):
        for quality in ((1921, 1080), (1920, 0), (1080, 1920), (1920., 1080)):
            with self.assertRaises(ValueError):
                canvas_dimensions(quality)
        with self.assertRaisesRegex(ValueError, 'Unknown canvas'):
            canvas_dimensions((1920, 1080), 'unknown')


class CameraCompositionTests(unittest.TestCase):
    def test_crops_stay_inside_source_and_placement_never_stretches(self):
        from untangle.composition import camera_composition
        for preset in ('landscape', 'portrait', 'square', 'portrait45'):
            width, height = canvas_dimensions((1920, 1080), preset)
            for source_w, source_h in ((1920, 1080), (641, 481), (480, 640), (1, 1)):
                for zoom in (1, 1.73, 3):
                    for framing in ('fit', 'fill'):
                        with self.subTest(preset=preset, source=(source_w, source_h), zoom=zoom, framing=framing):
                            crop, (x, y, scale) = camera_composition(
                                width, height, source_w, source_h,
                                camera_zoom=zoom, framing=framing)
                            left, top, cw, ch = crop
                            self.assertTrue(0 <= left <= source_w - cw)
                            self.assertTrue(0 <= top <= source_h - ch)
                            self.assertGreaterEqual(min(cw, ch), 1)
                            self.assertAlmostEqual(x + cw * scale / 2, width / 2)
                            self.assertAlmostEqual(y + ch * scale / 2, height / 2)
                            if framing == 'fit':
                                self.assertGreaterEqual(x, -1e-9)
                                self.assertGreaterEqual(y, -1e-9)
                            else:
                                self.assertLessEqual(x, 1e-9)
                                self.assertLessEqual(y, 1e-9)

    def test_zoom_crops_synthetic_source_around_its_center(self):
        from untangle.composition import camera_composition
        crop, placement = camera_composition(1080, 1920, 1280, 720,
                                              camera_zoom=2, framing='fill')
        left, top, width, height = crop
        # Source corners disappear; the source center remains in the crop.
        self.assertGreater(left, 0)
        self.assertGreater(top, 0)
        self.assertAlmostEqual(left + width / 2, 640, delta=.5)
        self.assertAlmostEqual(top + height / 2, 360, delta=.5)
        self.assertLessEqual(placement[0], 0)
        self.assertLessEqual(placement[1], 0)
