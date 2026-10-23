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


## Clearline UI acceptance

UI changes must pass `./scripts/test.sh` and `bash -n scripts/*.sh bin/*`. The safe suite includes the pinned `tests/test_ui_clickthrough.py` workflows. It uses real Qt mouse and keyboard events through the production widgets, with only device, capture and playback boundaries replaced.

The checks require visible mode and input choices, setup left of preview, working device changes, explicit microphone-off status, countdown cancellation with Escape, audio-check return and unlock, silent library selection until Play, theme persistence through both views, and bounds/text/overlap checks at 960 × 760 and 1120 × 840 in both themes and recording modes. Expanded camera must retain the microphone status and recording action. Existing recovery, audio ownership, playback, thumbnail and installation tests remain part of the same suite.

See [UI standards](ui-standards.md) for the visual review and screenshot procedure. A passing suite does not replace inspection of the actual Qt captures. Mockups are design references, never proof that the shipped app matches them. Synthetic fixtures establish layout and interaction only. OBS rendering, Bluetooth audio quality and real saved recordings still require separately authorized hardware verification.

The screenshot renderer replaces the non-widget media-player and audio-output backends too. Qt 6.11 offscreen `QMediaPlayer` and `QAudioOutput` construction intermittently crashed during screenshot generation, before playback, including in an isolated process. That renderer cannot establish native player stability. The click-through suite still constructs the native player and replaces only audible `play()`; existing silent synthetic decode checks also remain in the safe suite. Those checks passed for this change. No live-app crash was reproduced, and no normal app/device session was used to investigate it.


## Camera zoom and recording canvases

The initial canvas release ran 317 safe tests with two hardware opt-ins skipped. It includes bounded centered camera crops, uniform Fit/Fill placement, every preset at both quality levels, pointer zoom on top of Fill, fresh engine construction, rapid canvas changes with a pending debounce, floating/composited transitions, invalid saved preferences and actual Qt zoom/reset/locking workflows. `bash -n scripts/*.sh bin/*` also passes.

The initial release gallery contained 74 complete Qt windows at 960 × 760 and 1120 × 840 in both themes: 44 new canvas/framing captures, 22 intended recorder changes and eight unchanged library captures compared with `e710a6b`. At that release, the theme fix and explicit audio-output mock produced 74 regenerated PNGs byte-identical to the feature captures. Source feeds are synthetic; these checks do not verify native encoded pixels or hardware capture.

Full-suite verification exposed a pre-existing Qt 6.11.1 crash when Python GC collects widget cycles during `QApplication.allWidgets()`. A pure Qt reproduction failed five of five runs, and the same trigger crashed the committed baseline. Theme changes now let each microphone meter restyle on `PaletteChange`, preserving its reading and status without enumerating all widgets. A subprocess regression fails before this fix and passes afterward. This is separate from the offscreen multimedia-constructor issue and does not resolve OnePlus silence.


## Reels framing correction

A real user screenshot showed the weakness missed by the first visual acceptance: selecting Reels inherited Fit, leaving a small landscape camera image in an unmarked dark viewport. Camera Reels, Square and 4:5 presets now select Fill by default. The native preview has the output aspect ratio and an outlined boundary against a contrasting workspace. Explicit Fit remains available and persists. Legacy automatic camera portrait/square Fit preferences are corrected once.

Five new mocked Qt regressions pin useful preset defaults, crop coverage, canvas geometry and stable native window identity/parent at minimum and wide sizes, explicit Fit restoration and legacy preference handling. The expanded safe suite now runs 347 tests with two hardware opt-ins skipped. Existing layout size assertions now measure the workspace; separate geometry checks measure the aspect-constrained native canvas. No live app or devices were opened. Personal pixels from the supplied screenshot were replayed only into temporary local Qt evidence, never committed to the public repository.


The follow-up also removes dotted focus outlines, adds ±10% camera zoom buttons, hides canvas controls from Screen view and updates crop/placement in place instead of reopening camera capture. New engine tests pin filter ownership/order, original source dimensions, repeated live updates, stable microphone and native displays, normalized dragged overlay position, canvas reset failure/rollback and busy/input guards. QTest workflows verify linear slider updates, step buttons/reset, Screen mode isolation, remembered camera choices, geometry, and no source configure/engine close on live edits. Native OBS source/crop execution remains outside these mocked checks.

The correction gallery contains 74 refreshed actual Qt captures, including −/+ steps, default portrait Fill, explicit Fit and Screen after returning from portrait camera mode. Three additional regressions cover failed-canvas retry recovery, zoom synchronization after retry, immediate quality persistence with camera off, and pending device-configuration guards.

Final verification: 347 safe tests passed with two hardware opt-ins skipped. The independent retry review passed 23 focused mocked tests and confirmed all three new regressions fail against the previous handler; no remaining blockers were found.
