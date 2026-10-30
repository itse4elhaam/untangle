"""Presentation changes use mocked OBS, never capture devices."""
import unittest
from unittest.mock import Mock
from untangle.engine import Engine, EngineError


class PresentationTests(unittest.TestCase):
    def engine(self, floating=True, screen=True):
        e = Engine.__new__(Engine)
        e._closed = False
        e._started_obs = True
        e._obs = Mock()
        e._output = 99
        e._scene = 1
        e._sources = []
        e._camera_source = 2
        e._camera_scene_item = None if floating else 3
        e._camera_crop_filter = 4
        e._camera_mask_filter = None
        e._camera_dimensions = (1920, 1080)
        e._camera_framing = dict(mode='screen', camera_zoom=1., framing='fit',
                                 size=.22, position='bottom-right')
        e._camera_position = None
        e._camera_mirror = True
        e._screen_item = 5 if screen else None
        e._presentation_floating = floating
        e._presentation_screen = 0
        e.width, e.height = 1920, 1080
        e._data = Mock(return_value=7)
        e._place = Mock()
        e._source = Mock(return_value=8)
        e._dimensions = Mock(return_value=(1920, 1080))
        e.restore_screen_zoom = Mock()
        return e

    def test_floating_camera_expands_and_returns_without_restarting_output(self):
        e = self.engine()
        e.set_presentation(1)
        e._place.assert_called_with(e._camera_scene_item, 0., 0., 1., True, 1920.)
        e._obs.obs_sceneitem_set_visible.assert_any_call(5, False)
        e.set_presentation(.5)
        e.set_presentation(0)
        e._obs.obs_sceneitem_set_visible.assert_any_call(e._camera_scene_item, False)
        self.assertEqual(e._output, 99)
        e._source.assert_not_called()
        e._obs.obs_output_start.assert_not_called()
        e._obs.obs_output_stop.assert_not_called()

    def test_camera_only_acquires_desktop_once_when_switching_to_screen(self):
        e = self.engine(screen=False, floating=False)
        e.set_presentation(1)
        e._source.assert_not_called()
        e.set_presentation(.5)
        e.set_presentation(0)
        e.set_presentation(1)
        e._source.assert_called_once_with('xshm_input', 'RecIt screen',
                                         {'screen': 0, 'show_cursor': True})
        e._obs.obs_sceneitem_set_order.assert_called_once_with(e._screen_item, 3)
        self.assertEqual(e._output, 99)

    def test_mask_is_disabled_during_expansion_and_restored_for_bubble(self):
        e = self.engine(floating=False)
        e._camera_mask_filter = 6
        e.set_presentation(.5)
        e._obs.obs_source_set_enabled.assert_called_with(6, False)
        e.set_presentation(0)
        e._obs.obs_source_set_enabled.assert_called_with(6, True)

    def test_invalid_progress_is_rejected_before_mutation(self):
        e = self.engine()
        with self.assertRaises(EngineError):
            e.set_presentation(float('nan'))
        e._obs.obs_scene_add.assert_not_called()
