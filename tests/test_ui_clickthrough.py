"""Pinned Clearline UX checks, using real Qt input and synthetic devices only.

Run: QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_ui_clickthrough.py -v
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from untangle import app as glint

qt = QApplication.instance() or QApplication([])


class ClearlineClickthrough(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        devices = MagicMock()
        devices.lease = None
        devices.prepare.return_value = 'test-microphone'
        devices.resolve.return_value = 'test-microphone'
        for replacement in (
            patch.object(glint, 'AudioDevices', return_value=devices),
            patch.object(glint.Window, 'initialize'),
            patch.object(glint.Hotkeys, 'start'),
            patch.object(glint.WindowCatalog, 'list', return_value=[('Synthetic editor', 4242)]),
            patch.object(glint.WindowCatalog, 'geometry', return_value=(0, 0, 1280, 720)),
            patch.object(glint, 'cameras', return_value=[
                ('Test camera', '/dev/video-test'), ('Second camera', '/dev/video-second')]),
            patch.object(glint, 'microphones', return_value=[('Test microphone', 'test-microphone')]),
            patch.object(glint, 'VIDEOS', self.root),
            patch.object(glint, 'STATE', self.root),
            patch.object(glint, 'QSettings', return_value=QSettings(
                str(self.root / 'prefs.ini'), QSettings.IniFormat)),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)
        self.window = glint.Window()
        self.addCleanup(self.close_window)
        self.window.engine = MagicMock()
        self.window.engine.recording = False
        self.window.engine.errors = []
        self.window.engine.audio_status.return_value = {
            'state': 'signal', 'source': 'test-microphone', 'peak_db': -18.0,
        }
        self.window.engine.verify_audio_route.return_value = 'test-microphone'
        self.window.configure()
        self.window.show()
        self.window.activateWindow()
        QTest.qWait(30)

    def close_window(self):
        dialog = getattr(self.window, 'audio_check_dialog', None)
        if dialog:
            dialog.close()
            qt.processEvents()
        self.window.recording = self.window.busy = self.window.counting = False
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_primary_setup_is_available_without_expanding_sections(self):
        for name in ('screen_button', 'camera_button', 'canvas', 'framing', 'canvas_note',
                     'camera', 'camera_zoom', 'camera_zoom_value', 'camera_zoom_reset', 'microphone'):
            with self.subTest(control=name):
                self.assertTrue(getattr(self.window, name).isVisible(),
                    f'{name} must be visible without opening a setup accordion')

    def test_canvas_is_above_preview_and_camera_zoom_stays_with_camera(self):
        w = self.window
        for control in (w.canvas, w.framing):
            self.visible_control(control)
            self.assertFalse(w.controls_panel.isAncestorOf(control))
            self.assertLess(self.bounds(control).bottom(), self.bounds(w.preview).top())
            self.assertGreaterEqual(self.bounds(control).left(), self.bounds(w.preview).left() - 2)
        self.assertGreater(self.bounds(w.camera_zoom).top(), self.bounds(w.camera).bottom())
        self.assertLess(self.bounds(w.camera_zoom).bottom(), self.bounds(w.microphone).top())

    def test_setup_is_left_of_prominent_preview(self):
        setup = self.window.controls_panel
        preview = self.window.preview
        left = setup.mapTo(self.window, QPoint(0, 0))
        right = preview.mapTo(self.window, QPoint(0, 0))
        self.assertLess(left.x(), right.x(), 'Setup must be left of the preview')
        self.assertLessEqual(left.x() + setup.width(), right.x())
        self.assertGreater(preview.width(), setup.width(), 'Preview must be wider than setup')

    def wait_for(self, predicate, message, timeout=1500):
        for _ in range(timeout // 10):
            if predicate():
                return
            QTest.qWait(10)
        self.assertTrue(predicate(), message)

    def bounds(self, widget):
        from PySide6.QtCore import QRect
        return QRect(widget.mapTo(self.window, QPoint(0, 0)), widget.size())

    def visible_control(self, widget):
        self.assertTrue(widget.isVisible(), f'{widget.objectName() or type(widget).__name__} is hidden')
        rect = self.bounds(widget)
        self.assertTrue(self.window.rect().contains(rect), f'Control outside window: {rect}')
        parent = widget.parentWidget()
        while parent and parent is not self.window:
            self.assertTrue(self.bounds(parent).contains(rect),
                            f'Control clipped by {parent.objectName() or type(parent).__name__}')
            parent = parent.parentWidget()

    def click(self, widget):
        self.visible_control(widget)
        self.assertTrue(widget.isEnabled(), 'Cannot click a disabled control')
        QTest.mouseClick(widget, Qt.LeftButton, pos=QPoint(10, widget.height() // 2))
        QTest.qWait(20)

    def choose(self, combo, data):
        index = combo.findData(data)
        self.assertGreaterEqual(index, 0, f'Missing option {data!r}')
        self.click(combo)
        QTest.keyClick(combo, Qt.Key_Home)
        for _ in range(index):
            QTest.keyClick(combo, Qt.Key_Down)
        QTest.keyClick(combo, Qt.Key_Return)
        self.assertEqual(combo.currentData(), data)
        QTest.qWait(220)  # Let the real configuration debounce process the selection.

    def choose_output(self, combo, data):
        """Exercise live output updates and detect any unintended engine reconstruction."""
        engine = self.window.engine
        def initialize():
            self.window.engine = engine
            self.window.configure()
        with patch.object(self.window, 'initialize', side_effect=initialize) as start:
            self.choose(combo, data)
        return engine, start

    def test_canvas_choices_update_existing_engine_and_preserve_quality(self):
        w = self.window
        quality = [(w.quality.itemText(i), w.quality.itemData(i))
                   for i in range(w.quality.count())]
        self.assertEqual(quality, [('4K · 30 fps', (3840, 2160)),
                                   ('1080p · 30 fps', (1920, 1080))])
        self.assertEqual(w.canvas.currentData(), 'landscape')
        for canvas, ratio in (('portrait', 9 / 16), ('square', 1),
                              ('portrait45', 4 / 5), ('landscape', 16 / 9)):
            with self.subTest(canvas=canvas):
                engine = w.engine
                engine.close.reset_mock()
                _, initialize = self.choose_output(w.canvas, canvas)
                engine.close.assert_not_called()
                initialize.assert_not_called()
                engine.set_canvas.assert_called_with(*w.output_dimensions())
                width, height = w.output_dimensions()
                self.assertAlmostEqual(width / height, ratio, places=2)
                self.assertIn(str(width), w.canvas_note.text())
                self.assertIn(str(height), w.canvas_note.text())
                self.assertEqual(w.quality.currentData(), (3840, 2160))
                self.assertTrue(w.record_button.isEnabled())
        self.assertIn('9:16', w.canvas.itemText(w.canvas.findData('portrait')))

    def test_camera_zoom_keyboard_reset_framing_and_camera_off(self):
        w = self.window
        self.assertEqual((w.camera_zoom.minimum(), w.camera_zoom.maximum()), (100, 300))
        self.assertEqual(w.camera_zoom.value(), 100)
        self.assertEqual(w.camera_zoom_value.text(), '100%')
        self.click(w.camera_zoom)
        QTest.keyClick(w.camera_zoom, Qt.Key_End)
        QTest.qWait(220)
        self.assertEqual(w.camera_zoom.value(), 300)
        self.assertEqual(w.camera_zoom_value.text(), '300%')
        self.assertEqual(w.engine.set_camera_framing.call_args.kwargs['camera_zoom'], 3.0)
        self.choose(w.framing, 'fill')
        self.assertEqual(w.engine.set_camera_framing.call_args.kwargs['framing'], 'fill')
        self.choose(w.framing, 'fit')
        self.assertEqual(w.engine.set_camera_framing.call_args.kwargs['framing'], 'fit')
        self.click(w.camera_zoom_reset)
        self.assertEqual(w.camera_zoom.value(), 100)
        self.assertEqual(w.camera_zoom_value.text(), '100%')
        QTest.qWait(220)
        self.assertEqual(w.engine.set_camera_framing.call_args.kwargs['camera_zoom'], 1.0)
        self.choose(w.camera, None)
        for control in (w.camera_zoom, w.camera_zoom_reset):
            self.visible_control(control)
            self.assertFalse(control.isEnabled())
        self.choose(w.camera, '/dev/video-test')
        self.assertTrue(w.camera_zoom.isEnabled())

    def test_canvas_zoom_and_framing_preferences_round_trip(self):
        w = self.window
        self.choose_output(w.canvas, 'portrait45')
        self.choose(w.framing, 'fill')
        self.click(w.camera_zoom)
        QTest.keyClick(w.camera_zoom, Qt.Key_End)
        QTest.qWait(220)
        w.save_preferences()
        # Reset widgets without saving defaults over the stored choices.
        for widget, value in ((w.canvas, 'landscape'), (w.framing, 'fit')):
            widget.blockSignals(True)
            widget.setCurrentIndex(widget.findData(value))
            widget.blockSignals(False)
        w.camera_zoom.blockSignals(True)
        w.camera_zoom.setValue(100)
        w.camera_zoom.blockSignals(False)
        w.restore_preferences()
        self.assertEqual(w.canvas.currentData(), 'portrait45')
        self.assertEqual(w.framing.currentData(), 'fill')
        self.assertEqual(w.camera_zoom.value(), 300)
        self.assertEqual(w.camera_zoom_value.text(), '300%')

    def test_more_options_scrolls_fields_into_view_at_minimum_size(self):
        w = self.window
        w.resize(960, 760)
        for theme in ('light', 'dark'):
            self.choose(w.theme_choice, theme)
            for mode in ('camera', 'screen'):
                with self.subTest(theme=theme, mode=mode):
                    self.click(getattr(w, mode + '_button'))
                    QTest.qWait(220)
                    disclosure = w.setup_sections[0]
                    w.controls_panel.ensureWidgetVisible(disclosure)
                    QTest.qWait(20)
                    self.click(disclosure)
                    self.wait_for(lambda: w.quality.isVisible(), 'More options did not open')
                    QTest.qWait(30)
                    fields = [w.mirror, w.clean_microphone, w.quality]
                    if mode == 'screen':
                        fields += [w.shape, w.size, w.position]
                    for control in fields:
                        self.visible_control(control)
                    self.assertEqual(w.controls_panel.horizontalScrollBar().maximum(), 0)
                    # Scroll back to the actual disclosure before closing it.
                    w.controls_panel.ensureWidgetVisible(disclosure)
                    QTest.qWait(20)
                    self.click(disclosure)
                    w.controls_panel.verticalScrollBar().setValue(0)
                    QTest.qWait(20)

    def test_modes_and_camera_device_changes_use_visible_controls(self):
        w = self.window
        self.click(w.screen_button)
        self.wait_for(lambda: w.mode == 'screen' and w.record_button.isEnabled(), 'Screen mode did not become ready')
        self.assertTrue(w.screen_button.isChecked())
        self.assertFalse(w.camera_button.isChecked())
        self.assertEqual(w.engine.configure.call_args.kwargs['mode'], 'screen')
        self.choose(w.camera, '/dev/video-second')
        self.assertEqual(w.engine.configure.call_args.kwargs['camera'], '/dev/video-second')
        self.click(w.camera_button)
        self.wait_for(lambda: w.mode == 'camera' and w.record_button.isEnabled(), 'Camera mode did not become ready')
        self.assertTrue(w.camera_button.isChecked())
        self.assertFalse(w.screen_button.isChecked())
        self.choose(w.camera, None)
        self.assertFalse(w.record_button.isEnabled())
        self.assertIn('camera', w.status.text().lower())
        self.choose(w.camera, '/dev/video-test')
        self.assertTrue(w.record_button.isEnabled())

    def test_microphone_selection_and_live_off_have_explicit_visible_status(self):
        w = self.window
        self.choose(w.microphone, 'test-microphone')
        self.assertTrue(w.microphone_meter.isVisible())
        self.click(w.live_microphone)
        self.assertFalse(w.live_microphone.isChecked())
        self.wait_for(lambda: 'off' in w.microphone_meter.message.text().lower(),
                      'Turning live monitoring off needs an explicit visible status')
        self.choose(w.microphone, None)
        self.wait_for(lambda: 'microphone off' in w.microphone_meter.message.text().lower(),
                      'Microphone off must be distinguished from live monitoring off')
        self.visible_control(w.microphone_meter.message)
        self.choose(w.microphone, 'test-microphone')
        self.click(w.live_microphone)
        self.assertTrue(w.live_microphone.isChecked())
        self.wait_for(lambda: 'off' not in w.microphone_meter.message.text().lower(),
                      'Enabling live monitoring must clear the stale off status')

    def assert_composition_locked(self):
        w = self.window
        controls = (w.canvas, w.framing, w.camera_zoom, w.camera_zoom_reset)
        before = (w.canvas.currentData(), w.framing.currentData(), w.camera_zoom.value())
        for control in controls:
            self.assertIn(control, w.config_controls)
            self.assertFalse(control.isEnabled())
            QTest.keyClick(control, Qt.Key_End)
            QTest.mouseClick(control, Qt.LeftButton)
        self.assertEqual((w.canvas.currentData(), w.framing.currentData(),
                          w.camera_zoom.value()), before)
        # Queued signals must also respect the state guard after inputs lock.
        engine = w.engine
        close_count = engine.close.call_count
        w.quality_changed()
        w.schedule_configure()
        self.assertIs(w.engine, engine)
        self.assertEqual(engine.close.call_count, close_count)
        self.assertFalse(w.configure_timer.isActive())

    def test_start_countdown_escape_unlocks_without_capture(self):
        w = self.window
        engine = w.engine
        self.click(w.record_button)
        self.assertTrue(w.counting)
        self.assert_composition_locked()
        self.assertIn('3', w.record_button.text())
        self.assertFalse(w.camera.isEnabled())
        self.assertFalse(w.microphone.isEnabled())
        QTest.qWait(1050)
        self.assertIn('2', w.record_button.text())
        QTest.keyClick(w, Qt.Key_Escape)
        self.wait_for(lambda: not w.counting, 'Escape did not cancel the countdown')
        self.assertTrue(w.camera.isEnabled())
        self.assertTrue(w.microphone.isEnabled())
        self.assertTrue(w.record_button.isEnabled())
        self.assertIn('cancel', w.status.text().lower())
        self.assertFalse(w.count_timer.isActive())
        self.assertFalse(w.start_timer.isActive())
        engine.start.assert_not_called()

    def test_audio_check_return_is_visible_and_restores_source_controls(self):
        w = self.window
        self.wait_for(lambda: not w.audio_worker or not w.audio_worker.isRunning(), 'Synthetic audio worker did not finish')
        self.click(w.audio_check_button)
        dialog = getattr(w, 'audio_check_dialog', None)
        self.assertIsNotNone(dialog, 'Audio check did not open')
        self.assertTrue(dialog.isVisible())
        self.assertTrue(w.busy)
        self.visible_control(dialog.done_button)
        self.assertRegex(dialog.done_button.text().lower(), r'back|return')
        self.click(dialog.done_button)
        self.wait_for(lambda: not getattr(w, 'audio_check_dialog', None), 'Return did not close audio check')
        self.assertFalse(w.busy)
        for widget in (w.screen_button, w.camera_button, w.camera, w.microphone):
            self.visible_control(widget)
            self.assertTrue(widget.isEnabled())
        # A source change after returning must reach the engine, rather than stay locked.
        self.choose(w.camera, '/dev/video-second')
        self.assertEqual(w.engine.configure.call_args.kwargs['camera'], '/dev/video-second')
        w.engine.begin_audio_check.assert_not_called()

    def open_synthetic_library(self):
        for name in ('Alpha explanation.mp4', 'Beta draft.mkv'):
            (self.root / name).write_bytes(b'synthetic video fixture, never captured')
        self.click(self.window.library_button)
        self.wait_for(lambda: self.window.in_library(), 'Recordings did not open')
        return self.window.recordings

    def test_library_search_select_is_silent_until_play_and_back_releases(self):
        from PySide6.QtMultimedia import QMediaPlayer
        # This is the only playback boundary replaced. Search, selection, source,
        # navigation, and player release all run through the production UI.
        with patch.object(QMediaPlayer, 'play') as play:
            page = self.open_synthetic_library()
            self.assertTrue(page.player.source().isEmpty())
            self.click(page.search)
            QTest.keyClicks(page.search, 'Alpha')
            QTest.qWait(20)
            rows = [page.files.item(i) for i in range(page.files.count())
                    if not page.files.item(i).isHidden()]
            self.assertEqual(len(rows), 1)
            self.assertIn('Alpha', rows[0].text())
            QTest.mouseClick(page.files.viewport(), Qt.LeftButton,
                             pos=page.files.visualItemRect(rows[0]).center())
            self.assertEqual(page.selected_path(), self.root / 'Alpha explanation.mp4')
            self.assertTrue(page.player.source().isEmpty())
            play.assert_not_called()
            self.click(page.toggle)
            play.assert_called_once()
            self.assertEqual(page.player.source().toLocalFile(), str(self.root / 'Alpha explanation.mp4'))
            self.click(page.back)
            self.assertFalse(self.window.in_library())
            self.assertTrue(page.player.source().isEmpty())
            self.visible_control(self.window.record_button)

    def test_light_dark_switch_in_recorder_and_library(self):
        w = self.window
        for theme in ('dark', 'light'):
            self.choose(w.theme_choice, theme)
            self.assertEqual(qt.property('untangleTheme'), theme)
            self.assertEqual(w.prefs.value('theme'), theme)
        page = self.open_synthetic_library()
        for theme in ('dark', 'light'):
            self.choose(page.theme_choice, theme)
            self.assertEqual(qt.property('untangleTheme'), theme)
            self.assertEqual(w.prefs.value('theme'), theme)
            self.assertEqual(w.theme_choice.currentData(), theme)
        self.click(page.back)
        self.assertEqual(w.theme_choice.currentData(), 'light')

    def assert_primary_geometry(self, widgets):
        from itertools import combinations
        from PySide6.QtWidgets import QCheckBox, QComboBox, QPushButton, QStyle, QStyleOptionComboBox, QStyleOptionButton
        for widget in widgets:
            self.visible_control(widget)
            if isinstance(widget, QComboBox):
                option = QStyleOptionComboBox()
                widget.initStyleOption(option)
                content = widget.style().subControlRect(QStyle.CC_ComboBox, option,
                                                        QStyle.SC_ComboBoxEditField, widget)
                text = widget.currentText()
            elif isinstance(widget, (QPushButton, QCheckBox)):
                option = QStyleOptionButton()
                widget.initStyleOption(option)
                element = (QStyle.SE_CheckBoxContents if isinstance(widget, QCheckBox)
                           else QStyle.SE_PushButtonContents)
                content = widget.style().subElementRect(element, option, widget)
                text = widget.text().replace('&', '')
            else:
                continue
            self.assertGreaterEqual(content.width(), widget.fontMetrics().horizontalAdvance(text),
                                    f'Clipped text: {text!r}')
            self.assertGreaterEqual(content.height(), widget.fontMetrics().height(),
                                    f'Clipped text height: {text!r}')
        for first, second in combinations(widgets, 2):
            self.assertFalse(self.bounds(first).intersects(self.bounds(second)),
                             f'Overlapping controls: {getattr(first, "text", lambda: type(first).__name__)()} / '
                             f'{getattr(second, "text", lambda: type(second).__name__)()}')

    def test_primary_controls_fit_both_window_sizes_in_both_modes_and_themes(self):
        w = self.window
        for width, height in ((960, 760), (1120, 840)):
            w.resize(width, height)
            QTest.qWait(20)
            self.assertEqual((w.width(), w.height()), (width, height))
            for theme in ('light', 'dark'):
                self.choose(w.theme_choice, theme)
                for mode in ('camera', 'screen'):
                    with self.subTest(size=(width, height), theme=theme, mode=mode):
                        self.click(getattr(w, mode + '_button'))
                        QTest.qWait(220)
                        self.assert_primary_geometry([
                            w.screen_button, w.camera_button, w.canvas_note,
                            *([w.canvas, w.framing] if mode == 'camera' else []),
                            w.camera, w.camera_zoom, w.camera_zoom_value, w.camera_zoom_reset, w.microphone,
                            w.theme_choice, w.library_button, w.sharing_button,
                            w.record_button, w.live_microphone, w.audio_check_button,
                            w.microphone_meter,
                        ])

    def test_expanded_camera_keeps_meter_and_recording_controls_visible(self):
        w = self.window
        for size in ((960, 760), (1120, 840)):
            with self.subTest(size=size):
                w.resize(*size)
                QTest.qWait(20)
                self.click(w.focus_button)
                self.assertTrue(w.focus_button.isChecked())
                for widget in (w.microphone_meter, w.record_button, w.focus_button,
                               w.microphone_meter.name, w.microphone_meter.message):
                    self.visible_control(widget)
                self.click(w.focus_button)
                for widget in (w.camera, w.microphone, w.screen_button, w.camera_button):
                    self.visible_control(widget)

    def test_library_primary_controls_fit_both_sizes_and_themes(self):
        page = self.open_synthetic_library()
        for width, height in ((960, 760), (1120, 840)):
            self.window.resize(width, height)
            QTest.qWait(20)
            self.assertEqual((self.window.width(), self.window.height()), (width, height))
            for theme in ('light', 'dark'):
                with self.subTest(size=(width, height), theme=theme):
                    self.choose(page.theme_choice, theme)
                    self.assert_primary_geometry([
                        page.back, page.theme_choice, page.search, page.files,
                        page.toggle, page.seek, page.mute, page.volume,
                        page.upload, page.copy, page.rename, page.delete,
                    ])

    def test_tab_navigation_reaches_primary_setup_and_actions(self):
        w = self.window
        self.click(w.camera_button)
        QTest.qWait(220)
        self.click(w.camera_zoom)
        QTest.keyClick(w.camera_zoom, Qt.Key_End)
        QTest.qWait(220)
        required = {w.screen_button, w.camera_button, w.canvas, w.framing,
                    w.camera_zoom, w.camera_zoom_reset, w.camera, w.microphone,
                    w.theme_choice, w.library_button, w.record_button}
        visited = set()
        for _ in range(80):
            focused = qt.focusWidget()
            if focused in required:
                self.visible_control(focused)
                visited.add(focused)
            if visited == required:
                break
            QTest.keyClick(w, Qt.Key_Tab)
        self.assertEqual(visited, required, 'Tab navigation must reach every primary setup/action control')
        previous = qt.focusWidget()
        QTest.keyClick(w, Qt.Key_Tab)
        self.assertIsNot(qt.focusWidget(), previous, 'Tab must move focus')
        QTest.keyClick(w, Qt.Key_Tab, Qt.ShiftModifier)
        self.assertIs(qt.focusWidget(), previous, 'Shift+Tab must restore the previous focus')

    def test_specific_window_selection_and_return_to_entire_screen(self):
        w = self.window
        self.click(w.screen_button)
        QTest.qWait(220)
        self.choose(w.capture_kind, 'window')
        self.visible_control(w.capture_window)
        self.assertFalse(w.screen.isVisible())
        # The catalogue may automatically select its first available window.
        # Explicitly choose the synthetic entry through the actual combo either way.
        self.choose(w.capture_window, 4242)
        self.assertEqual(w.engine.configure.call_args.kwargs['window_id'], 4242)
        self.assertFalse(w.engine.configure.call_args.kwargs['floating_camera'])
        self.assertTrue(w.record_button.isEnabled())
        self.choose(w.capture_kind, 'screen')
        self.visible_control(w.screen)
        self.assertFalse(w.capture_window.isVisible())
        self.assertIsNone(w.engine.configure.call_args.kwargs['window_id'])
        self.assertTrue(w.record_button.isEnabled())

    def test_inline_audio_change_microphone_keeps_selected_sources_visible(self):
        w = self.window
        w.resize(960, 760)
        for theme in ('light', 'dark'):
            with self.subTest(theme=theme):
                self.choose(w.theme_choice, theme)
                selected = (w.camera.currentData(), w.microphone.currentData())
                self.wait_for(lambda: not w.audio_worker or not w.audio_worker.isRunning(),
                              'Synthetic audio worker did not finish')
                self.click(w.audio_check_button)
                dialog = w.audio_check_dialog
                for widget in (w.camera, w.microphone):
                    self.visible_control(widget)
                    self.assertFalse(widget.isEnabled())
                self.assertEqual((w.camera.currentData(), w.microphone.currentData()), selected)
                self.assertFalse(w.microphone_meter.isVisible(), 'Inline check should show only its own meter')
                self.assert_primary_geometry([dialog.done_button, dialog.record, dialog.play,
                                              dialog.stop, dialog.change_input_button])
                self.click(dialog.change_input_button)
                self.wait_for(lambda: not getattr(w, 'audio_check_dialog', None),
                              'Change microphone did not return to setup')
                self.assertTrue(w.microphone.isEnabled())
                self.assertTrue(w.camera.isEnabled())
                self.assertIs(qt.focusWidget(), w.microphone)
                self.assertTrue(w.microphone_meter.isVisible())

    def test_main_action_bounds_stay_fixed_through_recording_states(self):
        w = self.window
        self.choose(w.microphone, None)
        # Model the hardware boundary faithfully when microphone capture is off.
        w.audio_devices.prepare.return_value = None
        w.engine.stats.return_value = {'recording': True, 'encoder': 'ffmpeg_vaapi'}
        original = self.bounds(w.record_button)
        self.assertEqual(original.width(), 210)
        self.click(w.record_button)
        self.assertTrue(w.counting)
        self.assertEqual(self.bounds(w.record_button), original, 'Countdown moved the main action')
        QTest.keyClick(w, Qt.Key_Escape)
        self.wait_for(lambda: not w.counting, 'Escape did not cancel')
        self.assertEqual(self.bounds(w.record_button), original, 'Cancel moved the main action')
        self.click(w.record_button)
        self.wait_for(lambda: w.recording, 'Mocked recording did not start', timeout=5000)
        w.engine.start.assert_called_once()
        self.assert_composition_locked()
        self.assertTrue(w.pause_button.isVisible())
        self.assertEqual(self.bounds(w.record_button), original, 'Showing Pause moved the main action')
        self.click(w.pause_button)
        self.assertTrue(w.paused)
        self.assertEqual(self.bounds(w.record_button), original, 'Pause moved the main action')
        # Hold the engine-finish boundary so the real saving UI can be checked.
        with patch.object(glint.FinishWorker, 'start'):
            self.click(w.record_button)
        self.assertTrue(w.busy)
        self.assert_composition_locked()
        self.assertEqual(self.bounds(w.record_button), original, 'Saving moved the main action')

    def test_change_microphone_focus_waits_for_delayed_audio_cleanup(self):
        from threading import Event
        from untangle.audio_check import AudioSample
        from test_audio_check import feed
        w = self.window
        sample = AudioSample(MagicMock(), 123)
        feed(sample, muted=True)
        w.engine.begin_audio_check.return_value = sample
        self.wait_for(lambda: not w.audio_worker or not w.audio_worker.isRunning(),
                      'Synthetic audio worker did not finish')
        self.click(w.audio_check_button)
        dialog = w.audio_check_dialog
        self.click(dialog.record)
        self.wait_for(lambda: dialog.capturing and dialog.worker is None,
                      'Synthetic audio check did not start')
        entered, released = Event(), Event()
        self.addCleanup(released.set)
        def restore():
            entered.set()
            if not released.wait(3):
                raise RuntimeError('Test cleanup gate timed out')
            return True
        w.audio_devices.restore.side_effect = restore
        self.click(dialog.change_input_button)
        self.wait_for(entered.is_set, 'Cleanup never reached the hardware restore boundary')
        self.assertIs(w.audio_check_dialog, dialog)
        self.assertTrue(w.busy)
        self.assertFalse(w.microphone.isEnabled())
        self.assertTrue(dialog.isVisible())
        released.set()
        self.wait_for(lambda: not getattr(w, 'audio_check_dialog', None),
                      'Delayed cleanup did not close the audio check')
        self.assertFalse(w.busy)
        self.assertTrue(w.microphone.isEnabled())
        self.assertIs(qt.focusWidget(), w.microphone)

    def test_audio_meter_stops_after_silence_and_failed_capture(self):
        from untangle.audio_check import AudioSample
        from test_audio_check import feed
        w = self.window
        for outcome in ('silence', 'no samples'):
            with self.subTest(outcome=outcome):
                sample = AudioSample(MagicMock(), 123)
                if outcome == 'silence':
                    feed(sample, muted=True)
                w.engine.begin_audio_check.return_value = sample
                w.audio_devices.restore.return_value = True
                self.wait_for(lambda: not w.audio_worker or not w.audio_worker.isRunning(),
                              'Synthetic audio worker did not finish')
                self.click(w.audio_check_button)
                dialog = w.audio_check_dialog
                self.click(dialog.record)
                self.wait_for(lambda: dialog.capturing and dialog.worker is None,
                              'Synthetic audio check did not start')
                self.assertEqual(dialog.meter.level.value(), 42)
                self.click(dialog.stop)
                self.wait_for(lambda: dialog.worker is None and not dialog.capturing,
                              'Synthetic audio check did not stop')
                self.assertEqual(dialog.meter.level.value(), 0)
                self.assertEqual(dialog.meter._state, 'idle')
                self.assertIn('stopped', dialog.meter.message.text().lower())
                self.assertNotIn('signal received', dialog.meter.message.text().lower())
                self.assertIn('silence' if outcome == 'silence' else 'no microphone signal',
                              dialog.status.text().lower())
                self.click(dialog.done_button)
