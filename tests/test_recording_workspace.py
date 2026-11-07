"""Recording controls survive review navigation without changing the active take."""
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog
import test_loom_workflow as workflow


class RecordingWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.case = workflow.LoomWorkflowChecks()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.window = self.case.window
        self.window.resize(960, 760)
        self.window.show()
        workflow.qt.processEvents()

    def begin(self):
        w = self.window
        w.microphone.setCurrentIndex(w.microphone.findData(None))
        w.audio_devices.prepare.return_value = None
        w.selected_source = None
        w.configuration_valid = True
        w.engine.stats.return_value = {'recording': True, 'encoder': 'ffmpeg_vaapi'}
        w.lock_controls(True)
        w.begin_recording()
        self.assertTrue(w.recording)
        w.started = time.monotonic() - 83
        w.tick()
        return w

    def test_library_review_preserves_capture_and_stop_remains_reachable(self):
        w = self.begin()
        w.selected_source = 'test-microphone'
        w.audio_devices.resolve.return_value = 'test-microphone'
        w._capture_owner = 'synthetic-capture-owner'
        w.engine.audio_status.return_value = dict(state='signal', source='test-microphone', peak_db=-18)
        original = (w.mode, w.camera.currentData(), w.canvas.currentData(), w.selected_source)
        w.engine.reset_mock()
        w.audio_devices.reset_mock()
        w.library_button.click()
        workflow.qt.processEvents()
        self.assertTrue(w.in_library())
        self.assertTrue(w.record_button.isVisible())
        self.assertTrue(w.record_button.isEnabled())
        self.assertTrue(w.pause_button.isVisible())
        self.assertIn('01:23', w.recording_timer.text())
        w.engine.release_audio.assert_not_called()
        w.engine.reset_portal.assert_not_called()
        w.engine.detach_camera_preview.assert_not_called()
        w.audio_devices.release_capture.assert_not_called()
        w.pause_button.click()
        frozen = w.recording_timer.text()
        self.assertTrue(w.paused)
        self.assertIn('Paused', frozen)
        self.assertEqual((w.mode, w.camera.currentData(), w.canvas.currentData(), w.selected_source), original)
        self.assertFalse(w.camera.isEnabled())
        self.assertFalse(w.canvas.isEnabled())
        w.engine.start.assert_not_called()
        w.engine.configure.assert_not_called()
        with patch.object(workflow.glint.FinishWorker, 'start'):
            w.record_button.click()
        self.assertTrue(w.busy)
        self.assertFalse(w.in_library())
        self.assertFalse(w.record_button.isEnabled())
        self.assertIn('Saving', w.status.text())

    def test_timer_stays_visible_with_details_closed_and_freezes_when_paused(self):
        w = self.begin()
        self.assertFalse(w.details_toggle.isChecked())
        self.assertTrue(w.recording_timer.isVisible())
        self.assertFalse(w.status.isVisible())
        w.pause_button.click()
        frozen = w.recording_timer.text()
        with patch('untangle.app.time.monotonic', return_value=time.monotonic() + 5):
            w.tick()
        self.assertEqual(w.recording_timer.text(), frozen)
        self.assertTrue(w.recording_timer.isVisible())
        w.pause_button.click()
        self.assertFalse(w.paused)
        self.assertIn('Recording', w.recording_timer.text())

    def test_sharing_can_be_inspected_without_mutating_active_take_preferences(self):
        w = self.begin()
        before = {name: w.prefs.value(name) for name in ('auto_upload', 'visibility', 'loom_auto_titles')}
        def inspect():
            dialog = workflow.qt.activeModalWidget()
            self.assertIsInstance(dialog, QDialog)
            mutable = dialog.findChildren(QCheckBox) + dialog.findChildren(QComboBox)
            self.assertTrue(mutable)
            self.assertTrue(all(not control.isEnabled() for control in mutable))
            self.assertTrue(w.recording)
            dialog.accept()
        QTimer.singleShot(0, inspect)
        w.sharing_button.click()
        self.assertEqual({name: w.prefs.value(name) for name in before}, before)
        self.assertTrue(w.recording)

    def test_idle_review_page_cannot_start_a_new_take(self):
        page = self.case.open_library()
        page.files.setCurrentRow(0)
        self.assertTrue(page.player.source().isEmpty())
        page.player.play.assert_not_called()
        w = self.window
        self.assertFalse(w.record_button.isEnabled(), 'Starting from the review page stays unavailable')
        page.back.click()
        workflow.qt.processEvents()
        self.assertTrue(w.record_button.isEnabled())
