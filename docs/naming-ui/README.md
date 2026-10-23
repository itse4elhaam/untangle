# Recording names

Actual Qt dialogs rendered with synthetic paths. No app launch, recording,
playback, filesystem rename, or Loom request is used in these captures.

Reproduce with `.venv/bin/python scripts/render-naming-ui.py`.
The manifest records the source and screenshot hashes.

- `finished-light.png` and `finished-dark.png`: prompt after a successful save.
- `rename-light.png` and `rename-dark.png`: library rename dialog, also opened with F2.
- `error-light.png` and `error-dark.png`: a synthetic rename failure, with retained input and retry.

Safe validation: `./scripts/test.sh` and `bash -n scripts/*.sh bin/*`.
The integration tests check that naming resolves before automatic upload,
cancel preserves the saved file, and existing Loom metadata follows a rename.
