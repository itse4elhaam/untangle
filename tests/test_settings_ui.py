"""Settings and recorder navigation with synthetic devices, never live capture."""
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QScrollArea

from untangle import app as glint
from untangle.theme import tokens
import test_ui_clickthrough as ui


class SettingsUITests(unittest.TestCase):
    def setUp(self):
        self.case = ui.ClearlineClickthrough()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.window = self.case.window

    def test_only_secondary_controls_move_into_settings(self):
        w = self.window
        moved = (w.theme_choice, w.auto_titles, w.live_microphone, w.desktop_audio, w.mirror,
                 w.clean_microphone, w.quality, w.shape, w.size, w.position)
        for control in moved:
            with self.subTest(control=control.accessibleName() or type(control).__name__):
                self.assertIs(control.window(), w.settings_dialog)
                self.assertFalse(control.isVisible())
                self.assertFalse(w.controls_panel.isAncestorOf(control))
        for control in (w.camera, w.microphone, w.camera_zoom, w.canvas,
                        w.audio_check_button, w.record_button, w.microphone_meter):
            self.assertIs(control.window(), w)
            self.case.visible_control(control)
        self.case.open_settings()
        for control in (w.theme_choice, w.live_microphone, w.desktop_audio,
                        w.mirror, w.clean_microphone, w.quality):
            self.case.reveal_setting(control)
        self.assertFalse(w.widget_panel.isVisible(), 'Screen overlay controls belong to screen mode')
        self.case.close_settings()
        self.case.click(w.screen_button)
        QTest.qWait(220)
        self.case.open_settings()
        for control in (w.shape, w.size, w.position):
            self.case.reveal_setting(control)

    def test_settings_defaults_and_done_persist_choices_across_a_new_window(self):
        w = self.window
        self.case.open_settings()
        self.assertEqual(w.theme_choice.currentData(), 'light')
        self.assertTrue(w.live_microphone.isChecked())
        self.assertTrue(w.auto_titles.isChecked())
        self.assertFalse(w.desktop_audio.isChecked())
        self.assertTrue(w.mirror.isChecked())
        self.assertTrue(w.clean_microphone.isChecked())
        self.assertEqual(w.quality.currentData(), (3840, 2160))
        self.case.reveal_setting(w.theme_choice)
        self.case.choose(w.theme_choice, 'dark')
        for control in (w.auto_titles, w.live_microphone, w.desktop_audio, w.mirror, w.clean_microphone):
            self.case.reveal_setting(control)
            self.case.click(control)
        self.case.reveal_setting(w.quality)
        self.case.choose(w.quality, (1920, 1080))
        self.case.close_settings()
        self.case.click(w.sidebar_button)
        self.case.close_window()
        # Keep all fixture patches, including OBS initialization and device access.
        self.window = self.case.window = restored = glint.Window()
        restored.show()
        restored.activateWindow()
        QTest.qWait(20)
        self.case.open_settings()
        self.assertEqual(restored.theme_choice.currentData(), 'dark')
        self.assertEqual(ui.qt.property('untangleTheme'), 'dark')
        self.assertFalse(restored.live_microphone.isChecked())
        self.assertFalse(restored.auto_titles.isChecked())
        self.assertTrue(restored.desktop_audio.isChecked())
        self.assertFalse(restored.mirror.isChecked())
        self.assertFalse(restored.clean_microphone.isChecked())
        self.assertEqual(restored.quality.currentData(), (1920, 1080))
        self.assertFalse(restored.sidebar_button.isChecked())
        self.assertFalse(restored.controls_panel.isVisible())
        self.assertFalse(restored.navigation_footer.isVisible())

    def test_header_start_stays_available_when_sidebar_is_hidden(self):
        w = self.window
        self.assertTrue(w.sidebar_button.isCheckable())
        self.assertTrue(w.sidebar_button.isChecked())
        action = self.case.bounds(w.record_button)
        self.assertLess(action.bottom(), self.case.bounds(w.preview).top())
        self.assertGreater(action.left(), self.case.bounds(w.settings_button).right())
        self.assertLessEqual(w.recorder_page.width() - action.right(), 30)
        before = (w.camera.currentData(), w.microphone.currentData(), w.canvas.currentData())
        w.engine.reset_mock()
        self.case.click(w.sidebar_button)
        self.assertFalse(w.controls_panel.isVisible())
        self.assertFalse(w.navigation_footer.isVisible())
        self.assertEqual(w.prefs.value('sidebar_visible', type=bool), False)
        for control in (w.record_button, w.settings_button, w.sidebar_button,
                        w.canvas, w.microphone_meter):
            self.case.visible_control(control)
        self.assertEqual(self.case.bounds(w.record_button), action)
        self.case.open_settings()
        self.case.close_settings()
        self.assertFalse(w.controls_panel.isVisible())
        self.case.click(w.sidebar_button)
        self.case.visible_control(w.controls_panel)
        self.case.visible_control(w.navigation_footer)
        self.assertEqual((w.camera.currentData(), w.microphone.currentData(), w.canvas.currentData()), before)
        w.engine.configure.assert_not_called()
        w.engine.close.assert_not_called()

    def test_expand_and_restore_camera_respects_hidden_sidebar(self):
        w = self.window
        self.case.click(w.sidebar_button)
        self.case.click(w.focus_button)
        self.assertFalse(w.controls_panel.isVisible())
        self.assertFalse(w.navigation_footer.isVisible())
        self.case.click(w.focus_button)
        self.assertFalse(w.controls_panel.isVisible())
        self.assertFalse(w.navigation_footer.isVisible())
        self.case.visible_control(w.canvas)
        self.case.click(w.sidebar_button)
        self.case.visible_control(w.camera)
        self.case.visible_control(w.library_button)

    def test_settings_keyboard_focus_has_one_solid_ring_and_no_extra_frames(self):
        w = self.window
        for theme in ('light', 'dark'):
            self.case.choose_theme(theme)
            self.case.open_settings()
            self.assertEqual(w.settings_dialog.findChild(QScrollArea).frameWidth(), 0)
            self.assertNotRegex(ui.qt.styleSheet(), r'(?:border|outline)\s*:[^;{}]*\b(?:dashed|dotted)\b')
            for control in (w.theme_choice, w.live_microphone, w.desktop_audio,
                            w.mirror, w.clean_microphone, w.quality):
                with self.subTest(theme=theme, control=type(control).__name__):
                    self.case.reveal_setting(control)
                    w.settings_dialog.setFocus()
                    ui.qt.processEvents()
                    before = (control.geometry(), control.sizeHint(), control.contentsRect())
                    control.setFocus(Qt.TabFocusReason)
                    ui.qt.processEvents()
                    self.assertTrue(control.hasFocus())
                    self.assertEqual((control.geometry(), control.sizeHint(), control.contentsRect()), before)
                    image = control.grab().toImage()
                    center = image.width() // 2
                    expected = QColor(tokens(theme)['focus'])
                    rows = [y for y in range(4)
                            if all(image.pixelColor(x, y) == expected
                                   for x in range(center - 8, center + 8))]
                    self.assertEqual(len(rows), 1, 'Keyboard focus needs exactly one solid border')
            self.case.close_settings()

    def test_keyboard_combo_selection_keeps_settings_open_until_done(self):
        w = self.window
        self.case.open_settings()
        for combo, value in ((w.theme_choice, 'dark'), (w.quality, (1920, 1080))):
            self.case.reveal_setting(combo)
            self.case.choose(combo, value)
            self.assertTrue(w.settings_dialog.isVisible(), 'Enter must commit the combo without closing Settings')
        self.case.close_settings()

    def test_tab_navigation_reaches_and_reveals_settings_controls_in_both_modes(self):
        w = self.window
        for mode in ('camera', 'screen'):
            with self.subTest(mode=mode):
                self.case.click(getattr(w, mode + '_button'))
                QTest.qWait(220)
                dialog = self.case.open_settings()
                dialog.resize(560, 480)
                self.case.reveal_setting(w.theme_choice)
                w.theme_choice.setFocus(Qt.TabFocusReason)
                required = {w.theme_choice, w.auto_titles, w.live_microphone,
                            w.desktop_audio, w.mirror, w.clean_microphone, w.quality}
                if mode == 'screen':
                    required.update((w.shape, w.size, w.position))
                visited = set()
                for _ in range(40):
                    focused = ui.qt.focusWidget()
                    if focused in required:
                        name = next(name for name in ('theme_choice', 'auto_titles', 'live_microphone',
                                    'desktop_audio', 'mirror', 'clean_microphone', 'quality',
                                    'shape', 'size', 'position') if getattr(w, name) is focused)
                        with self.subTest(control=name):
                            self.case.visible_control(focused)
                        visited.add(focused)
                    if visited == required:
                        break
                    QTest.keyClick(focused, Qt.Key_Tab)
                    QTest.qWait(10)
                self.assertEqual(visited, required, 'Tab must reach each setting and scroll it into view')
                self.case.close_settings()

    def test_settings_entry_is_locked_during_countdown(self):
        w = self.window
        self.case.click(w.record_button)
        self.assertTrue(w.counting)
        self.assertFalse(w.settings_button.isEnabled())
        w.open_settings()
        self.assertFalse(w.settings_dialog.isVisible())
        QTest.keyClick(w, Qt.Key_Escape)
        self.case.wait_for(lambda: not w.counting, 'Escape did not cancel the countdown')
        self.assertTrue(w.settings_button.isEnabled())
        self.case.open_settings()
        w.engine.start.assert_not_called()
