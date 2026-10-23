"""Synthetic camera updates: no libobs startup, capture, audio or Qt windows."""
import ctypes as C
import json
import unittest
from unittest.mock import Mock, call, patch

from untangle.composition import camera_composition
from untangle.engine import Engine, EngineError, _VideoInfo


class CameraUpdatesTests(unittest.TestCase):
    def engine(self, mode='camera', **kwargs):
        e = Engine.__new__(Engine)
        e._obs = Mock()
        e._closed = False
        e._started_obs = True
        e._output = e._scene = e._camera_display = None
        e._camera_source = e._camera_item = None
        e._camera_preview_enabled = False
        e._microphone_meter = None
        e._sources = []
        e.width, e.height, e.fps = 1920, 1080, 30
        e._video_info = _VideoInfo(b'libobs-opengl.so.0', 30, 1, 1920, 1080,
                                   1920, 1080, 2, 0, True, 2, 1, 2)
        e.errors = []
        e.source_types = {'v4l2_input', 'xshm_input', 'crop_filter', 'mask_filter_v2'}
        e._obs.obs_source_create.side_effect = range(100, 200)
        e._obs.obs_scene_add.side_effect = range(200, 300)
        e._obs.obs_reset_video.return_value = 0
        e._obs.obs_data_create_from_json.side_effect = lambda data: json.loads(data)
        e._dimensions = Mock(return_value=(1920, 1080))
        e._mask = Mock(return_value='custom-mask.png')
        with patch('untangle.engine.os.access', return_value=True), patch(
                'untangle.engine.camera_settings', return_value={'device_id': '/dev/synthetic'}):
            e.configure(mode=mode, camera='/dev/synthetic', microphone=None, **kwargs)
        e._place = Mock()
        return e

    def assert_no_rebuild(self, e):
        for name in ('obs_source_create', 'obs_source_release', 'obs_source_filter_add',
                     'obs_scene_create', 'obs_scene_release', 'obs_set_output_source',
                     'obs_display_destroy', 'obs_display_create', 'obs_reset_audio',
                     'obs_source_inc_showing', 'obs_source_dec_showing',
                     'obs_wait_for_destroy_queue', 'obs_shutdown'):
            getattr(e._obs, name).assert_not_called()

    def test_repeated_linear_zoom_keeps_sources_audio_displays_and_cached_dimensions(self):
        for mode in ('camera', 'screen'):
            with self.subTest(mode=mode):
                e = self.engine(mode, shape='custom', mask_path='custom-mask.png')
                source, filt, scene = e._camera_source, e._camera_crop_filter, e._scene
                e._camera_display, e._display = 501, 502
                e._camera_preview_enabled = True
                meter = e._microphone_meter = Mock()
                e._obs.reset_mock()
                e._mask.reset_mock()
                e._dimensions.reset_mock()
                for percent in range(100, 301):
                    e.set_camera_framing(camera_zoom=percent / 100)
                    expected, placement = camera_composition(1920, 1080, 1920, 1080,
                        mode=mode, camera_zoom=percent / 100)
                    data = e._obs.obs_source_update.call_args.args[1]
                    self.assertEqual((data['left'], data['top'], data['cx'], data['cy']), expected)
                    self.assertEqual(e._camera_framing['camera_zoom'], percent / 100)
                    self.assertEqual(e._place.call_args.args[1:4], placement)
                self.assertEqual((e._camera_source, e._camera_crop_filter, e._scene), (source, filt, scene))
                self.assertEqual((e._camera_display, e._display), (501, 502))
                self.assertTrue(e._camera_preview_enabled)
                meter.close.assert_not_called()
                e._dimensions.assert_not_called()
                e._mask.assert_not_called()
                self.assert_no_rebuild(e)
                self.assertEqual(e._obs.obs_data_release.call_count, 201)

    def test_crop_installed_at_default_before_mask_and_borrowed_until_scene_clear(self):
        for mode in ('camera', 'screen'):
            e = self.engine(mode, shape='custom', mask_path='custom-mask.png')
            kinds = [c.args[0] for c in e._obs.obs_source_create.call_args_list]
            self.assertIn(b'crop_filter', kinds)
            if mode == 'screen':
                self.assertLess(kinds.index(b'crop_filter'), kinds.index(b'mask_filter_v2'))
            crop = e._camera_crop_filter
            self.assertEqual(e._obs.obs_source_release.call_args_list.count(call(crop)), 1)
            e._obs.reset_mock()
            e.set_camera_framing(camera_zoom=2, mirror=False)
            e._obs.obs_source_update.assert_called_once()
            e._obs.obs_source_filter_add.assert_not_called()
            e._clear_scene()
            self.assertIsNone(e._camera_crop_filter)
            self.assertIsNone(e._camera_scene_item)
            self.assertNotIn(call(crop), e._obs.obs_source_release.call_args_list)

    def test_camera_only_item_does_not_become_draggable_overlay(self):
        e = self.engine()
        self.assertIsNotNone(e._camera_scene_item)
        self.assertIsNone(e._camera_item)
        e.set_camera_position(.2, .8)
        e._place.assert_not_called()
        e.set_camera_framing(framing='fill', mirror=False)
        self.assertEqual(e._place.call_args.args[0], e._camera_scene_item)
        self.assertFalse(e._place.call_args.args[4])

    def test_builtin_masks_track_output_pixels_without_reopening_sources(self):
        for shape in ('circle', 'rounded'):
            e = self.engine('screen', shape=shape, size=.2)
            e._mask.assert_called_once_with(shape, None, 216, 216)
            e._obs.reset_mock()
            e._mask.reset_mock()
            e.set_camera_framing(camera_zoom=3)
            e._mask.assert_not_called()  # Same output coverage despite crop zoom.
            e.set_camera_framing(size=.4)
            e._mask.assert_called_once_with(shape, None, 360, 360)
            self.assertEqual(e._obs.obs_source_update.call_args.args[1]['cx'], 360)
            e._mask.reset_mock()
            e.set_camera_framing(camera_zoom=1)
            e._mask.assert_called_once_with(shape, None, 432, 432)
            self.assertEqual(e._camera_mask_size, (432, 432))
            self.assert_no_rebuild(e)

    def test_fit_fill_bounds_and_overlay_controls_across_canvases(self):
        for mode in ('camera', 'screen'):
            for dims in ((1920, 1080), (1080, 1920), (1080, 1080), (1080, 1350)):
                e = self.engine(mode)
                e.set_canvas(*dims)
                for framing in ('fit', 'fill'):
                    for position in ('top-left', 'top-right', 'bottom-left', 'bottom-right', 'center'):
                        for zoom in (1, 1.37, 3):
                            e.set_camera_framing(camera_zoom=zoom, framing=framing,
                                                 size=.4, position=position, mirror=True)
                            _, x, y, scale, mirrored, dw = e._place.call_args.args
                            data = e._obs.obs_source_update.call_args.args[1]
                            dh = data['cy'] * scale
                            self.assertTrue(mirrored)
                            if mode == 'screen' or framing == 'fit':
                                self.assertGreaterEqual(x, -1e-9)
                                self.assertGreaterEqual(y, -1e-9)
                                self.assertLessEqual(x + dw, dims[0] + 1e-9)
                                self.assertLessEqual(y + dh, dims[1] + 1e-9)
                            else:
                                self.assertLessEqual(x, 1e-9)
                                self.assertLessEqual(y, 1e-9)
                                self.assertGreaterEqual(x + dw, dims[0] - 1e-9)
                                self.assertGreaterEqual(y + dh, dims[1] - 1e-9)

    def test_screen_pointer_zoom_and_drag_remain_independent(self):
        e = self.engine('screen')
        e.set_screen_zoom(2, .2, .8)
        e.set_camera_position(.3, .7)
        e._obs.reset_mock()
        e._place.reset_mock()
        e.set_camera_framing(camera_zoom=2)
        e.set_camera_framing(mirror=False)
        e.set_camera_framing(size=.4)
        item, x, y, _, _, dw = e._place.call_args.args
        self.assertEqual(item, e._camera_item)
        self.assertEqual((x, y), (.3 * (1920 - dw), .7 * (1080 - dw)))
        self.assertEqual(e._screen_zoom, (2, .2, .8))
        self.assert_no_rebuild(e)
        e.set_canvas(1080, 1920)
        self.assertEqual(e._screen_zoom, (2, .2, .8))

    def test_floating_preview_keeps_same_source_and_mirror(self):
        e = self.engine('screen', floating_camera=True)
        self.assertIsNone(e._camera_scene_item)
        e._camera_preview_enabled = True
        e._obs.reset_mock()
        e.set_camera_framing(camera_zoom=2, mirror=False)
        e._obs.obs_source_get_width.return_value = 540
        e._obs.obs_source_get_height.return_value = 540
        e._draw_camera(None, 240, 240)
        e._obs.obs_source_video_render.assert_called_once_with(e._camera_source)
        e._obs.gs_ortho.assert_called_once_with(0, 540, 0, 540, -100, 100)
        self.assert_no_rebuild(e)

    def test_preview_resize_reuses_display_without_changing_visibility(self):
        e = self.engine('screen', floating_camera=True)
        e._camera_display = 501
        e._camera_preview_enabled = True
        e._obs.reset_mock()
        e.resize_camera_preview(360, 360)
        self.assertEqual(e._obs.mock_calls, [call.obs_display_resize(501, 360, 360)])
        self.assertEqual(e._camera_display, 501)
        self.assertTrue(e._camera_preview_enabled)
        for dims in ((0, 240), (-1, 240), (240.5, 240), (True, 240), (2**31, 240)):
            with self.assertRaises(EngineError):
                e.resize_camera_preview(*dims)
        e._camera_display = None
        e._obs.reset_mock()
        e.resize_camera_preview(240, 240)
        self.assertEqual(e._obs.mock_calls, [])

    def test_settings_and_defer_are_released_when_transform_fails(self):
        e = self.engine()
        e._obs.reset_mock()
        e._place.side_effect = RuntimeError('synthetic transform failure')
        previous = dict(e._camera_framing)
        with self.assertRaisesRegex(RuntimeError, 'synthetic'):
            e.set_camera_framing(camera_zoom=2)
        e._obs.obs_sceneitem_defer_update_end.assert_called_once_with(e._camera_scene_item)
        data = e._obs.obs_source_update.call_args.args[1]
        e._obs.obs_data_release.assert_called_once_with(data)
        self.assertEqual(e._camera_framing, previous)
        self.assert_no_rebuild(e)

    def test_invalid_inputs_busy_and_closed_leave_obs_untouched(self):
        e = self.engine()
        e._obs.reset_mock()
        invalid = [{'camera_zoom': v} for v in (True, '2', float('nan'), float('inf'))]
        invalid += [{'size': v} for v in (True, 'large', 0, 1.1, float('nan'))]
        invalid += [{'framing': 'stretch'}, {'position': 'left'}, {'mirror': 1}]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(EngineError):
                e.set_camera_framing(**kwargs)
        for dims in ((0, 1080), (1082, 1920), (1920, 17), (True, 100), (16.0, 16), (32772, 1080)):
            with self.subTest(dims=dims), self.assertRaises(EngineError):
                e.set_canvas(*dims)
        for closed, output in ((False, 999), (True, None)):
            e._closed, e._output = closed, output
            with self.assertRaises(EngineError):
                e.set_camera_framing(camera_zoom=2)
            with self.assertRaises(EngineError):
                e.set_canvas(1080, 1920)
        self.assertEqual(e._obs.mock_calls, [])

    def test_zoom_clamps_and_tiny_dimensions_stay_positive(self):
        e = self.engine()
        e._camera_dimensions = (1, 1)
        for zoom, expected in ((-2, 1), (99, 3)):
            e.set_camera_framing(camera_zoom=zoom)
            self.assertEqual(e._camera_framing['camera_zoom'], expected)
            data = e._obs.obs_source_update.call_args.args[1]
            self.assertEqual((data['left'], data['top'], data['cx'], data['cy']), (0, 0, 1, 1))

    def test_canvas_preserves_video_format_and_existing_resources(self):
        for mode in ('camera', 'screen'):
            e = self.engine(mode)
            e._obs.reset_mock()
            e.set_canvas(1080, 1920)
            vi = C.cast(e._obs.obs_reset_video.call_args.args[0], C.POINTER(_VideoInfo)).contents
            self.assertEqual((vi.base_width, vi.base_height, vi.output_width, vi.output_height),
                             (1080, 1920, 1080, 1920))
            self.assertEqual((vi.graphics_module, vi.fps_num, vi.fps_den, vi.output_format,
                              vi.adapter, vi.gpu_conversion, vi.colorspace, vi.range, vi.scale_type),
                             (b'libobs-opengl.so.0', 30, 1, 2, 0, True, 2, 1, 2))
            self.assert_no_rebuild(e)
            e._obs.reset_mock()
            e.set_canvas(1080, 1920)
            self.assertEqual(e._obs.mock_calls, [])

    def test_canvas_failure_restores_previous_format_and_reports_failed_rollback(self):
        for results in ((-1, 0), (-1, -2)):
            e = self.engine()
            previous = e._video_info
            e._obs.reset_mock()
            e._obs.obs_reset_video.side_effect = results
            with self.assertRaisesRegex(EngineError, 'also failed' if results[1] else 'reset failed'):
                e.set_canvas(1080, 1920)
            self.assertEqual((e.width, e.height), (1920, 1080))
            self.assertIs(e._video_info, previous)
            self.assertEqual(e._obs.obs_reset_video.call_count, 2)
            e._obs.obs_source_update.assert_not_called()
            self.assert_no_rebuild(e)
            self.assertEqual(e._video_reset_failed, results[1] != 0)
            if results[1]:
                with self.assertRaisesRegex(EngineError, 'OBS video reset failed'):
                    e.start('never-created.mkv')
                e._obs.obs_reset_video.side_effect = None
                e._obs.obs_reset_video.return_value = 0
                e.set_canvas(1920, 1080)
                self.assertFalse(e._video_reset_failed)
                self.assertEqual(e._obs.obs_reset_video.call_count, 3)


if __name__ == '__main__':
    unittest.main()
