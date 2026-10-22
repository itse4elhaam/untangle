# Untangle contributor instructions

Untangle is a standalone Python Linux recording app, formerly RecIt. Production code lives in `src/untangle/`. `app.py` owns the Qt UI; `engine.py` wraps OBS; audio helpers own device preparation and restoration; `recordings.py` owns the library and playback. Tests live in `tests/`, with synthetic device data in `tests/fixtures/`. Maintenance scripts live in `scripts/`, executable launchers in `bin/`, and logo assets stay in root `assets/`. Use relative imports within the package. Run the app through `python -m untangle` with `PYTHONPATH=src`; opening it requires explicit authorization.

## Conventions

- Follow the existing Python style. Keep Qt UI work on the main thread and release OBS, audio, and playback resources on every exit path.
- Use `pathlib.Path` for filesystem paths. Resolve bundled assets relative to `__file__`, never a dotfiles checkout or the working directory.
- Shell scripts use `#!/bin/bash`, `set -euo pipefail`, quoted variables, and `[[ ]]` tests. Keep the installer safe to rerun.
- Visible branding is Untangle; the app icon is `assets/untangle-mark.svg`.
- Preserve compatibility identifiers unless a separate migration is explicitly authorized: `QSettings('TrueDevs', 'Glint')`, glint data/state paths, `~/Videos/RecIt`, lock/socket names, and the `recit` compatibility command. Internal OBS/audio names and `recit.audio` logs can retain their old names.

## Verification

Run safe checks from this repository root:

```bash
./scripts/test.sh
bash -n scripts/*.sh bin/*
```

The runner uses `.venv/bin/python` when available, otherwise `python3`, sets an absolute `PYTHONPATH` for `src/`, and runs `unittest discover -s tests`. It clears display and hardware opt-in environment switches and accepts no capture flags. It works from any working directory.

Use mocks and synthetic samples. Never run device capture, live desktop tests, microphone checks, camera checks, Bluetooth profile changes, or audible playback without explicit authorization. Hardware tests are opt-in; leave their flags and environment switches unset during ordinary checks. Opening the app can open capture devices, so do not launch it as an incidental verification step.

## Speech and accessibility

Never enable screen readers, Orca, speech-dispatcher, accessibility speech, or desktop accessibility settings. Never set `ScreenReaderEnabled`, `screen-reader-enabled`, or `toolkit-accessibility` to true, even temporarily for testing. Never unmask speech services or remove speech safeguards. Only a new, explicit user request to enable speech can override this rule.

## Installation and delivery

All new changes go through a pull request. Do not automatically install, deploy, update the installed runtime or launchers, authenticate to Loom, or upload recordings. `./scripts/install.sh` is an explicit user action, not a verification command. Keep repository work separate from the installed app and other projects.
