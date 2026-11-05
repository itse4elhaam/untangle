"""Portal readiness checks with synthetic UI and engine objects."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from untangle.app import Window


class WaylandUiChecks(unittest.TestCase):
    def window(self):
        w = SimpleNamespace(engine=MagicMock(), mode='screen', recording=False,
            busy=False, counting=False, _configure_pending=False,
            _portal_configured=True, _closing=False, in_library=lambda: False,
            record_button=MagicMock(), notice=MagicMock(), stop=MagicMock(),
            wayland_session=lambda: True)
        return w

    def test_pending_permission_disables_record(self):
        w = self.window()
        w.engine.screen_ready.return_value = False
        Window.poll_portal(w)
        self.assertFalse(w.configuration_valid)
        w.record_button.setEnabled.assert_called_with(False)

    def test_ready_permission_enables_record(self):
        w = self.window()
        w.engine.screen_ready.return_value = True
        Window.poll_portal(w)
        self.assertTrue(w.configuration_valid)
        w.record_button.setEnabled.assert_called_with(True)

    def test_lost_stream_stops_recording(self):
        w = self.window()
        w.recording = True
        w.engine.screen_ready.return_value = False
        Window.poll_portal(w)
        w.stop.assert_called_once()

    def test_pending_timeout_releases_source(self):
        w = self.window()
        w.engine.screen_ready.return_value = False
        w._portal_wait_started = 1
        with patch('untangle.app.time.monotonic', return_value=122):
            Window.poll_portal(w)
        w.engine.reset_portal.assert_called_once()

    def test_session_detection(self):
        with patch.dict(os.environ, XDG_SESSION_TYPE='wayland'):
            self.assertTrue(Window.wayland_session())

    def test_failed_setup_is_not_marked_ready_by_permission_poll(self):
        w = self.window()
        w._portal_configured = False
        Window.poll_portal(w)
        w.engine.screen_ready.assert_not_called()
        w.record_button.setEnabled.assert_not_called()

    def test_library_does_not_enable_recording(self):
        w = self.window()
        w.in_library = lambda: True
        Window.poll_portal(w)
        w.record_button.setEnabled.assert_not_called()

    def test_unsupported_pointer_zoom_does_nothing(self):
        w = self.window()
        Window.toggle_zoom(w)
        w.engine.set_screen_zoom.assert_not_called()

    def test_video_reset_failure_stays_disabled(self):
        w = self.window()
        w._live_update_failed = True
        Window.poll_portal(w)
        w.record_button.setEnabled.assert_not_called()
