"""Synthetic crop geometry and OBS filter state, without device IO."""
import unittest

from untangle.composition import bounded_offset, camera_composition
from untangle.engine import EngineError
import test_camera_updates


class OffsetGeometryTests(unittest.TestCase):
    def test_crop_travel_edges_mirror_and_placement_are_independent(self):
        for dims in ((1920, 1080), (1080, 1920), (1080, 1080)):
            for source in ((1920, 1080), (720, 1280), (641, 481)):
                for mode in ('screen', 'camera'):
                    for framing in ('fit', 'fill'):
                        for zoom in (1, 1.37, 3):
                            _, placement = camera_composition(*dims, *source, mode=mode,
                                framing=framing, camera_zoom=zoom)
                            for mirror in (False, True):
                                for offset in ((-1, -1), (0, 0), (1, 1), (.37, -.63)):
                                    crop, moved = camera_composition(*dims, *source, mode=mode,
                                        framing=framing, camera_zoom=zoom,
                                        camera_offset=offset, mirror=mirror)
                                    x, y, width, height = crop
                                    self.assertEqual(moved, placement)
                                    self.assertTrue(0 <= x <= source[0] - width)
                                    self.assertTrue(0 <= y <= source[1] - height)
                                    if offset == (1, 1):
                                        self.assertEqual(x, source[0] - width if mirror else 0)
                                        self.assertEqual(y, 0)
                                    if offset == (-1, -1):
                                        self.assertEqual(x, 0 if mirror else source[0] - width)
                                        self.assertEqual(y, source[1] - height)

    def test_invalid_values_and_clamping(self):
        self.assertEqual(bounded_offset((-10, 10)), (-1, 1))
        for value in (None, 'xy', (), (0,), (0, 0, 0), (True, 0),
                      (float('nan'), 0), (0, float('inf')), ('1', 0)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bounded_offset(value)

    def test_engine_updates_preserve_mask_position_zoom_and_size(self):
        factory = test_camera_updates.CameraUpdatesTests()
        for shape in ('circle', 'rounded', 'square', 'custom'):
            e = factory.engine('screen', shape=shape)
            e.set_camera_position(.2, .8)
            e.set_camera_framing(camera_zoom=2, camera_offset=(.8, -.6))
            e._obs.reset_mock()
            e._mask.reset_mock()
            e.set_camera_framing(camera_offset=(-1, 1))
            data = e._obs.obs_source_update.call_args.args[1]
            self.assertEqual((data['left'], data['top']), (0, 0))
            self.assertEqual(e._camera_position, (.2, .8))
            self.assertEqual(e._camera_framing['camera_zoom'], 2)
            self.assertEqual(e._camera_framing['size'], .22)
            e._mask.assert_not_called()
            factory.assert_no_rebuild(e)
            e.set_camera_framing(size=.3)
            self.assertEqual(e._camera_framing['camera_offset'], (-1, 1))
            e.set_camera_framing(mirror=False)
            self.assertEqual(e._obs.obs_source_update.call_args.args[1]['left'], 1380)
            e._output = object()
            with self.assertRaises(EngineError):
                e.set_camera_framing(camera_offset=(0, 0))
