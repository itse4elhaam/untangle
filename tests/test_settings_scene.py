"""Retained OBS scene and Raw encoder contracts, with mocked capture only."""
import unittest
import test_app as fixture


class SettingsSceneTests(unittest.TestCase):
    setUp = fixture.AppChecks.setUp
    tearDown = fixture.AppChecks.tearDown

    def test_library_quality_and_mirror_mark_scene_dirty_until_return(self):
        w = self.window
        w.configuration_valid = True
        w._configure_pending = False
        w.open_recordings()
        w.engine.reset_mock()
        w.quality.setCurrentIndex(1)
        w.mirror.setChecked(not w.mirror.isChecked())
        self.assertTrue(w._configure_pending)
        self.assertFalse(w.configuration_valid)
        w.engine.configure.assert_not_called()
        w.back_to_recorder()
        w.engine.configure.assert_not_called()
        fixture.qt.processEvents()
        self.assertEqual(w.engine.set_canvas.call_args.args, (1920, 1080))
        self.assertEqual(w.engine.configure.call_args.kwargs['mirror'], w.mirror.isChecked())

    def test_raw_uses_encoder_safe_source_dimensions(self):
        w = self.window
        w.set_mode('camera', configure=False)
        w.engine._camera_dimensions = (854, 481)
        w.canvas.blockSignals(True)
        w.canvas.setCurrentIndex(w.canvas.findData('raw'))
        w.canvas.blockSignals(False)
        self.assertEqual(w.output_dimensions(), (852, 480))
        self.assertEqual(w.effective_framing(), 'fit')
