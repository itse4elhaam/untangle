"""Capture controls preserve the take and never assume a stop shortcut works."""
import time
import unittest
from unittest.mock import patch

import test_loom_workflow as workflow


class ScreenRecordingExperienceTests(unittest.TestCase):
    def setUp(self):
        self.case = workflow.LoomWorkflowChecks()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.window = self.case.window
        self.window.mode = 'screen'
        self.window.show()
        workflow.qt.processEvents()

    def take(self, window=False):
        w = self.window
        w.capture_kind.setCurrentIndex(w.capture_kind.findData('window' if window else 'screen'))
        w.engine.reset_mock()
        w.record_path = self.case.path
        w.recording = True
        w.engine.recording = True
        w.started = time.monotonic() - 83
        w._take_target = 'Window · Synthetic editor' if window else 'Display · Synthetic desktop'
        w.selected_source = None
        w.hide()
        w.update_capture_controls()
        return w

    def test_no_tray_or_confirmed_shortcut_keeps_stop_visible(self):
        w = self.window
        with patch.object(workflow.glint.QSystemTrayIcon, 'isSystemTrayAvailable', return_value=False):
            w.hide_for_capture()
        self.assertTrue(w.isVisible())
        w.engine.detach_preview.assert_not_called()
        self.assertIn('no other Stop', w.status.text())

    def test_shortcut_loss_restores_a_stop_route(self):
        w = self.window
        w.counting = True
        w._shortcut_available['F9'] = True
        with patch.object(workflow.glint.QSystemTrayIcon, 'isSystemTrayAvailable', return_value=False):
            w.hide_for_capture()
            self.assertFalse(w.isVisible())
            w.shortcut_availability('F9', False)
        self.assertTrue(w.isVisible())
        w.counting = False

    def test_whole_display_controls_pause_before_show_and_hide_before_resume(self):
        w = self.take()
        w._shortcut_available['F9'] = True
        with patch.object(w, 'wayland_session', return_value=False):
            w.show_recording_controls()
            self.assertTrue(w.paused)
            self.assertTrue(w.recording_controls.isVisible())
            self.assertIn('01:23', w.recording_controls.elapsed_label.text())
            self.assertEqual(w.recording_controls.pause_button.text(), 'Resume')
            seen = []
            w.engine.pause.side_effect = lambda paused: seen.append((paused, w.recording_controls.isVisible()))
            w.recording_controls.pause_button.click()
            self.assertEqual(seen, [(False, False)])
            self.assertFalse(w.paused)
        w.engine.configure.assert_not_called()
        w.engine.release_audio.assert_not_called()

    def test_window_controls_do_not_pause_capture_and_cannot_hide_last_stop(self):
        w = self.take(window=True)
        with patch.object(w, 'wayland_session', return_value=False), patch.object(
                workflow.glint.QSystemTrayIcon, 'isSystemTrayAvailable', return_value=False):
            w.show_recording_controls()
            self.assertFalse(w.paused)
            w.engine.pause.assert_not_called()
            self.assertTrue(w.recording_controls.isVisible())
            self.assertFalse(w.recording_controls.hide_button.isEnabled())
            w.hide_recording_controls()
            self.assertTrue(w.recording_controls.isVisible())
            w.shortcut_availability('F9', True)
            w.recording_controls.hide_button.click()
            self.assertFalse(w.recording_controls.isVisible())

    def test_shortcut_loss_while_paused_cannot_hide_the_last_stop_on_resume(self):
        w = self.take()
        w._shortcut_available['F9'] = True
        with patch.object(workflow.glint.QSystemTrayIcon, 'isSystemTrayAvailable', return_value=False):
            w.show_recording_controls()
            w.shortcut_availability('F9', False)
            w.engine.pause.reset_mock()
            w.recording_controls.pause_button.click()
            self.assertTrue(w.paused)
            self.assertTrue(w.recording_controls.isVisible())
            w.engine.pause.assert_not_called()
            self.assertIn('needs Stop control', w.recording_controls.state_label.text())
            w.reveal()
            w.recording_controls.pause_button.click()
            self.assertFalse(w.paused)
            self.assertTrue(w.isVisible())

    def test_failed_resume_retains_pause_and_reachable_controls(self):
        w = self.take()
        w._shortcut_available['F9'] = True
        w.show_recording_controls()
        w.engine.pause.side_effect = RuntimeError('synthetic resume failure')
        w.toggle_pause()
        self.assertTrue(w.paused)
        self.assertTrue(w.recording_controls.isVisible())
        self.assertIn('synthetic resume failure', w.status.text())

    def test_saving_disables_dock_and_failed_stop_restores_retry(self):
        w = self.take(window=True)
        w.show_recording_controls()
        with patch.object(workflow.glint.FinishWorker, 'start'):
            w.recording_controls.stop_button.click()
        self.assertTrue(w.busy)
        self.assertFalse(w.recording_controls.stop_button.isEnabled())
        self.assertFalse(w.recording_controls.pause_button.isEnabled())
        w.stopped('', 'synthetic stopping delay')
        self.assertTrue(w.recording)
        self.assertFalse(w.busy)
        self.assertTrue(w.recording_controls.stop_button.isEnabled())

    def test_portal_target_is_honest_and_microphone_warning_reaches_tray(self):
        w = self.take()
        with patch.object(w, 'wayland_session', return_value=True):
            self.assertEqual(w.capture_target_label(), 'System-selected source')
            self.assertFalse(w.window_controls_safe())
        w.selected_source = 'synthetic-microphone'
        w.engine.audio_status.return_value = {'state': 'no_packets'}
        w.recording_error = 'Microphone samples stopped arriving. Review before sharing.'
        w.update_capture_controls()
        self.assertIn('No microphone samples', w.tray.toolTip())
        self.assertIn('Review before sharing', w.tray.toolTip())
        self.assertIn('Microphone samples stopped', w.recording_controls.microphone_label.toolTip())
