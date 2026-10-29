"""Camera picture controls, parsed from real v4l2-ctl dumps; every subprocess is mocked."""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QComboBox
from untangle import camera_image
from untangle.camera_image import Control, parse_controls, restore_saved, write_controls
import test_ui_clickthrough as ui

FIXTURES = Path(__file__).parent / 'fixtures'
HP = (FIXTURES / 'v4l2-hp-5mp.txt').read_text()
BRIO = (FIXTURES / 'v4l2-mx-brio.txt').read_text()


def completed(stdout='', returncode=0, stderr=''):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class FakeCamera:
    """Answers list and set calls from one v4l2-ctl dump, tracking writes."""
    def __init__(self, text):
        self.controls = {c.name: c for c in parse_controls(text)}
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if '--set-ctrl' in args:
            pairs = [pair.split('=') for pair in args[args.index('--set-ctrl') + 1].split(',')]
            values = {name: control.value for name, control in self.controls.items()}
            for name, _ in pairs:
                # Like some uvcvideo kernels: an inactive control fails the whole call.
                if not camera_image.manual_allowed(name, values):
                    return completed(returncode=1, stderr='Permission denied')
            for name, value in pairs:
                self.controls[name].value = int(value)
            return completed()
        lines = []
        for c in self.controls.values():
            if c.kind == 'menu':
                lines.append(f'{c.name} 0x1 (menu) : min={c.minimum} max={c.maximum} default={c.default} value={c.value}')
                lines += [f'\t\t\t\t{index}: {text}' for index, text in c.menu.items()]
            else:
                lines.append(f'{c.name} 0x1 ({c.kind}) : min={c.minimum} max={c.maximum} step={c.step} '
                             f'default={c.default} value={c.value}')
        return completed('\n'.join(lines))

    def sets(self):
        return [args[args.index('--set-ctrl') + 1] for args in self.calls if '--set-ctrl' in args]


class ParserTests(unittest.TestCase):
    def test_hp_camera_keeps_supported_writable_controls_in_display_order(self):
        names = [c.name for c in parse_controls(HP)]
        self.assertEqual(names[:6], ['brightness', 'contrast', 'saturation', 'hue', 'gamma', 'sharpness'])
        for skipped in ('privacy', 'region_of_interest_rectangle', 'region_of_interest_auto_ctrls'):
            self.assertNotIn(skipped, names)
        brightness = parse_controls(HP)[0]
        self.assertEqual((brightness.minimum, brightness.maximum, brightness.default), (-64, 64, 0))

    def test_brio_exposes_device_framing_and_camera_light(self):
        controls = {c.name: c for c in parse_controls(BRIO)}
        names = list(controls)
        self.assertEqual(names[:3], ['zoom_absolute', 'pan_absolute', 'tilt_absolute'])
        self.assertEqual(names[-2:], ['led1_mode', 'led1_frequency'])
        self.assertEqual((controls['zoom_absolute'].value, controls['zoom_absolute'].display(150)), (150, '150%'))
        self.assertEqual(controls['pan_absolute'].display(-36000), '-10°')
        self.assertEqual(controls['led1_mode'].menu[3], 'When camera is in use')
        self.assertIn('inactive', controls['focus_absolute'].flags)

    def test_hp_has_no_device_framing(self):
        names = [c.name for c in parse_controls(HP)]
        for missing in ('zoom_absolute', 'pan_absolute', 'led1_mode'):
            self.assertNotIn(missing, names)

    def test_sparse_menus_and_labels(self):
        controls = {c.name: c for c in parse_controls(HP)}
        self.assertEqual(controls['auto_exposure'].menu, {1: 'Manual', 3: 'Automatic'})
        self.assertEqual(controls['power_line_frequency'].menu, {0: 'Disabled', 1: '50 Hz', 2: '60 Hz'})
        self.assertEqual(controls['auto_exposure'].clamp(2), 3, 'Unlisted menu values fall back to default')

    def test_clamp_snaps_to_step_and_range(self):
        control = Control('pan', 'int', 0, 0, -72000, 72000, 3600)
        self.assertEqual(control.clamp(5000), 3600)
        self.assertEqual(control.clamp(10 ** 9), 72000)

    def test_write_sets_automatic_modes_before_manual_values(self):
        with patch.object(camera_image.subprocess, 'run', return_value=completed()) as run:
            write_controls('/dev/video9', {'exposure_time_absolute': 200, 'auto_exposure': 1, 'contrast': 40})
        settings = [c.args[0][-1] for c in run.call_args_list]
        self.assertEqual(settings, ['auto_exposure=1', 'contrast=40', 'exposure_time_absolute=200'])

    def test_manual_values_are_dropped_while_automatic_stays_on(self):
        with patch.object(camera_image.subprocess, 'run', return_value=completed()) as run:
            write_controls('/dev/video9', {'focus_absolute': 50, 'brightness': 10},
                           {'focus_automatic_continuous': 1})
        self.assertEqual([c.args[0][-1] for c in run.call_args_list], ['brightness=10'])

    def test_a_rejected_manual_batch_keeps_picture_values(self):
        fake = FakeCamera(BRIO)
        fake.controls['focus_automatic_continuous'].value = 1
        with patch.object(camera_image.subprocess, 'run', side_effect=fake):
            # Stale current state claims auto is off; the camera disagrees.
            with self.assertRaises(camera_image.CameraControlError):
                write_controls('/dev/video5', {'focus_absolute': 50, 'brightness': 10},
                               {'focus_automatic_continuous': 0})
        self.assertEqual(fake.controls['brightness'].value, 10)

    def test_failures_raise_camera_control_error(self):
        with patch.object(camera_image.subprocess, 'run', return_value=completed(returncode=1, stderr='busy')):
            with self.assertRaisesRegex(camera_image.CameraControlError, 'busy'):
                write_controls('/dev/video9', {'contrast': 1})
        with patch.object(camera_image.subprocess, 'run', side_effect=subprocess.TimeoutExpired('v4l2-ctl', 2)):
            with self.assertRaises(camera_image.CameraControlError):
                camera_image.read_controls('/dev/video9')

    def test_restore_clamps_saved_values_to_this_camera(self):
        fake = FakeCamera(HP)
        with patch.object(camera_image.subprocess, 'run', side_effect=fake):
            applied = restore_saved('/dev/video0', {'brightness': 200, 'zoom_absolute': 300, 'contrast': True,
                                                    'white_balance_temperature': 3000})
        self.assertEqual(applied, {'brightness': 64})
        self.assertEqual(fake.sets(), ['brightness=64'], 'Stale manual value is skipped while auto is on')

    def test_restore_without_saved_values_runs_nothing(self):
        with patch.object(camera_image.subprocess, 'run') as run:
            self.assertEqual(restore_saved('/dev/video0', {}), {})
        run.assert_not_called()


class CameraPageTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeCamera(BRIO)
        runner = patch.object(camera_image.subprocess, 'run', side_effect=self.fake)
        runner.start()
        self.addCleanup(runner.stop)
        self.case = ui.ClearlineClickthrough()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.window = self.case.window
        self.window.timer.stop()

    def open_page(self):
        w = self.window
        w.engine.reset_mock()
        self.case.click(w.camera_settings_button)
        QTest.qWait(30)
        return w.camera_adjustments

    def control(self, name):
        return self.window.camera_adjustments.widgets[name][0]

    def flush(self):
        self.window.camera_adjustments.apply_timer.stop()
        self.window.camera_adjustments.apply_pending()

    def test_on_off_integer_controls_are_checkboxes(self):
        self.open_page()
        self.assertIsInstance(self.control('backlight_compensation'), QCheckBox)

    def test_entry_is_disabled_when_camera_off(self):
        w = self.window
        self.assertTrue(w.camera_settings_button.isEnabled())
        w.camera.setCurrentIndex(0)
        self.assertFalse(w.camera_settings_button.isEnabled())

    def test_page_swaps_main_preview_for_camera_preview_and_back(self):
        w = self.window
        page = self.open_page()
        self.assertIs(w.pages.currentWidget(), page)
        w.engine.detach_preview.assert_called()
        w.engine.attach_camera_preview.assert_called_once()
        self.assertEqual(w.engine.attach_camera_preview.call_args.args[0], int(page.preview.winId()))
        self.assertFalse(w.tray_record.isEnabled())
        self.assertIn(w.camera.currentText(), page.subtitle.text())
        w.engine.reset_mock()
        self.case.click(page.back)
        QTest.qWait(30)
        self.assertIs(w.pages.currentWidget(), w.recorder_page)
        w.engine.detach_camera_preview.assert_called()
        w.engine.attach_preview.assert_called_once()

    def test_hotkey_record_is_ignored_on_page(self):
        w = self.window
        self.open_page()
        w.toggle_record()
        self.assertFalse(w.counting)

    def test_slider_changes_are_debounced_into_one_write_and_remembered(self):
        w = self.window
        self.open_page()
        contrast = self.control('contrast')
        for value in (130, 140, 150):
            contrast.setValue(value)
        self.assertEqual(self.fake.sets(), [])
        QTest.qWait(200)
        self.assertEqual(self.fake.sets(), ['contrast=150'])
        name = w.camera.currentText()
        self.assertEqual(w.camera_image_settings()[name], {'contrast': 150})

    def test_back_flushes_a_pending_change(self):
        self.open_page()
        self.control('brightness').setValue(90)
        self.case.click(self.window.camera_adjustments.back)
        self.assertEqual(self.fake.sets(), ['brightness=90'])

    def test_automatic_modes_disable_their_manual_partners(self):
        self.open_page()
        for auto, manual in (('white_balance_automatic', 'white_balance_temperature'),
                             ('focus_automatic_continuous', 'focus_absolute')):
            box, slider = self.control(auto), self.control(manual)
            self.assertIsInstance(box, QCheckBox)
            self.assertFalse(slider.isEnabled())
            box.setChecked(False)
            self.assertTrue(slider.isEnabled())
        exposure, time = self.control('auto_exposure'), self.control('exposure_time_absolute')
        self.assertIsInstance(exposure, QComboBox)
        self.assertFalse(time.isEnabled())
        exposure.setCurrentIndex(exposure.findData(1))
        self.assertTrue(time.isEnabled())
        self.flush()
        self.assertEqual(self.fake.sets()[0], 'white_balance_automatic=0,focus_automatic_continuous=0,auto_exposure=1')

    def test_device_zoom_and_pan_write_to_the_camera(self):
        self.open_page()
        zoom, pan = self.control('zoom_absolute'), self.control('pan_absolute')
        self.assertEqual(zoom.value(), 150)
        self.assertEqual(self.window.camera_adjustments.widgets['zoom_absolute'][1].text(), '150%')
        zoom.setValue(200)
        pan.setValue(5000)
        self.flush()
        self.assertEqual(self.fake.sets(), ['zoom_absolute=200,pan_absolute=3600'])
        self.assertEqual(self.window.camera_adjustments.widgets['pan_absolute'][1].text(), '1°')
        self.window.engine.configure.assert_not_called()

    def test_blink_speed_needs_blink_mode(self):
        self.open_page()
        light, speed = self.control('led1_mode'), self.control('led1_frequency')
        self.assertFalse(speed.isEnabled())
        light.setCurrentIndex(light.findData(2))
        self.assertTrue(speed.isEnabled())
        speed.setValue(40)
        self.flush()
        self.assertEqual(self.fake.sets(), ['led1_mode=2', 'led1_frequency=40'])

    def test_reset_returns_device_zoom_to_100(self):
        self.open_page()
        self.case.click(self.window.camera_adjustments.reset_button)
        self.assertEqual(self.fake.controls['zoom_absolute'].value, 100)
        self.assertEqual(self.control('zoom_absolute').value(), 100)

    def test_reset_after_manual_focus_still_resets_picture(self):
        self.open_page()
        self.control('focus_automatic_continuous').setChecked(False)
        self.flush()
        self.control('focus_absolute').setValue(90)
        self.control('contrast').setValue(10)
        self.flush()
        self.case.click(self.window.camera_adjustments.reset_button)
        self.assertEqual(self.fake.controls['contrast'].value, 128)
        self.assertEqual(self.fake.controls['focus_automatic_continuous'].value, 1)
        self.assertNotIn('Permission denied', self.window.camera_adjustments.message.text())

    def test_reset_restores_defaults_but_keeps_regional_anti_flicker(self):
        w = self.window
        self.open_page()
        self.control('contrast').setValue(10)
        self.flush()
        self.case.click(w.camera_adjustments.reset_button)
        self.assertEqual(self.fake.controls['contrast'].value, 128)
        self.assertEqual(self.fake.controls['power_line_frequency'].value, 1)
        self.assertEqual(self.control('contrast').value(), 128)
        self.assertNotIn(w.camera.currentText(), w.camera_image_settings())

    def test_saved_values_follow_camera_name_across_device_numbers(self):
        w = self.window
        name = w.camera.currentText()
        w.prefs.setValue('camera_image', '{"%s": {"saturation": 999}}' % name)
        w.camera.setItemData(w.camera.currentIndex(), '/dev/video-moved')
        w.configure()
        self.assertEqual(self.fake.sets(), ['saturation=255'])
        self.assertTrue(any('/dev/video-moved' in args for args in self.fake.calls))
        w.configure()
        self.assertEqual(self.fake.sets(), ['saturation=255'] * 2, 'Every camera reopen reapplies saved values')

    def test_configure_without_saved_values_runs_nothing(self):
        self.fake.calls.clear()
        self.window.configure()
        self.assertEqual(self.fake.calls, [])

    def test_read_failure_shows_message_and_empty_panel(self):
        w = self.window
        with patch.object(camera_image.subprocess, 'run', return_value=completed(returncode=1, stderr='Device busy')):
            page = self.open_page()
        self.assertEqual(page.widgets, {})
        self.assertIn('Device busy', page.message.text())
        self.assertFalse(page.reset_button.isEnabled())

    def test_page_is_left_when_controls_lock(self):
        w = self.window
        self.open_page()
        w.lock_controls(True)
        self.assertIs(w.pages.currentWidget(), w.recorder_page)
        w.lock_controls(False)


if __name__ == '__main__':
    unittest.main()
