# Verification

Run safe checks from the repository root:

```bash
./scripts/test.sh
bash -n scripts/*.sh bin/*
```

[scripts/test.sh](../scripts/test.sh) requires bubblewrap and fails closed if
namespace isolation is unavailable. It uses private devices, networking and
runtime directories and a read-only host filesystem; it clears display and
hardware opt-ins. Never replace it with direct unittest discovery. Incomplete UI
mocks can otherwise reach real audio and change Bluetooth profiles. See
[contributor safety rules](../AGENTS.md#verification-and-delivery).

## What synthetic checks establish

- [Overlay input](../tests/test_overlay_input.py) uses private Xvfb when available,
  real pointer events at 1×/1.5×, and OBS XComposite on a synthetic window with
  image-source camera pixels. It needs OBS 27 plugins and software GLX; it never
  loads camera/audio capture plugins. It cannot establish host window-manager behavior.
- [UI click-throughs](../tests/test_ui_clickthrough.py) use production widgets and
  Qt events with capture/device boundaries replaced. See [UI standards](ui-standards.md)
  for screenshot acceptance. Fixtures prove layout and interaction, not hardware output.
- [Camera updates](../tests/test_camera_updates.py),
  [canvas lifecycle](../tests/test_canvas_lifecycle.py), and
  [framing preferences](../tests/test_camera_framing_preferences.py) own crop,
  Fit/Fill, zoom and retry regressions. A user screenshot exposed the original
  Reels default's tiny landscape image; portrait/square camera defaults now use Fill.
  Mocked checks do not verify native encoded pixels.
- [Playback](../tests/test_recordings.py) decodes silent synthetic H.264 MP4/MKV
  through offscreen QVideoSink without audio output. [Navigation](../tests/test_navigation.py)
  covers preview teardown/restoration and playback release. Neither establishes
  desktop GLX stacking or audible output.

## Reasons for the Qt safeguards

Keep PySide6 Essentials/Addons together at the [pinned version](../requirements.txt).
On the tested Python 3.10 runtime, 6.12.0 lost references to Python's `None` during
ordinary widget updates and aborted with `none_dealloc: deallocating None`.
Commit `c42f566` pins 6.11.1;
[test_qt_runtime.py](../tests/test_qt_runtime.py) stresses 10,000 meter updates and shutdown.

A separate Qt 6.11.1 failure collected widget cycles during
`QApplication.allWidgets()`. The October 23 baseline reproduction failed five of
five runs. Commit `ee76e0b` uses meter `PaletteChange` handling instead; the same
subprocess regression covers it. [render-ui.py](../scripts/render-ui.py) replaces
non-widget media backends because Qt 6.11 offscreen `QMediaPlayer`/`QAudioOutput`
construction intermittently segfaulted before playback, even in isolated processes.
This does not establish a live-app crash or native player stability.

The October 30 overlay diagnostic found python-xlib's `shape_rectangles` rejects
`onerror`, preventing input-region installation. It also found the recorder's
`screen` selector shadowed `QWidget.screen()` in diagnostics. Commit `da890bd`
fixes both. [floating.py](../src/untangle/floating.py) uses a non-focusing X11
override-redirect panel because `Popup` grabs input and managed tools can acquire
frames. This follows [Cap's panel approach](https://github.com/CapSoftware/Cap/blob/84334e79035e408ab82ed3b6ca63db1e76e14c0e/apps/desktop-gpui/src/app_windows.rs#L4194).
The logged TypeError alone does not explain the user's target-app selection failure.

## Explicit hardware boundaries

Only after explicit recording authorization, close Untangle and all other capture
streams before the audio-only comparison:

```bash
RECIT_TEST_XVFB=/path/to/Xvfb PYTHONPATH=src .venv/bin/python tests/test_hardware_audio.py --microphone-hardware
```

Discovery skips it; `RECIT_TEST_MIC_HARDWARE=1` also opts in.
`--source EXACT_PULSE_NAME` overrides production Default preparation. It requires
a Bluetooth microphone and compares five-second native Pulse samples with the
verified OBS stream before/after filters. Readiness gates AAC/MKV encoding of a
black scene. No camera, desktop, playback or upload occurs. Owner-only artifacts
remain under the printed `/tmp/recit-hardware-audio-*`; remove them afterward.
Cleanup releases capture and restores only profile changes owned by the test.
Missing/very-low native signal is inconclusive; nonzero samples cannot prove speech quality.

Live desktop checks require separate authorization and an isolated test desktop,
never the user's active desktop. Close Untangle there first. They move the pointer,
open windows/capture devices and delete temporary recordings:

```bash
PYTHONPATH=src QT_QPA_PLATFORM=xcb .venv/bin/python tests/test_engine.py --capture --camera /dev/video0
PYTHONPATH=src QT_QPA_PLATFORM=xcb .venv/bin/python tests/test_live_ui.py --capture
```

## Dated hardware evidence

The authorized 2026-10-22 OnePlus Buds 4 session used mSBC HFP, 16000 Hz mono,
unmuted at 88% gain. Repeated native Pulse samples including a speech retry,
direct PipeWire capture, and verified OBS packets before/after RNNoise/limiting
were exact zeros. Readiness blocked live AAC. The reported working Meet/Loom path
and Bluetooth root cause remain unexplained; this justified no production audio fix.
A separate synthetic 16 kHz mono → filters → 48 kHz stereo AAC check passed.

Earlier host checks reported 4K/30 fps with zero lagged/dropped frames in screen
and camera modes, including pointer zoom. Their date was not recorded. Live MX
Brio capture remains unverified. These observations were not rerun in the
2026-11-09 documentation audit and do not establish sustained performance.
