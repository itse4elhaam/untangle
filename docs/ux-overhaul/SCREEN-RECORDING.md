# During a screen recording

[Watch the synchronized side-by-side desktop recording](screen-recording-side-by-side.mp4) or [open its single comparison frame](screen-recording-side-by-side.png). The earlier [86-second step walkthrough](screen-recording-before-after.mp4) remains available. [Competitor comparison and next loop](../research/screen-recording-experience.md).

The previous overhaul is squash-merged in PR #38 as `5fb8e3d874fca203aeac0caa410f854d32b1dfc5` and installed locally from its pushed immutable archive. This recording-controls pass is a separate reviewable change.

## What changes

- Selected X11 window: compact controls show elapsed time, the fixed target, microphone input state, Pause, Stop and save, and existing confirmed restart/discard actions.
- Whole display or portal-selected source: requesting controls pauses first. Resuming hides them before capture resumes. If that would hide the last Stop route, the take stays paused and asks for a reachable Stop control.
- Untangle stays visible when neither a tray, confirmed stop shortcut nor interactive camera bubble is available. A failed shortcut registration never counts as a Stop route.
- Hidden-window users can inspect microphone input state and retained warnings in the tray. Input telemetry does not certify saved speech.
- Native camera resizing retains its exact fraction when the bubble is hidden and shown again. Capture inputs and resizing remain locked during a take.

Opening Untangle or the tray during whole-screen capture can appear in the recording. This pass does not promise the macOS capture exclusion documented by Screen Studio. Encoding settings, audio processing, save/recovery, upload consent and compatibility identifiers are preserved.

## Evidence

| Video interval | Observed task |
|---|---|
| 00:00–00:12 | Selected-window take: before, then after |
| 00:12–00:24 | Paused take and frozen timer |
| 00:24–00:38 | Missing microphone samples while the main window is hidden |
| 00:38–00:50 | Active whole-screen take: new controls hidden |
| 00:50–01:02 | Whole-screen controls appear while paused |
| 01:02–01:14 | Resume hides the new controls |
| 01:14–01:26 | Existing saving path locks actions |

The video holds production Qt widget captures over a synthetic QTextEdit. Engine, elapsed time, audio, files and save events are fixtures; it is not footage from a real recording. The manifests record reached states and source hashes. The second synthetic take asserts start, pause, resume and saving states before captions are emitted. Baseline source hashes were checked against Git revision `5fb8e3d`; after hashes match this candidate. Dark and light captures are in `screen-after/` and `screen-light/`; before captures are in `screen-before/`.

Validation:

- Full safe runner: **717 tests passed, two opt-in hardware checks skipped**. Includes private Xvfb at 1× and 1.5×, with mocked and restricted OBS backends. OBS loads only synthetic selected-window/image/filter sources; no camera or audio plugins. Checks native camera dragging/resizing/reattachment, transparent-corner input routing, typing/text selection in the original target, and native dock Pause without stealing keyboard focus.
- Final recording-focused safe suite after copy cleanup: **59 tests passed**.
- Shell syntax and whitespace checks passed. Existing UI matrix regenerated in the safe renderer; light/dark complete recorder/library/error layouts remain covered by the safe suite.
- Independent review found a last-Stop resume defect; fixed and regression-tested. Visual review found invalid second-take evidence; fixture corrected, assertions added and captures regenerated. Final visual feedback about an ampersand mnemonic and truncated guidance was resolved with “Stop and save” and a short visible microphone state; full warning remains in its tooltip/tray.

No host app launch, live capture devices, desktop services, account operations, uploads or audible playback were used. Native tests establish input routing on a private synthetic desktop, not portal/compositor behavior or encoded pixels/audio quality.

## Reproduce safely

```bash
./scripts/test.sh
bash -n scripts/*.sh bin/*
./scripts/render-safe.sh "$PWD/docs/ux-overhaul/screen-after" recording --version after
./scripts/render-safe.sh "$PWD/docs/ux-overhaul/screen-light" recording --version after --theme light
python3 scripts/build-ux-video.py --before docs/ux-overhaul/screen-before --after docs/ux-overhaul/screen-after --output docs/ux-overhaul/screen-recording-before-after.mp4
```

Xvfb must be available on PATH to run the isolated native input lane; otherwise that lane explicitly skips. No hardware flags are needed or enabled. The before renderer accepts `--source-root` pointing to an archive of the stated baseline; baseline hashes are retained for audit.

## Recorded side by side

The new video records two actual Qt sessions on separate private Xvfb desktops, then aligns them horizontally: baseline `5fb8e3d` on the left, PR #39 on the right. It includes live timer updates, Qt mouse clicks on the new Pause/Resume controls, typing in a synthetic shared editor, microphone warning presentation, whole-screen control visibility, saving and a saved-take review action. Each session asserts that pause/resume/start/save states were reached. The combined PNG is extracted from the combined video at 00:11, during the microphone-warning task.

OBS/device/audio/file/process boundaries remain inert fixtures. Baseline shortcut actions and media/save events are injected; no actual user recording is produced or played. FFmpeg records only the explicitly created private Xvfb desktop, inside the existing device/network/session isolation. Application-triggered external processes remain blocked. No host desktop or devices are available to the sessions. This is an interactive UI recording, not a claim about encoded OBS output or saved audio.

To reproduce, make Xvfb available on PATH, and archive the baseline revision to a read-only source directory:

```bash
./scripts/render-safe.sh "$PWD/docs/ux-overhaul/recorded-before" recording-video --version before --source-root /path/to/baseline-5fb8e3d
./scripts/render-safe.sh "$PWD/docs/ux-overhaul/recorded-after" recording-video --version after
ffmpeg -i docs/ux-overhaul/recorded-before/raw.mp4 -i docs/ux-overhaul/recorded-after/raw.mp4 -filter_complex '[0:v]setpts=PTS-STARTPTS[left];[1:v]setpts=PTS-STARTPTS[right];[left][right]hstack=inputs=2:shortest=1[v]' -map '[v]' -an -c:v libx264 -crf 19 -pix_fmt yuv420p -movflags +faststart docs/ux-overhaul/screen-recording-side-by-side.mp4
ffmpeg -ss 11 -i docs/ux-overhaul/screen-recording-side-by-side.mp4 -frames:v 1 docs/ux-overhaul/screen-recording-side-by-side.png
```

The private display is mandatory; the renderer fails rather than using a host display. Raw takes and logs remain ignored local artifacts.
