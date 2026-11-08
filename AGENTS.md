# Untangle contributor instructions

Untangle is a standalone Python Linux recording app, formerly RecIt. Protect recording reliability, saved media, and the user's desktop session.

## Where code lives

`src/untangle/` contains production code: `app.py` owns Qt, `engine.py` wraps OBS, audio helpers prepare/restore devices, and `recordings.py` owns library/playback. Tests and synthetic fixtures live in `tests/`, helpers in `scripts/`, launchers in `bin/`, and branding assets in `assets/`.

## Protect the user's session

- App launch, live desktop tests, capture, microphone/camera checks, Bluetooth profile changes, and audible playback require explicit authorization. Never launch incidentally for verification. Use synthetic data and mocks.
- Never enable screen readers, Orca, speech-dispatcher, accessibility speech, or desktop accessibility settings. Never set `ScreenReaderEnabled`, `screen-reader-enabled`, or `toolkit-accessibility` to true, even temporarily. Never unmask speech services or remove safeguards. Only a new explicit request to enable speech overrides this.
- Keep fast mode disabled and use the default service tier, including delegates. Never select fast/priority. Prefer Codex Elhaam for requested delegation; report exhaustion before switching providers/accounts.
- Keep private recordings, transcripts, extracted media, credentials, and personal screen content out of Git and public PR evidence.

## Preserve behavior

UI polish must preserve capture/encoding, audio ownership, recovery, and active-take inputs/upload consent. Check recorder, library, Settings, tray, shortcuts, and floating controls where applicable. Preserve X11 behavior when changing Wayland support.

Keep Qt work on the main thread. Release OBS, audio, playback, and workers on every exit path. Restore only audio state Untangle still owns; respect other applications' streams and profile changes. Do not force earbuds into a preferred profile on exit.

Use relative imports, `pathlib.Path`, and bundled assets resolved from `__file__`. Shell scripts use `#!/bin/bash`, `set -euo pipefail`, quoted variables, and `[[ ]]`. Keep installers rerunnable.

Visible branding is Untangle; the icon is `assets/untangle-mark.svg`. Preserve `QSettings('TrueDevs', 'Glint')`, glint data/state paths, `~/Videos/RecIt`, lock/socket names, and `recit` compatibility commands unless a separate migration is authorized.

## Verification and delivery

```bash
./scripts/test.sh
bash -n scripts/*.sh bin/*
```

Never bypass the bubblewrap runner with direct unittest discovery. It fails closed without isolation. Leave hardware opt-ins unset. Focused checks use `UNTANGLE_TEST_PATTERN=test_name.py ./scripts/test.sh`. Distinguish synthetic UI, native input, encoded output, and live hardware evidence; report skips. Follow [UI standards](docs/ui-standards.md) for visual changes.

All changes go through a PR. Merge/install authority is task-specific. Version and push before authorized deployment; install immutable pushed code. Do not automatically update the installed runtime/launchers, authenticate, upload, or activate timers. Prerequisite repair needs consent and a successful version recheck before runtime replacement.

## Documentation

Keep user tasks, safe setup/recovery procedures, and reasons code cannot explain. Link to source owners instead of copying APIs, fields, event inventories, or control flow. Rewrite stale sections in place; never append a competing account.

Do not commit plans, agent scratch files, PR summaries, test-count diaries, or PR-only media. Track work in issues/PRs. Preserve unique rationale and unverified historical evidence until checked. Keep policy in one authority and link to it. Aim for 500 words in README/AGENTS, 600 in context docs, and 800 in runbooks; complete safety procedures can justify exceptions.
