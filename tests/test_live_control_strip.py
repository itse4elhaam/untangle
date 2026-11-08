"""Real start/cancel/pause controls with inert engine and devices."""
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication
import test_loom_workflow as workflow


class LiveControlStripTests(unittest.TestCase):
    def setUp(self):
        self.case = workflow.LoomWorkflowChecks()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.w = w = self.case.window
        w.timer.stop()
        w.configure_timer.stop()
        w.idle_audio.stop()
        self.stack.enter_context(patch.object(w, 'wayland_session', return_value=False))
        self.stack.enter_context(patch.object(workflow.glint.shutil, 'disk_usage', return_value=MagicMock(free=2**40)))
        self.stack.enter_context(patch.object(workflow.glint.QSystemTrayIcon, 'isSystemTrayAvailable', return_value=False))
        w.show()
        with patch.object(w, 'configure'):
            w.set_mode('screen', configure=False)
            w.capture_kind.setCurrentIndex(w.capture_kind.findData('screen'))
        w.microphone.setCurrentIndex(w.microphone.findData(None))
        w.selected_source = None
        w.engine.stats.return_value = {'recording': True, 'encoder': 'ffmpeg_vaapi'}
        w.configure_timer.stop()
        w.configure()
        self.assertTrue(w.configuration_valid, w.status.text())
        self.assertIsNotNone(w._configured_control_strip)
        w.engine.reset_mock()

    def begin(self):
        w = self.w
        w.toggle_record()
        self.assertTrue(w.counting)
        self.assertTrue(w.recording_controls.isVisible())
        self.assertEqual(w.recording_controls.stop_button.text(), 'Cancel')
        w.countdown = 1
        w.countdown_tick()
        w.start_timer.stop()
        self.assertFalse(w.isVisible())
        w.counting = False
        w.begin_recording()
        self.assertTrue(w.recording)
        w.engine.recording = True
        return w

    def test_start_is_live_by_default_and_pause_resume_keeps_bar_visible(self):
        self.w.hide_bubble()
        w = self.begin()
        self.assertFalse(w.paused)
        self.assertTrue(w.recording_controls.isVisible())
        self.assertTrue(w.recording_controls.strip_rect.contains(w.recording_controls.geometry()))
        w.engine.pause.assert_not_called()
        self.assertFalse(w.recording_controls.hide_button.isEnabled(), 'Last Stop route stays visible')
        w.recording_controls.pause_button.click()
        self.assertTrue(w.paused)
        w.recording_controls.pause_button.click()
        self.assertFalse(w.paused)
        self.assertTrue(w.recording_controls.isVisible())
        w.engine.start.assert_called_once()
        w.engine.release_audio.assert_not_called()
        self.assertFalse(w.camera.isEnabled())

    def test_countdown_cancel_from_strip_restores_setup_without_starting(self):
        w = self.w
        w.toggle_record()
        w.recording_controls.stop_button.click()
        self.assertFalse(w.counting)
        self.assertFalse(w.recording_controls.isVisible())
        self.assertTrue(w.camera.isEnabled())
        w.engine.start.assert_not_called()

    def test_configure_passes_physical_crop_and_camera_stays_above_it(self):
        w = self.w
        w.configure()
        screen, geometry, height, pixels = w._configured_control_strip
        kw = w.engine.configure.call_args.kwargs
        self.assertEqual(kw['screen_cut_bottom'], pixels)
        self.assertEqual(kw['screen_expected_size'], (
            round(geometry.width()*screen.devicePixelRatio()), round(geometry.height()*screen.devicePixelRatio())))
        w.show_bubble()
        self.assertTrue(w.camera_recording_bounds().contains(w.bubble.geometry()))
        self.assertIn('control strip', w.capture_caption.text())
        self.assertIn('strip excluded', w.preview_title.text())
        self.assertIn('excluded', w.preflight_summary())

    def test_display_change_pauses_hides_and_blocks_resume(self):
        w = self.begin()
        w.control_strip_display_changed()
        self.assertTrue(w.paused)
        self.assertTrue(w._control_strip_invalidated)
        self.assertFalse(w.recording_controls.isVisible())
        w.engine.pause.reset_mock()
        w.toggle_pause()
        self.assertTrue(w.paused)
        w.engine.pause.assert_not_called()
        self.assertIn('restart', w.status.text())

    def test_failed_pause_on_display_change_requests_stop(self):
        w = self.begin()
        w.engine.pause.side_effect = RuntimeError('synthetic pause failure')
        with patch.object(workflow.glint.FinishWorker, 'start'):
            w.control_strip_display_changed()
        self.assertTrue(w.busy)
        self.assertFalse(w.recording_controls.isVisible())

    def test_ambiguous_or_portal_capture_uses_existing_pause_policy(self):
        w = self.w
        with patch.object(QApplication, 'screens', return_value=[MagicMock(), MagicMock()]):
            self.assertIsNone(w.control_strip_spec())
        with patch.object(w, 'wayland_session', return_value=True):
            self.assertIsNone(w.control_strip_spec())

    def test_control_placement_failure_cannot_start_a_recording(self):
        w = self.w
        with patch.object(w, 'place_recording_controls', side_effect=ValueError('synthetic geometry mismatch')):
            w.begin_recording()
        w.engine.start.assert_not_called()
        self.assertFalse(w.recording)
        self.assertFalse(w.recording_controls.isVisible())
        self.assertIn('synthetic geometry mismatch', w.status.text())

    def test_post_start_failure_uses_stop_worker_without_releasing_live_audio(self):
        w = self.w
        w.engine.start.side_effect = lambda *a, **kw: setattr(w.engine, 'recording', True)
        w.engine.stats.side_effect = RuntimeError('synthetic stats failure')
        with patch.object(workflow.glint.FinishWorker, 'start'):
            w.begin_recording()
        self.assertTrue(w.recording)
        self.assertTrue(w.busy)
        self.assertIn('synthetic stats failure', w.recording_error)
        w.engine.release_audio.assert_not_called()
