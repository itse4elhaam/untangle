"""Inline geometry and asynchronous ownership checks with no real audio devices."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget

from untangle.audio_check import AudioCheck
from untangle.theme import load_fonts, stylesheet


qt = QApplication.instance() or QApplication([])


class InlineAudioCheckTests(unittest.TestCase):
    def setUp(self):
        self.font = qt.font()
        load_fonts(qt)
        self.engine, self.devices = MagicMock(), MagicMock()
        self.devices.prepare.return_value = 'synthetic.input'
        self.devices.source_label = 'Synthetic headset microphone'
        self.devices.restore.return_value = True
        self.engine.audio_status.return_value = dict(state='signal', peak_db=-18,
                                                    source='synthetic.input')
        self.sample = self.engine.begin_audio_check.return_value
        self.sample.frames = 4800
        self.sample.save.side_effect = lambda path: path.write_bytes(b'synthetic sample') and .25
        self.patches = [patch('untangle.audio_check.QMediaPlayer'),
                        patch('untangle.audio_check.QAudioOutput')]
        for mocked in self.patches:
            mocked.start()
        self.dialogs = []
        self.gates = []
        self.host = QWidget()
        self.dialog = self.make_dialog(inline=True)
        self.host.show()

    def make_dialog(self, **kwargs):
        dialog = AudioCheck(self.engine, self.devices, 'default', True,
                            'Synthetic headset microphone',
                            parent=self.host if kwargs.get('inline') else None, **kwargs)
        self.dialogs.append(dialog)
        return dialog

    def wait(self, dialog=None):
        dialog = dialog or self.dialog
        deadline = time.monotonic() + 4
        while dialog.worker and time.monotonic() < deadline:
            qt.processEvents()
            time.sleep(.001)
        qt.processEvents()
        self.assertIsNone(dialog.worker, 'Mocked worker did not finish')

    def tearDown(self):
        for gate in self.gates:
            gate.set()
        for dialog in self.dialogs:
            self.wait(dialog)
            dialog.reject()
            self.wait(dialog)
            dialog.deleteLater()
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        for mocked in reversed(self.patches):
            mocked.stop()
        qt.setFont(self.font)

    def assert_visible_inside(self, widget):
        self.assertTrue(widget.isVisible(), widget.objectName() or type(widget).__name__)
        top_left = widget.mapTo(self.dialog, QPoint())
        bottom_right = widget.mapTo(self.dialog, widget.rect().bottomRight())
        self.assertTrue(self.dialog.rect().contains(top_left))
        self.assertTrue(self.dialog.rect().contains(bottom_right))

    def test_compact_layout_fits_both_themes_with_readable_exits(self):
        dialog = self.dialog
        scroll = dialog.findChild(QScrollArea)
        states = (
            'Record four seconds, then choose Play sample to listen. No playback starts automatically.',
            'Speak now. Recording four seconds…',
            'Only silence detected. The sample contains zero-valued audio. Check mute, input volume '
            'and selected device, then retry. This does not identify the Bluetooth cause.',
            'Sample contains sound. Choose Play sample to review it. Signal does not prove clear speech.',
            'Playback is waiting for the headset to be released by other apps. Close their audio '
            'streams and retry Play sample.',
        )
        for theme in ('light', 'dark'):
            dialog.setStyleSheet(stylesheet(theme))
            for width in (610, 850):
                dialog.resize(width, 230)
                dialog.show()
                for state in states:
                    with self.subTest(theme=theme, width=width, state=state):
                        dialog.status.setText(state)
                        qt.processEvents()
                        self.assertEqual((dialog.width(), dialog.height()), (width, 230))
                        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                        self.assertEqual(scroll.verticalScrollBar().maximum(), 0)
                        widgets = (dialog.device, dialog.meter, dialog.status, dialog.record,
                                   dialog.play, dialog.stop, dialog.done_button,
                                   dialog.change_input_button)
                        for widget in widgets:
                            self.assert_visible_inside(widget)
                        for label in dialog.findChildren(QLabel):
                            if label.isVisible():
                                self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
                        for button in widgets[3:]:
                            self.assertGreaterEqual(button.width(), button.sizeHint().width())
                self.assertLess(dialog.done_button.y(), dialog.record.y())
        self.devices.prepare.assert_not_called()
        self.engine.begin_audio_check.assert_not_called()
        dialog.player.play.assert_not_called()

    def test_long_details_scroll_without_hiding_sample_controls_or_exit(self):
        dialog = self.dialog
        dialog.setStyleSheet(stylesheet('light'))
        dialog.device.setText('Synthetic microphone ' * 30)
        dialog.status.setText('Synthetic route failure. ' * 100)
        dialog.resize(610, 230)
        dialog.show()
        qt.processEvents()
        scroll = dialog.findChild(QScrollArea)
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        for button in (dialog.record, dialog.play, dialog.stop, dialog.done_button,
                       dialog.change_input_button):
            self.assert_visible_inside(button)
            self.assertFalse(scroll.isAncestorOf(button))

    def test_default_standalone_layout_is_preserved(self):
        dialog = self.make_dialog()
        self.assertTrue(dialog.isWindow())
        self.assertTrue(dialog.isModal())
        self.assertEqual((dialog.width(), dialog.height()), (420, 560))
        self.assertFalse(hasattr(dialog, 'change_input_button'))
        self.assertEqual(self.dialog.windowFlags() & Qt.WindowType_Mask, Qt.Widget)
        self.assertFalse(self.dialog.isModal())

    def test_sample_restores_before_explicit_play_and_back_cleans_up(self):
        dialog = self.dialog
        order = []
        self.engine.end_audio_check.side_effect = lambda: order.append('release')
        self.devices.restore.side_effect = lambda: order.append('restore') or True
        dialog.player.play.side_effect = lambda: order.append('play')
        dialog.record.click()
        self.wait()
        self.assertTrue(dialog.capturing)
        dialog.stop.click()
        self.wait()
        self.assertEqual(order, ['release', 'restore'])
        self.assertTrue(dialog.play.isEnabled())
        dialog.player.play.assert_not_called()
        dialog.play.click()
        self.wait()
        self.assertEqual(order, ['release', 'restore', 'restore', 'play'])
        dialog.done_button.click()
        self.assertFalse(dialog.path.parent.exists())
        self.devices.release_capture.assert_called_once_with(self.devices.hold_capture.return_value)

    def test_change_microphone_waits_for_preparation_and_restore(self):
        dialog = self.dialog
        gate = threading.Event()
        self.gates.append(gate)
        self.devices.prepare.side_effect = lambda _: gate.wait(3) and 'synthetic.input'
        rejected = MagicMock()
        dialog.rejected.connect(rejected)
        dialog.record.click()
        dialog.change_input_button.click()
        self.assertTrue(dialog.closing)
        rejected.assert_not_called()
        gate.set()
        self.wait()
        self.engine.end_audio_check.assert_called_once()
        self.devices.release_capture.assert_called_once_with(self.devices.hold_capture.return_value)
        self.devices.restore.assert_called_once()
        self.sample.save.assert_not_called()
        dialog.player.play.assert_not_called()
        rejected.assert_called_once()
        self.assertFalse(dialog.path.parent.exists())

    def test_back_during_capture_retains_ownership_until_restore_finishes(self):
        dialog = self.dialog
        dialog.record.click()
        self.wait()
        gate = threading.Event()
        self.gates.append(gate)
        self.devices.restore.side_effect = lambda: gate.wait(3)
        rejected = MagicMock()
        dialog.rejected.connect(rejected)
        dialog.done_button.click()
        self.assertTrue(dialog.closing)
        self.assertIsNotNone(dialog.worker)
        rejected.assert_not_called()
        self.assertTrue(dialog.path.parent.exists())
        gate.set()
        self.wait()
        rejected.assert_called_once()
        self.sample.save.assert_not_called()
        dialog.player.play.assert_not_called()
        self.assertFalse(dialog.path.parent.exists())


if __name__ == '__main__':
    unittest.main()
