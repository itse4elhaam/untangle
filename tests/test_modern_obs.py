"""Native compatibility and portal lifecycle without loading OBS or devices."""
import ctypes
import unittest
from unittest.mock import Mock, patch

from untangle.engine import Engine, EngineError, _load_obs, _VideoInfo, _DisplayInfo, _Window, _AudioInfo


class ModernObsTests(unittest.TestCase):
    def engine(self):
        e = Engine.__new__(Engine)
        e._obs = Mock()
        e._closed = False
        e._started_obs = True
        e._output = e._scene = e._camera_display = e._camera_source = None
        e._sources = []
        e._microphone_capture = None
        e._screen_item = e._screen_source = e._screen_dimensions = None
        e._portal_source = None
        e.portal_capture = True
        e._glib = Mock()
        e._glib.g_main_context_iteration.return_value = 0
        e._configured = False
        e.width, e.height, e.fps = 1920, 1080, 30
        e.errors, e.warnings = [], []
        e._obs.obs_source_get_width.return_value = 0
        e._obs.obs_source_get_height.return_value = 0
        e._source = Mock(return_value=301)
        e._obs.obs_scene_add.return_value = 201
        e.source_types = {'pipewire-screen-capture-source'}
        return e

    def test_pending_permission_retained_across_audio_reconfiguration(self):
        e = self.engine()
        e.configure(camera=None, microphone=None)
        self.assertFalse(e.screen_ready())
        e._source.assert_called_once_with('pipewire-screen-capture-source',
            'Untangle screen or window', {'ShowCursor': True})
        # Preparing the microphone rebuilds the scene; permission must survive.
        e.configure(camera=None, microphone=None)
        e._source.assert_called_once()
        e._obs.obs_source_release.assert_not_called()
        with self.assertRaisesRegex(EngineError, 'system picker'):
            e.start('/tmp/synthetic.mkv')
        e._obs.obs_source_get_width.return_value = 2560
        e._obs.obs_source_get_height.return_value = 1440
        self.assertTrue(e.screen_ready())
        e._obs.obs_sceneitem_set_scale.assert_called()
        e.reset_portal()
        e._obs.obs_source_release.assert_called_once_with(301)
        self.assertFalse(e.screen_ready())
        e.configure(camera=None, microphone=None)
        self.assertEqual(e._source.call_count, 2)

    def test_camera_mode_and_clear_video_release_screen_permission(self):
        e = self.engine()
        e.configure(camera=None, microphone=None)
        e.clear_video()
        e._obs.obs_source_release.assert_called_once_with(301)
        self.assertFalse(e.screen_ready())

    def test_unknown_obs_rejected_before_binding_other_symbols(self):
        lib = Mock()
        lib.obs_get_version.return_value = 34 << 24
        lib.obs_get_version_string.return_value = b'34.0.0'
        with patch('untangle.engine.C.CDLL', return_value=lib), \
             patch('untangle.engine.ctypes.util.find_library', return_value='libobs.so.30'):
            with self.assertRaisesRegex(EngineError, '34.0.0'):
                _load_obs()
        self.assertFalse(lib.obs_startup.called)

    def test_supported_versions_and_binary_struct_contract(self):
        self.assertEqual([ctypes.sizeof(t) for t in (_VideoInfo, _AudioInfo, _Window, _DisplayInfo)],
                         [56, 8, 16, 40])
        for major in (27, 30, 31, 32, 33):
            lib = Mock()
            lib.obs_get_version.return_value = major << 24
            with patch('untangle.engine.C.CDLL', return_value=lib), \
                 patch('untangle.engine.ctypes.util.find_library', return_value='libobs.so.30'):
                self.assertIs(_load_obs(), lib)
            lib.obs_startup.assert_not_called()

    def test_modern_egl_selection_preserves_legacy_glx(self):
        for major, platform in ((27, 0), (30, 1), (33, 1)):
            lib = Mock()
            lib.obs_get_version.return_value = major << 24
            lib.obs_reset_video.return_value = 0
            xlib = Mock()
            xlib.XOpenDisplay.return_value = 10
            with patch('untangle.engine._load_obs', return_value=lib), \
                 patch('untangle.engine.C.CDLL', return_value=xlib), \
                 patch('untangle.engine.ctypes.util.find_library', return_value=None), \
                 patch.object(Engine, '_load_modules'), \
                 patch.object(Engine, '_enum', return_value=set()), \
                 patch.dict('os.environ', {'DISPLAY': ':synthetic', 'XDG_SESSION_TYPE': 'x11'}, clear=True):
                engine = Engine(0, 320, 240)
                try:
                    lib.obs_set_nix_platform.assert_called_once_with(platform)
                    self.assertEqual(engine.platform, 'glx' if major == 27 else 'egl')
                finally:
                    engine.close()
            xlib.XCloseDisplay.assert_called_once_with(10)
