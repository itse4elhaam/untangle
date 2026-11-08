# Camera and Loom UI evidence

Historical capture pack. The manifest identifies its source; these images are not the current release. Use [UI standards](../ui-standards.md) for isolated reproduction.

These are production Qt widgets rendered offscreen with synthetic data. Camera,
audio, playback, account commands, and uploads are mocked. No installed app or
user recording was opened. The camera sheet uses synthetic pixels to show alpha
edges at 1×, 1.25×, and 2× device scale; it does not verify a live GPU compositor.

The manifest records source and PNG hashes for the selected Loom captures.
The upload-progress example injects a labeled 42% event to verify that path.
The currently installed CLI provides no percentage telemetry, so normal uploads
show an indeterminate indicator and elapsed time.

Reproduce from the repository root:

```bash
./scripts/test.sh
bash -n scripts/*.sh bin/*
```

`render-loom-ui.py` and `render-camera-edges.py` produced this historical pack. The current wrapper has no dedicated modes for them; do not reproduce them by bypassing isolation.

The Loom renderer produces light and dark versions at 960×760 and 1120×840.
It covers uploading, success, authentication failure, connected account,
title-preference opt-out, and the library's saved title and link actions.

For an authorized manual check after installation, open Sharing and check the
connected identity. Upload a disposable recording, observe the transfer and
processing states, then open or copy its link from Recordings. Restart manually
to check persistence. Rename the local file and verify its link follows; choose
Forget Loom link and verify that both the recorder and library hide it.

The current CLI cannot confirm remote deletion or enable remote AI settings.
See [capabilities and source references](../loom-integration.md). Live capture,
GPU/compositor performance, real authentication, and real uploads still require
separate authorized validation.
