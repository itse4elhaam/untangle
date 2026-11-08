# Audio troubleshooting

Inspect existing logs only. A new microphone check, Bluetooth profile change,
capture or audible playback requires explicit authorization; use
[the safe verification rules](testing.md).

The launcher writes stderr to `~/.local/state/glint/glint.log` with 10 MB rotation.
Audio records start with `recit.audio ` and one JSON object. Find a finished
capture's `session.start`, then filter its session:

```bash
rg 'recit.audio ' ~/.local/state/glint/glint.log
rg '"session":"YOUR_SESSION_ID"' ~/.local/state/glint/glint.log
```

## Follow the evidence

A session starts before device preparation and follows capture, release,
restoration and file validation. `purpose` means origin, not current UI state.
An idle monitor handed to recording stays `idle`; a fresh recording is `record`
and Quick audio check is `check`. Deferred restoration retains the session that
changed the profile. `elapsed_ms` is monotonic; `duration_ms` measures one operation.

Read selection/profile/source resolution first. Pulse source and BlueZ card are
separate identities; `changed:false` means hands-free mode was already active.
`connection.checked` separates live BlueZ connection evidence from potentially
stale PipeWire properties. Source metadata reports mute, gain and input format;
16000 Hz input is still bandwidth-limited even when OBS mixes at 48000 Hz.
Untangle does not change mute/gain.

Then compare `route.verified` or `route.mismatch` with the requested source.
A requested OBS device ID alone never proves actual attachment. Telemetry reports
packet counts, nonzero packets, age and post-filter levels. Missing/stale packets
and zero-only audio are different failures. JSON `null` means no finite dBFS
value. Summaries are polled at most every five seconds, with explicit boundary
results; native callbacks never log per-frame data.

Finally inspect release/restoration and saved validation. `restore.deferred`
means ownership/busy-stream protection; `restore.skipped` means the card vanished,
disconnected or another app changed its profile. `restore.requested` proves only
server acceptance, not completed hardware restoration. `saved_validation.result`
distinguishes missing track, exact digital silence and nonzero decoded audio;
`failed` means validation could not finish. Recording validation decodes stopped
MKV before remux; Quick check validates its temporary sample.

## Owners and limits

[AudioTrace](../src/untangle/audio_debug.py) owns fields, redaction and throttling;
[test_audio_debug.py](../tests/test_audio_debug.py) owns correlation and privacy
regressions. Event producers live in [audio_devices.py](../src/untangle/audio_devices.py),
[idle_audio.py](../src/untangle/idle_audio.py), [audio_check.py](../src/untangle/audio_check.py)
and [engine.py](../src/untangle/engine.py). Consult these instead of a copied event inventory.

Logs exclude samples, PCM, transcripts, credentials, environment dumps, filenames,
full pactl payloads and raw error/process output. They include source/card IDs
and friendly names, so review before sharing. Meter activity and nonzero samples
do not prove intelligible speech or headset quality. Synthetic tests cannot
establish live Bluetooth reliability. The [dated OnePlus diagnostic](testing.md#dated-hardware-evidence)
observed exact zeros across native and OBS paths; its root cause remains unresolved.
