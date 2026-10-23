# Minimal recorder and Settings

Actual Qt renders at 960×760, in light and dark themes. The capture source is a
software-painted fixture. Devices, playback, subprocesses, transcription,
accounts, and inference are mocked; no normal app launch or recording occurs.
The Settings title capability is a synthetic ready state.

Reproduce with `.venv/bin/python scripts/render-settings-ui.py`.
The manifest records source and screenshot hashes. Safe checks are
`./scripts/test.sh` and `bash -n scripts/*.sh bin/*`.

- Recorder: compact source summary, single canvas picker, Start at top right.
- Collapsed: sidebar hidden while the preview and main actions stay available.
- Settings: appearance, names, audio toggles, and former More options controls.
- Library: quiet selection, one focus treatment, Settings access.

The Back navigation regression injects a still-running thumbnail process into
the actual Back button → page rejection → recorder restoration path. Before
the fix it counted two synchronous 1,000 ms waits; afterward it counts none.
This is synthetic blocking-time accounting, not a live hardware benchmark.
The recorder retains a valid scene and queues native preview restoration.

Keyboard checks retain focus visibility, Enter/Escape behavior, normal scrolling
to focused Settings controls, stable header-action bounds through recording
states, and clipping checks at the minimum window size. Automatic naming tests
cover successful rename before upload, failure/cancel fallback, stale replies,
and source replacement. See [local title capabilities](../local-titles.md).
