# Verification

Qt is pinned to PySide6 6.11.1. On the tested Python 3.10 runtime, 6.12.0 loses references to Python's `None` during ordinary widget updates and eventually aborts with `none_dealloc: deallocating None`. The offscreen `tests/test_qt_runtime.py` subprocess exercises 10,000 microphone-meter updates and interpreter shutdown without opening capture devices. Keep Essentials and Addons on the same version when changing the pin. This dependency fix does not establish Bluetooth microphone reliability.

An audio-only hardware comparison requires explicit recording authorization and a closed Untangle process, with no other capture stream active:

```bash
RECIT_TEST_XVFB=/path/to/Xvfb PYTHONPATH=src .venv/bin/python tests/test_hardware_audio.py --microphone-hardware
```

Ordinary discovery skips this test. `RECIT_TEST_MIC_HARDWARE=1` also opts in; `--source EXACT_PULSE_NAME` explicitly overrides Default. The test requires a Bluetooth microphone, records five-second native Pulse samples from the exact source, then observes the same live OBS source before and after production filters. Default goes through `AudioDevices.prepare`; actual stream attachment is verified. Production readiness controls whether a synthetic black scene can be encoded to AAC/MKV. No camera or desktop source is loaded. There is no playback or upload. Artifacts and numeric evidence remain in the printed owner-only `/tmp/recit-hardware-audio-*` directory; remove that directory when no longer needed. Cleanup releases capture and safely restores any profile change owned by the test, including on failure. Missing/very low native signal gives an explicit inconclusive skip; ambient nonzero samples cannot establish intelligible speech or audio quality.

The authorized 2026-10-22 diagnostic used OnePlus Buds 4, active mSBC HFP, 16000 Hz mono, unmuted at 88% source gain. Repeated native Pulse samples, including a speech retry, contained exact zeros. A direct PipeWire capture linked to the same source also contained exact zeros. OBS's verified stream delivered unmuted packets containing exact-zero floats both before and after RNNoise and the limiter. The readiness guard therefore blocked live AAC recording. This establishes where silence was observed in this session, but does not explain the reported working Meet/Loom path or establish a Bluetooth root cause. No production audio fix was justified by this comparison. The separate synthetic 16 kHz mono → production filters → 48 kHz stereo AAC check passed.

```bash
./scripts/test.sh
```

Do not run live checks on the user's active desktop during agent work. They open windows, move the pointer, and capture devices. Use an isolated test desktop only when explicitly requested. Close Untangle on that test desktop first. The tests delete temporary recordings afterward:

```bash
PYTHONPATH=src QT_QPA_PLATFORM=xcb .venv/bin/python tests/test_engine.py --capture --camera /dev/video0
PYTHONPATH=src QT_QPA_PLATFORM=xcb .venv/bin/python tests/test_live_ui.py --capture
```

Short hardware smoke tests verify encoding, pause/resume, shape masking, scene changes, output recovery, and app lifecycle. They do not establish sustained performance under every workload.

The MX Brio format selection and full-image layout have automated regression coverage; live Brio recording has not been verified. Earlier checks on this machine recorded 4K at 30 fps with zero lagged frames and zero dropped frames in both screen and camera modes, including pointer-follow zoom. Automated checks cover UI state, recording safety, failed conversion, upload failure handling, camera ownership, shape clipping, and zoom transforms. Live checks also exercise physical mouse dragging and keeping the widget visible while the main window is hidden.

Playback regression checks generate silent H.264 MP4/MKV clips with FFmpeg and assert decoded frames through Qt QVideoSink offscreen, without an audio output device. They cover pause, seek, switching files, missing/corrupt files, and cleanup. Desktop video rendering and audible volume output have not been tested by these checks.

Navigation checks use a mocked OBS engine and synthetic silent video to exercise repeated Recordings/back transitions. The recorder destroys its native OBS preview before hiding it and recreates it after Qt lays out the recorder again; playback stops and clears its source on return. Tests check teardown order and cancel stale queued restoration, but offscreen Qt cannot establish X11/GLX stacking correctness. No live desktop or device capture was used to verify this fix.


## Companion UI verification

Companion adds light/dark themes, a preparation summary, an embedded audio-check side sheet and thumbnail-based local review. Regression checks exercise theme changes through both recorder and library, minimum-window layout, long names, camera expansion, explicit playback, thumbnail process cleanup/cache bounds, and returning from the audio sheet without reparenting the native preview. The output accordion remains usable for Zoom while recording, while configuration fields remain locked.

UI inspection uses offscreen Qt with a synthetic preview and mocked device helpers. It does not establish X11/GLX video stacking, live audio quality or Bluetooth reliability. The OnePlus silence diagnosis remains unresolved. Font files load only into Qt; no desktop font installation or accessibility/speech setting changes are involved.
