# Standalone repository

Untangle was extracted on 2026-10-22 from `apps/recit` in
[itse4elhaam/dotfiles](https://github.com/itse4elhaam/dotfiles).
The source revision is `eb093b2629efe0a86fde32ce9908ddfcba777233`, after
[PR 27](https://github.com/itse4elhaam/dotfiles/pull/27) and
[PR 28](https://github.com/itse4elhaam/dotfiles/pull/28) were merged.

`git subtree split --prefix=apps/recit main` preserved the three app-specific
commits and promoted their files to the repository root. The extracted root tree
is `d28fc048f46b2f9989073d41496f3477fa447836`, identical to the source app tree.
Unrelated dotfiles files and commits are absent from the new repository history.

Commit mapping:

- `622057538783fa3653b05662f59c32bc269261e9` became `12517a6`.
- `77b0f14b8153e35a7ab01f83a780a6b8e426f537` became `7e62293`.
- `da094cbab3b822491371936cc1151a2cfe1bbba4` became `c42f566`.

The original commits and review discussions remain in dotfiles. The unmerged
[capture-selection PR 29](https://github.com/itse4elhaam/dotfiles/pull/29)
is not part of Untangle's imported baseline. Carrying it over requires a
separate reviewed PR; it must not enter through the branding change.

## Local development and T3

The initial checkout is `/home/elhaam/workspace/coding/untangle`. T3 registers
that directory as the **Untangle** project. Its setup command creates only a
repository-local `.venv`; its test command uses offscreen Qt. Neither runs on
worktree creation. No script automatically installs or launches the recorder.

```bash
uv venv --python /usr/bin/python3 .venv
uv pip install --python .venv/bin/python -r requirements.txt
./scripts/test.sh
bash -n scripts/*.sh bin/*
```

## Source layout

- `src/untangle/` contains production Python and the `python -m untangle` entry point.
- `tests/` contains unittest modules; `tests/fixtures/` holds synthetic device data.
- `scripts/test.sh` runs safe offscreen checks from any working directory, using the local `.venv` when present.
- `scripts/install.sh` installs only when explicitly invoked; `scripts/connect-loom.sh` handles interactive Loom consent.
- `bin/untangle` and `bin/recit` resolve the checkout through symlinks and add its `src/` to `PYTHONPATH`.
- Root `assets/` holds the existing logos used by the app, README, and T3.

Direct unittest discovery from the repository root needs `PYTHONPATH=src`,
`QT_QPA_PLATFORM=offscreen`, no display, and no hardware opt-in switches.
Prefer `./scripts/test.sh`, which sets and clears these values for you.
Manual native diagnostic scripts now live at `tests/test_native_audio.py` and
`tests/test_hardware_audio.py`. They need `PYTHONPATH=src` when invoked directly;
their workers resolve the source path and repository working directory themselves.
Their opt-in flags still require explicit hardware authorization.

## Installed app cutover

Creating the repository and project does not redirect the installed application.
The existing launcher can continue to use dotfiles until a reviewed cutover is
explicitly installed with `./scripts/install.sh`. Do not remove the old app directory before verifying that
cutover and its rollback.

Keep existing preferences, `~/.local/share/glint/`, `~/.local/state/glint/`,
`~/Videos/RecIt`, and single-instance identifiers compatible. They contain user
state or identify the existing app; renaming the product is not permission to
move or reset them. Authentication and recording data are not repository assets.
