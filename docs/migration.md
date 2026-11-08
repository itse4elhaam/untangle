# Standalone repository

Untangle was extracted on 2026-10-22 from `apps/recit` in
[itse4elhaam/dotfiles](https://github.com/itse4elhaam/dotfiles).
The source revision is `eb093b2629efe0a86fde32ce9908ddfcba777233`, after
[PR 27](https://github.com/itse4elhaam/dotfiles/pull/27) and
[PR 28](https://github.com/itse4elhaam/dotfiles/pull/28) were merged.

`git subtree split --prefix=apps/recit main` preserved the three app-specific
commits and promoted their files to the repository root. The extracted root tree
is `d28fc048f46b2f9989073d41496f3477fa447836`, identical to the source app tree.
Unrelated dotfiles files and commits are absent from the imported history.

## Commit mapping

- `622057538783fa3653b05662f59c32bc269261e9` became `12517a6`.
- `77b0f14b8153e35a7ab01f83a780a6b8e426f537` became `7e62293`.
- `da094cbab3b822491371936cc1151a2cfe1bbba4` became `c42f566`.

Original commits and review discussions remain in dotfiles. The then-unmerged
[capture-selection PR 29](https://github.com/itse4elhaam/dotfiles/pull/29)
was excluded from the imported baseline. Carrying it over requires a separate
reviewed PR; it must not enter through branding changes.

## Development and T3

The initial checkout was `/home/elhaam/workspace/coding/untangle`, registered
as the Untangle T3 project. Its setup created only a repository-local `.venv`;
setup and headless tests did not run automatically on worktree creation. No
script automatically installed or launched the recorder.

See [README](../README.md#development) for setup. Always use the isolated runner:

```bash
./scripts/test.sh
# Focus a suite without bypassing isolation:
UNTANGLE_TEST_PATTERN=test_local_titles.py ./scripts/test.sh
bash -n scripts/*.sh bin/*
```

The runner fails closed without bubblewrap isolation. Direct unittest discovery
can reach real devices through incomplete mocks. Manual native/audio diagnostics
remain opt-in and require explicit hardware authorization; they are not routine
verification.

## Installed app cutover

Creating the repository and project does not redirect the installed application.
The old launcher can continue using dotfiles until a reviewed cutover is
explicitly installed with `./scripts/install.sh`. Do not remove the old app
directory before verifying cutover and rollback. See [installation](linux-support.md).

Keep existing preferences, `~/.local/share/glint/`, `~/.local/state/glint/`,
`~/Videos/RecIt`, and single-instance identifiers compatible. They contain user
state or identify the existing app; renaming the product is not permission to
move or reset them. Authentication and recording data are not repository assets.
