"""Actual Qt framing workflows with synthetic devices and a mocked OBS engine."""
import unittest
from unittest.mock import call, patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton
from untangle import app as glint
from untangle.composition import canvas_dimensions
import test_ui_clickthrough as ui

qt = ui.qt


class CameraControlsTests(unittest.TestCase):
    def setUp(self):
        self.case = ui.ClearlineClickthrough()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.window = self.case.window
        self.window.timer.stop()
        self.case.click(self.window.camera_button)
        QTest.qWait(220)

    def reveal(self, control):
        w = self.window
        if not control.isVisible():
            w.controls_panel.ensureWidgetVisible(w.setup_sections[0])
            self.case.click(w.setup_sections[0])
        w.controls_panel.ensureWidgetVisible(control)
        QTest.qWait(20)
        self.case.visible_control(control)

    def assert_live_update(self, engine, preview, parent, native_id):
        w = self.window
        self.assertIs(w.engine, engine)
        self.assertIs(w.preview, preview)
        self.assertIs(preview.parentWidget(), parent)
        self.assertEqual(int(preview.winId()), native_id)
        engine.configure.assert_not_called()
        engine.close.assert_not_called()
        self.assertFalse(w.configure_timer.isActive())
        self.assertTrue(w.record_button.isEnabled())
        self.assertTrue(w.configuration_valid)

    def test_zoom_buttons_step_clamp_percent_and_reset_without_reconfigure(self):
        w = self.window
        minus, plus = w.camera_zoom_minus, w.camera_zoom_plus
        self.assertIsInstance(minus, QPushButton)
        self.assertIsInstance(plus, QPushButton)
        self.assertLess(self.case.bounds(minus).right(), self.case.bounds(w.camera_zoom).left())
        self.assertGreater(self.case.bounds(plus).left(), self.case.bounds(w.camera_zoom).right())
        self.assertEqual((w.camera_zoom.minimum(), w.camera_zoom.maximum()), (100, 300))
        engine, preview = w.engine, w.preview
        parent, native_id = preview.parentWidget(), int(preview.winId())
        engine.reset_mock()
        for expected in range(110, 301, 10):
            self.case.click(plus)
            self.assertEqual(w.camera_zoom.value(), expected)
            self.assertEqual(w.camera_zoom_value.text(), f'{expected}%')
            self.assertEqual(engine.set_camera_framing.call_args, call(camera_zoom=expected / 100))
            self.assertFalse(w.configure_timer.isActive())
        # A limit may disable its button; QTest still verifies input cannot overshoot.
        QTest.mouseClick(plus, Qt.LeftButton)
        self.assertEqual(w.camera_zoom.value(), 300)
        self.assertEqual(engine.set_camera_framing.call_count, 20)
        for expected in range(290, 99, -10):
            self.case.click(minus)
            self.assertEqual(w.camera_zoom.value(), expected)
            self.assertEqual(w.camera_zoom_value.text(), f'{expected}%')
        QTest.mouseClick(minus, Qt.LeftButton)
        self.assertEqual(w.camera_zoom.value(), 100)
        self.assertEqual(engine.set_camera_framing.call_count, 40)
        self.assertFalse(w.camera_zoom_reset.isEnabled())
        self.case.click(plus)
        self.case.click(w.camera_zoom_reset)
        self.assertEqual(w.camera_zoom.value(), 100)
        self.assertEqual(w.camera_zoom_value.text(), '100%')
        self.assertEqual(engine.set_camera_framing.call_args, call(camera_zoom=1.0))
        QTest.qWait(220)
        self.assert_live_update(engine, preview, parent, native_id)

    def test_keyboard_zoom_updates_each_step_immediately_and_keeps_native_sink(self):
        w = self.window
        engine, preview = w.engine, w.preview
        parent, native_id = preview.parentWidget(), int(preview.winId())
        source = engine._camera_source
        engine.reset_mock()
        w.camera_zoom.setFocus()
        for key, value in ((Qt.Key_Right, 110), (Qt.Key_Right, 120),
                           (Qt.Key_Right, 130), (Qt.Key_Left, 120)):
            QTest.keyClick(w.camera_zoom, key)
            self.assertEqual(w.camera_zoom.value(), value)
            self.assertEqual(w.camera_zoom_value.text(), f'{value}%')
            self.assertEqual(engine.set_camera_framing.call_args, call(camera_zoom=value / 100))
            self.assertFalse(w.configure_timer.isActive())
        self.assertEqual(engine.set_camera_framing.call_args_list,
                         [call(camera_zoom=value) for value in (1.1, 1.2, 1.3, 1.2)])
        QTest.qWait(220)
        self.assertIs(engine._camera_source, source)
        self.assert_live_update(engine, preview, parent, native_id)

    def test_screen_hides_canvas_uses_landscape_fit_and_restores_camera_choices(self):
        w = self.window
        self.case.choose(w.canvas, 'portrait')
        self.assertEqual(w.framing.currentData(), 'fill')
        self.case.choose(w.framing, 'fit')
        self.case.click(w.camera_zoom_plus)
        preview, parent, native_id = w.preview, w.preview.parentWidget(), int(w.preview.winId())
        engine = w.engine
        engine.reset_mock()
        self.case.click(w.screen_button)
        QTest.qWait(220)
        self.assertIs(w.engine, engine)
        self.assertFalse(w.canvas_panel.isVisible())
        self.assertFalse(w.canvas.isVisible())
        self.assertFalse(w.framing.isVisible())
        self.assertEqual(w.output_dimensions(), tuple(w.quality.currentData()))
        engine.set_canvas.assert_any_call(*w.quality.currentData())
        self.assertEqual(engine.configure.call_args.kwargs['framing'], 'fit')
        engine.set_canvas.reset_mock()
        self.case.click(w.camera_button)
        QTest.qWait(220)
        self.assertIs(w.engine, engine)
        self.assertTrue(w.canvas_panel.isVisible())
        self.assertEqual(w.canvas.currentData(), 'portrait')
        self.assertEqual(w.framing.currentData(), 'fit')
        self.assertEqual(w.camera_zoom.value(), 110)
        engine.set_canvas.assert_any_call(*canvas_dimensions(w.quality.currentData(), 'portrait'))
        engine.close.assert_not_called()
        self.assertIs(w.preview, preview)
        self.assertIs(w.preview.parentWidget(), parent)
        self.assertEqual(int(w.preview.winId()), native_id)

    def test_explicit_fit_survives_preferences_and_social_presets_default_to_fill(self):
        w = self.window
        for preset in ('portrait', 'square', 'portrait45'):
            with self.subTest(preset=preset):
                self.case.choose(w.canvas, preset)
                self.assertEqual(w.framing.currentData(), 'fill')
                self.case.choose(w.framing, 'fit')
                w.save_preferences()
                w.restore_preferences()
                self.assertEqual(w.canvas.currentData(), preset)
                self.assertEqual(w.framing.currentData(), 'fit')

    def test_fit_fill_and_mirror_reframe_without_configuring_sources(self):
        w = self.window
        self.case.choose(w.canvas, 'portrait')
        engine, preview = w.engine, w.preview
        parent, native_id = preview.parentWidget(), int(preview.winId())
        engine.reset_mock()
        self.case.choose(w.framing, 'fit')
        self.assertEqual(engine.set_camera_framing.call_args.kwargs['framing'], 'fit')
        self.case.choose(w.framing, 'fill')
        self.assertEqual(engine.set_camera_framing.call_args.kwargs['framing'], 'fill')
        self.reveal(w.mirror)
        self.case.click(w.mirror)
        self.assertEqual(engine.set_camera_framing.call_args.kwargs['mirror'], w.mirror.isChecked())
        self.assert_live_update(engine, preview, parent, native_id)

    def test_screen_overlay_size_and_position_use_the_same_reframe_api(self):
        w = self.window
        self.case.click(w.screen_button)
        QTest.qWait(220)
        self.reveal(w.size)
        engine = w.engine
        engine.reset_mock()
        w.size.setFocus()
        previous = w.size.value()
        QTest.keyClick(w.size, Qt.Key_Right)
        self.assertEqual(w.size.value(), previous + w.size.singleStep())
        self.assertEqual(engine.set_camera_framing.call_args.kwargs['size'], w.size.value() / 100)
        target = next(w.position.itemData(i) for i in range(w.position.count())
                      if w.position.itemData(i) != w.position.currentData())
        self.reveal(w.position)
        self.case.choose(w.position, target)
        self.assertEqual(engine.set_camera_framing.call_args.kwargs['position'], target)
        engine.configure.assert_not_called()
        engine.close.assert_not_called()
        self.assertFalse(w.configure_timer.isActive())

    def test_busy_states_and_camera_off_lock_every_zoom_input(self):
        w = self.window
        self.case.click(w.camera_zoom_plus)
        controls = (w.camera_zoom_minus, w.camera_zoom, w.camera_zoom_plus, w.camera_zoom_reset)
        def assert_locked(state):
            with self.subTest(state=state):
                engine = w.engine
                engine.reset_mock()
                for control in controls:
                    self.assertIn(control, w.config_controls)
                    self.assertFalse(control.isEnabled())
                    QTest.mouseClick(control, Qt.LeftButton)
                    QTest.keyClick(control, Qt.Key_End)
                self.assertEqual(w.camera_zoom.value(), 110)
                engine.set_camera_framing.assert_not_called()
                engine.configure.assert_not_called()

        self.case.choose(w.microphone, None)
        self.case.click(w.record_button)
        self.assertTrue(w.counting)
        w.count_timer.stop()
        assert_locked('countdown')
        # Hold the mocked preparation boundary so the actual preparing UI stays put.
        with patch.object(w, 'run_audio'):
            w.start()
        self.assertTrue(w.preparing_audio)
        self.assertTrue(w.busy)
        assert_locked('preparation')
        w.audio_prepared(None, '')
        self.assertTrue(w.recording)
        assert_locked('recording')
        with patch.object(glint.FinishWorker, 'start'):
            self.case.click(w.record_button)
        self.assertTrue(w.busy)
        assert_locked('saving')
        # Complete the synthetic save without files, remuxing or a background worker.
        w.recording = False
        w.finish_save(None, 'Synthetic save completion')
        self.assertFalse(w.busy)
        self.case.choose(w.camera, None)
        for control in controls:
            self.assertFalse(control.isEnabled())
            QTest.mouseClick(control, Qt.LeftButton)
            QTest.keyClick(control, Qt.Key_End)
        self.assertEqual(w.camera_zoom.value(), 110)
        self.case.choose(w.camera, '/dev/video-test')
        self.assertTrue(all(control.isEnabled() for control in controls))

    def test_canvas_workspace_keeps_real_native_child_at_output_aspect(self):
        w = self.window
        preview, parent, native_id = w.preview, w.preview.parentWidget(), int(w.preview.winId())
        self.assertIsInstance(preview, glint.Preview)
        self.assertIsInstance(parent, glint.CanvasPreview)
        self.assertIs(parent.preview, preview)
        engine = w.engine
        engine.reset_mock()
        for preset in ('portrait', 'square', 'portrait45', 'landscape'):
            self.case.choose(w.canvas, preset)
            self.assertIs(w.engine, engine)
            engine.set_canvas.assert_any_call(*w.output_dimensions())
            engine.close.assert_not_called()
            for size in ((960, 760), (1120, 840)):
                with self.subTest(preset=preset, size=size):
                    w.resize(*size)
                    qt.processEvents()
                    width, height = w.output_dimensions()
                    self.assertAlmostEqual(preview.width() / preview.height(), width / height, delta=.005)
                    self.assertTrue(parent.rect().contains(preview.geometry()))
                    self.assertGreater(preview.x(), 0)
                    self.assertGreater(preview.y(), 0)
                    self.assertIs(preview.parentWidget(), parent)
                    self.assertEqual(int(preview.winId()), native_id)
        self.case.click(w.focus_button)
        self.assertFalse(w.canvas_panel.isVisible())
        self.case.click(w.focus_button)
        self.assertTrue(w.canvas_panel.isVisible())

    def test_canvas_retry_restores_record_and_pending_zoom_without_reloading(self):
        w = self.window
        engine = w.engine
        engine.reset_mock()
        engine.set_canvas.side_effect = RuntimeError('synthetic reset failure')
        self.case.choose(w.canvas, 'portrait')
        self.assertFalse(w.configuration_valid)
        self.assertFalse(w.record_button.isEnabled())
        w.camera_zoom.setValue(150)
        engine.set_canvas.side_effect = None
        self.case.choose(w.canvas, 'square')
        self.assertTrue(w.configuration_valid)
        self.assertTrue(w.record_button.isEnabled())
        self.assertEqual(engine.set_camera_framing.call_args.kwargs['camera_zoom'], 1.5)
        self.case.click(w.camera_zoom_plus)
        self.assertEqual(engine.set_camera_framing.call_args, call(camera_zoom=1.6))
        engine.configure.assert_not_called()
        engine.close.assert_not_called()

    def test_screen_quality_saves_immediately_with_camera_off(self):
        w = self.window
        self.case.click(w.screen_button)
        self.case.choose(w.camera, None)
        QTest.qWait(220)
        self.reveal(w.quality)
        w.quality.setCurrentIndex(1)
        self.assertEqual(w.prefs.value('quality'), w.quality.currentText())
        w.restore_preferences()
        self.assertEqual(w.quality.currentData(), (1920, 1080))

    def test_canvas_retry_does_not_validate_pending_device_configuration(self):
        w = self.window
        w._live_update_failed = True
        w.schedule_configure()
        w.configure_timer.stop()
        w.engine.reset_mock()
        w.canvas.setCurrentIndex(w.canvas.findData('portrait'))
        self.assertFalse(w.configuration_valid)
        self.assertFalse(w.record_button.isEnabled())
        w.engine.set_canvas.assert_not_called()
        w.engine.set_camera_framing.assert_not_called()
        self.assertTrue(w._configure_pending)
