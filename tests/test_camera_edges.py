"""Real alpha pixels and mocked OBS readback, without devices or an X server."""
import ctypes as C
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, call, patch
from types import MethodType

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from untangle.engine import Engine
from untangle.floating import CameraBubble, camera_input_rectangles, camera_mask

qt = QApplication.instance() or QApplication([])


class CameraAlphaTests(unittest.TestCase):
    def bubble(self, side=200):
        bubble = CameraBubble()
        self.addCleanup(bubble.close)
        bubble.resize(side, side)
        frame = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
        frame.fill(QColor('#f45c32'))
        bubble.set_frame(frame)
        return bubble

    def test_smooth_edges_at_small_large_and_fractional_device_scales(self):
        for shape in ('circle', 'rounded'):
            for side in (100, 201, 377):
                bubble = self.bubble(side)
                bubble.apply_shape(shape)
                for ratio in (1, 1.25, 1.5, 2):
                    with self.subTest(shape=shape, side=side, ratio=ratio):
                        image = bubble.frame_image(ratio)
                        size = round(side * ratio)
                        self.assertEqual((image.width(), image.height()), (size, size))
                        self.assertEqual(image.devicePixelRatio(), ratio)
                        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                        self.assertEqual(image.pixelColor(size // 2, size // 2).alpha(), 255)
                        alpha = image.convertToFormat(QImage.Format_Alpha8)
                        values = set(alpha.constBits())
                        self.assertGreater(len(values - {0, 255}), 10)
                        self.assertTrue(bubble.mask().isEmpty())
                        self.assertTrue(bubble.testAttribute(Qt.WA_TranslucentBackground))
                        self.assertFalse(bubble.testAttribute(Qt.WA_PaintOnScreen))

    def test_premultiplied_edges_blend_over_light_and_dark_without_black_halo(self):
        bubble = self.bubble()
        bubble.apply_shape('rounded')
        frame = bubble.frame_image(1)
        points = [(x, y) for y in range(40) for x in range(40)
                  if 30 < frame.pixelColor(x, y).alpha() < 220]
        self.assertTrue(points)
        for background in ('#171b20', '#f6f0e8'):
            composite = QImage(200, 200, QImage.Format_ARGB32_Premultiplied)
            composite.fill(QColor(background))
            painter = QPainter(composite)
            painter.drawImage(0, 0, frame)
            painter.end()
            for x, y in points:
                alpha = frame.pixelColor(x, y).alphaF()
                foreground, back, actual = QColor('#f45c32'), QColor(background), composite.pixelColor(x, y)
                for channel in ('red', 'green', 'blue'):
                    expected = getattr(foreground, channel)() * alpha + getattr(back, channel)() * (1 - alpha)
                    self.assertAlmostEqual(getattr(actual, channel)(), expected, delta=2)

    def test_custom_soft_alpha_mirror_and_invalid_mask_preserve_previous_shape(self):
        bubble = self.bubble(100)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'mask.png'
            custom = QImage(100, 100, QImage.Format_ARGB32_Premultiplied)
            custom.fill(QColor(255, 255, 255, 32))
            painter = QPainter(custom)
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.fillRect(0, 0, 50, 100, QColor(255, 255, 255, 192))
            painter.end()
            custom.save(str(path))
            bubble.apply_shape('custom', str(path))
            self.assertEqual(bubble.frame_image(1).pixelColor(10, 50).alpha(), 192)
            self.assertEqual(bubble.frame_image(1).pixelColor(90, 50).alpha(), 32)
            bubble.apply_shape('custom', str(path), mirror_mask=True)
            self.assertEqual(bubble.frame_image(1).pixelColor(10, 50).alpha(), 32)
            self.assertEqual(bubble.frame_image(1).pixelColor(90, 50).alpha(), 192)
            with self.assertRaisesRegex(ValueError, 'cannot be opened'):
                bubble.apply_shape('custom', str(path.with_name('missing.png')))
            self.assertEqual(bubble.frame_image(1).pixelColor(90, 50).alpha(), 192)
            custom.fill(Qt.transparent)
            custom.save(str(path))
            with self.assertRaisesRegex(ValueError, 'completely transparent'):
                bubble.apply_shape('custom', str(path))

    def test_existing_obs_alpha_is_not_applied_twice(self):
        bubble = self.bubble(100)
        bubble.apply_shape('circle')
        bubble.set_frame_provider(lambda: None, masked=True)
        frame = QImage(100, 100, QImage.Format_RGBA8888_Premultiplied)
        frame.fill(QColor(240, 160, 80, 64))
        bubble.set_frame(frame)
        self.assertEqual(bubble.frame_image(1).pixelColor(0, 0).alpha(), 64)
        self.assertEqual(bubble.frame_image(2).pixelColor(100, 100).alpha(), 64)

    def test_input_only_shape_keeps_all_soft_pixels_and_skips_corners(self):
        image = camera_mask('circle', 100, 100)
        rectangles = camera_input_rectangles(image)
        for x, y in ((0, 0), (50, 50), (49, 0), (5, 30)):
            covered = any(left <= x < left + width and top <= y < top + height
                          for left, top, width, height in rectangles)
            self.assertEqual(covered, image.pixelColor(x, y).alpha() > 0)
        soft = QImage(3, 2, QImage.Format_ARGB32_Premultiplied)
        soft.fill(QColor(255, 255, 255, 1))
        self.assertEqual(camera_input_rectangles(soft), [(0, 0, 3, 1), (0, 1, 3, 1)])

    def test_x11_clip_applies_only_to_input_and_closes_connection(self):
        from Xlib.ext import shape
        bubble = self.bubble()
        bubble.apply_shape('circle')
        with patch('Xlib.display.Display') as connection, \
             patch('Xlib.ext.shape.Rectangles') as request, \
             patch('Xlib.error.CatchError') as catcher:
            catcher.return_value.get_error.return_value = None
            bubble._update_input_shape()
        self.assertFalse(bubble._input_passthrough)
        self.assertEqual(request.call_args.kwargs['destination_kind'], shape.SK.Input)
        connection.return_value.close.assert_called_once()
        self.assertTrue(bubble.mask().isEmpty())

    def test_x11_shape_uses_the_real_library_call_signature(self):
        from Xlib.ext import shape
        bubble = self.bubble()
        with patch('Xlib.display.Display') as connection, \
             patch('Xlib.ext.shape.Rectangles') as request, \
             patch('Xlib.error.CatchError') as catcher:
            catcher.return_value.get_error.return_value = None
            window = connection.return_value.create_resource_object.return_value
            # The extension wrapper does not accept onerror. A plain Mock
            # hid that incompatibility in the previous input-region tests.
            window.shape_rectangles = MethodType(shape.rectangles, window)
            bubble._update_input_shape()
        self.assertFalse(bubble._input_passthrough)
        self.assertTrue(request.called)
        self.assertEqual(request.call_args.kwargs['destination_kind'], shape.SK.Input)
        self.assertIs(request.call_args.kwargs['onerror'], catcher.return_value)

    def test_hidden_camera_has_an_explicit_empty_native_input_region(self):
        from Xlib.ext import shape
        bubble = self.bubble()
        with patch('Xlib.display.Display') as connection, \
             patch('Xlib.ext.shape.Rectangles') as request, \
             patch('Xlib.error.CatchError') as catcher:
            catcher.return_value.get_error.return_value = None
            bubble._update_input_shape(empty=True)
        args = request.call_args.kwargs
        self.assertEqual(args['operation'], shape.SO.Set)
        self.assertEqual(args['destination_kind'], shape.SK.Input)
        self.assertEqual(args['rectangles'], [])
        connection.return_value.close.assert_called_once()

    def test_rejected_x11_shape_falls_back_to_click_through_until_restart(self):
        bubble = self.bubble()
        bubble.winId()
        with patch('Xlib.display.Display') as connection, \
             patch('Xlib.ext.shape.Rectangles'), \
             patch('Xlib.error.CatchError') as catcher:
            catcher.return_value.get_error.return_value = RuntimeError('BadMatch')
            bubble._update_input_shape()
        self.assertTrue(bubble._input_passthrough)
        self.assertTrue(bubble.windowHandle().flags() & Qt.WindowTransparentForInput)
        connection.return_value.sync.assert_called_once()
        connection.return_value.close.assert_called_once()
        with patch('Xlib.display.Display'), patch('Xlib.ext.shape.Rectangles') as request:
            bubble._update_input_shape()
        self.assertEqual(request.call_args.kwargs['rectangles'], [])

    def test_obs_composition_mask_uses_same_fractional_pixels(self):
        engine = Engine.__new__(Engine)
        with tempfile.TemporaryDirectory() as folder:
            engine._mask_dir = Mock(name=folder)
            engine._mask_dir.name = folder
            for shape in ('circle', 'rounded'):
                for side in (100, 240, 1080):
                    path = engine._mask(shape, None, side, side)
                    image = QImage(path)
                    expected = camera_mask(shape, side, side)
                    self.assertEqual(image.convertToFormat(expected.format()), expected)
            custom = QImage(20, 20, QImage.Format_ARGB32_Premultiplied)
            custom.fill(QColor(255, 255, 255, 47))
            path = Path(folder) / 'custom.png'
            custom.save(str(path))
            self.assertEqual(engine._mask('custom', str(path), 20, 20), str(path.resolve()))
            self.assertEqual(QImage(str(path)).pixelColor(0, 0).alpha(), 47)


class BubbleReadbackTests(unittest.TestCase):
    def setUp(self):
        e = self.engine = Engine.__new__(Engine)
        e._closed = False
        e._camera_source = 10
        e._camera_display = None
        e._camera_preview_enabled = False
        e._camera_mirror = False
        e._obs = Mock()
        e.errors = []
        e._obs.gs_texrender_create.return_value = 101
        e._obs.gs_stagesurface_create.side_effect = range(201, 220)
        e._obs.obs_source_get_width.return_value = 16
        e._obs.obs_source_get_height.return_value = 16
        bubble = self.bubble = CameraBubble()
        bubble.resize(16, 16)
        self.addCleanup(bubble.close)
        e.attach_bubble(bubble)
        self.addCleanup(e.detach_camera_preview)

    def render(self, now):
        with patch('untangle.engine.time.monotonic', return_value=now):
            self.engine._draw_bubble(None, 1920, 1080)

    def map_pixels(self, width=16, height=16):
        stride = width * 4 + 16
        self.buffer = C.create_string_buffer(bytes([80, 40, 20, 128]) * (stride * height // 4))
        def map_surface(_surface, pointer, linesize):
            C.cast(pointer, C.POINTER(C.c_void_p))[0] = C.cast(self.buffer, C.c_void_p)
            C.cast(linesize, C.POINTER(C.c_uint32))[0] = stride
            return True
        self.engine._obs.gs_stagesurface_map.side_effect = map_surface

    def test_bounded_rate_double_staging_and_owned_stride_aware_frame(self):
        self.map_pixels()
        self.render(1)
        e = self.engine
        e._obs.gs_stagesurface_map.assert_not_called()
        self.render(1.01)
        self.assertEqual(e._obs.gs_stage_texture.call_count, 1)
        self.render(1.04)
        self.assertEqual(e._obs.gs_stage_texture.call_count, 2)
        self.assertEqual(e._obs.gs_stagesurface_map.call_args.args[0], 201)
        e._obs.gs_stagesurface_unmap.assert_called_once_with(201)
        self.buffer[0] = 0  # Latest frame owns a copy, never this mapped memory.
        image = e._take_bubble_frame()
        self.assertEqual(image.pixelColor(0, 0).alpha(), 128)
        self.assertGreater(image.pixelColor(0, 0).red(), 150)
        self.assertEqual(image.pixelColor(0, 1), image.pixelColor(0, 0))
        self.assertIsNone(e._take_bubble_frame())
        e._obs.gs_blend_function.assert_called_with(1, 5)
        self.assertEqual(e._obs.gs_blend_state_push.call_count, e._obs.gs_blend_state_pop.call_count)

    def test_latest_frame_overwrites_without_widget_calls_on_render_thread(self):
        self.map_pixels()
        e, bubble = self.engine, self.bubble
        with patch.object(bubble, 'set_frame') as set_frame:
            def render_frames():
                for now in (1, 1.04, 1.08):
                    self.render(now)
            worker = threading.Thread(target=render_frames)
            worker.start()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            set_frame.assert_not_called()
        self.assertEqual(len(e._bubble_frame[0]), 80 * 16)
        self.assertIsNotNone(e._take_bubble_frame())
        self.assertIsNone(e._take_bubble_frame())

    def test_resize_caps_resources_recycles_and_never_reopens_capture(self):
        e = self.engine
        self.render(1)
        e.resize_camera_preview(4096, 2048)
        self.assertEqual(e._bubble_requested_size, (1024, 512))
        self.render(1.04)
        self.assertEqual(e._obs.gs_stagesurface_destroy.call_args_list, [call(201), call(202)])
        e._obs.gs_texrender_destroy.assert_called_once_with(101)
        self.assertEqual(e._obs.gs_stagesurface_create.call_args_list[-2:],
                         [call(1024, 512, 3), call(1024, 512, 3)])
        e._obs.obs_source_create.assert_not_called()
        e._obs.obs_reset_video.assert_not_called()

    def test_detach_synchronizes_callback_before_destroy_and_balances_showing(self):
        e = self.engine
        self.render(1)
        e._obs.reset_mock()
        e.detach_camera_preview()
        e.detach_camera_preview()
        calls = e._obs.mock_calls
        removed = calls.index(call.obs_remove_main_render_callback(e._bubble_draw_callback, None))
        entered = calls.index(call.obs_enter_graphics())
        destroyed = calls.index(call.gs_stagesurface_destroy(201))
        hidden = calls.index(call.obs_source_dec_showing(10))
        self.assertLess(removed, entered)
        self.assertLess(entered, destroyed)
        self.assertLess(destroyed, hidden)
        self.assertIsNone(e._bubble_frame)
        self.assertIsNone(e._bubble)
        self.assertFalse(self.bubble._frame_timer.isActive())
        e._obs.obs_source_dec_showing.assert_called_once_with(10)

    def test_disabled_preview_does_no_gpu_work_and_showing_stays_balanced(self):
        e = self.engine
        e.set_camera_preview_enabled(False)
        e.set_camera_preview_enabled(False)
        self.render(1)
        e._obs.gs_texrender_create.assert_not_called()
        e.set_camera_preview_enabled(True)
        self.render(1)
        e._obs.gs_texrender_create.assert_called_once()
        self.assertEqual(e._obs.obs_source_inc_showing.call_count, 2)
        e._obs.obs_source_dec_showing.assert_called_once_with(10)

    def test_failures_are_reported_once_and_partial_allocations_are_released(self):
        e = self.engine
        e._obs.gs_stagesurface_create.side_effect = [201, None]
        self.render(1)
        self.render(2)
        self.assertEqual(len(e.errors), 1)
        e.detach_camera_preview()
        e._obs.gs_stagesurface_destroy.assert_called_once_with(201)
        e._obs.gs_texrender_destroy.assert_called_once_with(101)

    def test_copy_failure_still_unmaps_gpu_memory_and_restores_render_state(self):
        self.map_pixels()
        self.render(1)
        with patch('untangle.engine.C.string_at', side_effect=MemoryError('synthetic')):
            self.render(1.04)
        e = self.engine
        self.assertEqual(len(e.errors), 1)
        e._obs.gs_stagesurface_unmap.assert_called_once_with(201)
        self.assertEqual(e._obs.gs_texrender_begin.call_count, e._obs.gs_texrender_end.call_count)
        self.assertEqual(e._obs.gs_projection_push.call_count, e._obs.gs_projection_pop.call_count)

    def test_map_failure_reports_once_without_unmapping_an_unmapped_surface(self):
        self.engine._obs.gs_stagesurface_map.return_value = False
        self.render(1)
        self.render(1.04)
        self.render(1.08)
        self.assertEqual(len(self.engine.errors), 1)
        self.engine._obs.gs_stagesurface_unmap.assert_not_called()

    def test_detach_waits_for_inflight_render_before_freeing_gpu_memory(self):
        e = self.engine
        mutex = threading.Lock()
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def stage(*_args):
            entered.set()
            if not release.wait(2):
                raise RuntimeError('Synthetic render timed out')
        e._obs.gs_stage_texture.side_effect = stage
        def render():
            with mutex:
                self.render(1)
            finished.set()
        worker = threading.Thread(target=render)
        worker.start()
        self.assertTrue(entered.wait(2))
        def remove(*_args):
            # OBS 27 holds this mutex across render callbacks and removal.
            release.set()
            with mutex:
                pass
            worker.join(2)
        e._obs.obs_remove_main_render_callback.side_effect = remove
        e._obs.gs_stagesurface_destroy.side_effect = lambda _surface: self.assertTrue(finished.is_set())
        e.detach_camera_preview()
        self.assertFalse(worker.is_alive())
        self.assertEqual(e.errors, [])
        self.assertIsNone(e._bubble)

    def test_failed_qt_attachment_unregisters_callback_and_keeps_capture_owned(self):
        e = self.engine
        e.detach_camera_preview()
        e._obs.reset_mock()
        with patch.object(self.bubble, 'set_frame_provider', side_effect=[RuntimeError('synthetic'), None]):
            with self.assertRaisesRegex(RuntimeError, 'synthetic'):
                e.attach_bubble(self.bubble)
        e._obs.obs_remove_main_render_callback.assert_called_once()
        e._obs.obs_source_release.assert_not_called()
        e._obs.obs_source_inc_showing.assert_not_called()
        self.assertIsNone(e._bubble)

    def test_deleted_qt_window_still_releases_callback_and_gpu_objects(self):
        from shiboken6 import delete
        e = self.engine
        replacement = CameraBubble()
        replacement.resize(16, 16)
        e.attach_bubble(replacement)
        self.render(1)
        e._obs.reset_mock()
        delete(replacement)
        e.detach_camera_preview()
        e._obs.obs_remove_main_render_callback.assert_called_once()
        self.assertEqual(e._obs.gs_stagesurface_destroy.call_count, 2)
        e._obs.obs_source_dec_showing.assert_called_once_with(10)


if __name__ == '__main__':
    unittest.main()
