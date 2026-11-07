"""Synthetic controls checks; no capture or host input."""
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from untangle.recording_controls import RecordingControls


class RecordingControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = RecordingControls()
        self.addCleanup(self.widget.finish)

    def update(self, **kwargs):
        values = dict(state='recording', elapsed='01:23', target='Editor', microphone='Input detected')
        values.update(kwargs)
        self.widget.update_state(**values)

    def test_actions_and_saving(self):
        calls = []
        self.widget.pause_requested.connect(lambda: calls.append('pause'))
        self.widget.stop_requested.connect(lambda: calls.append('stop'))
        self.widget.pause_button.click()
        self.update(state='paused')
        self.assertEqual(self.widget.pause_button.text(), 'Resume')
        self.widget.pause_button.click()
        self.widget.stop_button.click()
        self.assertEqual(calls, ['pause', 'pause', 'stop'])
        self.update(hide_allowed=False)
        self.assertFalse(self.widget.hide_button.isEnabled())
        self.update(state='saving')
        for button in (self.widget.pause_button, self.widget.stop_button,
                       self.widget.hide_button, self.widget.more_button):
            self.assertFalse(button.isEnabled())
        self.assertEqual(self.widget.state_label.text(), 'Saving')

    def test_title_focus_and_size(self):
        title = 'Very long editor title ' * 30
        self.update(target=title, warning='Saved audio unverified')
        self.widget.show()
        self.app.processEvents()
        self.assertEqual(self.widget.target_label.toolTip(), title)
        self.assertEqual(self.widget.target_label.accessibleName(), title)
        self.assertLess(len(self.widget.target_label.text()), len(title))
        self.assertIn('does not certify', self.widget.microphone_label.toolTip())
        for button in (self.widget.pause_button, self.widget.stop_button,
                       self.widget.hide_button, self.widget.more_button):
            self.assertEqual(button.focusPolicy(), Qt.NoFocus)
        self.assertTrue(self.widget.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        self.assertLessEqual(self.widget.width(), 650)
        self.assertLessEqual(self.widget.height(), 140)

    def test_hide_releases_input_and_close_is_caller_owned(self):
        calls = []
        self.widget.hide_requested.connect(lambda: calls.append('hide'))
        self.widget.show()
        self.assertFalse(self.widget.close())
        self.assertEqual(calls, ['hide'])
        with patch('untangle.recording_controls.floating.release_window_input') as release:
            self.widget.hide()
            release.assert_called_once_with(self.widget)
