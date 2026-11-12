# Using Untangle

Open Untangle from the application launcher or run `untangle`. Opening it can activate capture devices.

## Record a take

1. Choose **Camera** or **Screen** in the left sidebar. Select your camera and microphone. Camera Off disables camera-only recording or removes the screen overlay.
2. On X11, choose a screen or window; refresh the list if needed. On Wayland, use the system picker and **Choose / change source** to retry or change selection.
3. In Camera mode, choose **Canvas** above the preview and adjust **Zoom**. Use Settings for quality, microphone cleanup, computer sound and camera appearance.
4. Check **Upload this take to Loom** only if you want upload after saving and naming. Sharing supplies future defaults. Countdown freezes this choice; cancelling preserves it.
5. Choose **Start recording** in the bottom bar. Escape cancels countdown or microphone preparation. Stop saves; Pause freezes capture. Discard and Restart ask for confirmation before deleting the take; Restart then begins a new take.

On X11, **Ctrl+Shift+F9** starts or stops, **F10** with the same modifiers pauses/resumes, and **F8** toggles pointer zoom. Wayland disables global shortcuts, pointer zoom and the floating camera; use recorder/tray controls. See [Linux support](linux-support.md) for limitations and pending live validation.

Keep an X11 selected window open and unminimized. Closing or minimizing stops and saves with a warning. Computer sound captures system audio, not just that window. Entire-screen capture includes visible app windows, camera-widget menus and tooltips.

## Frame the camera

Canvas presets include landscape, Reels / Shorts, square, portrait and **Raw · source size**. Social presets crop the center; landscape normally fits with bars. Fit/Fill remains a saved preference, but its picker is hidden. Raw follows source dimensions with encoder alignment, not uncompressed encoding. The surrounding preview workspace is not recorded.

Camera Zoom crops from 100–300%; Reset returns to 100%. Overlay Size changes its area instead. Zoom cannot add detail. Capture controls lock during preparation, recording and saving. Sidebar toggles setup visibility without changing the canvas.

On X11, drag the floating camera to position it; its context menu offers recording controls. Custom masks use transparent PNG areas to hide the camera and opaque areas to show it. In entire-screen capture the camera is part of the desktop and can move out of frame during zoom; selected-window capture anchors it separately.

**Smaller camera recording files**, off by default, trades fine detail for size. It affects future camera takes only and prevents switching to screen presentation. Existing files stay unchanged.

## Check audio

Bluetooth earbuds have two modes: high-quality playback with no microphone, or hands-free, which adds the microphone but lowers playback quality. Untangle switches them to hands-free only while a recording uses their microphone, then restores the earlier mode when the take ends, fails or is discarded, or when Untangle quits. **Automatic microphone** uses the earbuds' microphone whenever they are the sound output; choose another microphone, such as a wireless receiver, explicitly to keep earbud playback at full quality. Until a recording starts, live levels for the earbud microphone pause and show *Earbud mic switches on when recording starts*. Other microphones keep live levels. Turn levels off to release idle monitoring. Quick audio check captures four seconds only after **Record sample**, and plays only after **Play sample**; for the earbud microphone it asks for a second click, **Switch earbuds and record**, and restores playback afterwards.

Untangle checks connection, mute and volume without changing system gain or mute, then requests fresh nonzero microphone samples. Microphone Off bypasses this check. Clean microphone suppression may hide very quiet speech; try disabling it when diagnosing. Computer sound cannot satisfy the microphone check.

Suppression does not cancel speaker echo or fix overload; the microphone limiter cannot protect the combined mix. Levels do not prove intelligible saved audio. Bluetooth silence remains unresolved. Restoration respects other streams and external profile changes, so playback-profile restoration may be deferred. See [audio notes](audio-notes.md) and [troubleshooting](audio-troubleshooting.md).

## Name and review

Videos save to `~/Videos/RecIt`. Automatic naming is opt-in; older AI preferences are reset once. It transcribes locally, then sends transcript text to Codex using Luna, medium reasoning and the default service tier. **Name manually** cancels; failures fall back to the manual prompt. **Keep current name** preserves the filename. [Privacy, prerequisites and lifecycle](local-titles.md).

Open **Recordings**, search or select a video, then **Play**. Selection alone does not play. Rename or F2 changes the local title without overwriting another file; Loom links follow the rename, but upstream titles stay unchanged. Copy path, delete and upload actions operate on the selection. Back to recorder stops playback.

The library can open during recording or upload. Stop/Pause remain reachable during recording; conflicting file actions are locked. Countdown and busy save/preparation block entry. An idle library cannot start a take.

## Loom

Use **Sharing → Connect Loom account** and complete browser consent yourself. The official CLI owns credentials; connecting does not upload. Select a video in Recordings and choose **Upload to Loom**, or opt in before a take. Automatic upload waits for naming; save errors, discarded/changed files, recovery and quitting do not trigger it.

Visibility is applied after upload, so account defaults apply initially. Failures preserve local files. Check Loom before retrying an interrupted upload to avoid duplicates. Permission/title failures can retain a working link with a warning. **Forget Loom link** only removes local metadata. Disconnect signs out the selected TWG profile across Atlassian products.

Local filenames supply titles unless **Let Loom generate titles when available** is enabled. Imported-video AI titles remain unconfirmed. Historical [vendor notes](https://support.atlassian.com/loom/docs/upload-or-import-videos/) recorded Business/Business + AI/Enterprise eligibility, excluded AI trials, and 4 GB/12-hour limits; these vendor details and real account upload remain unverified here. `loom.truedevs.tech` was not configured. The official CLI was chosen because the recording SDK is not a local-file upload API. Consult [capability evidence and official sources](loom-integration.md). [Drive setup](google-drive.md) is separate.

## Recovery

Interrupted recordings may leave MKV files. Select one in Recordings and choose **Prepare MP4**. Successful stream-copy conversion removes the MKV; failure preserves it. Review before uploading. Alternatively, use `ffmpeg -i recording.mkv -c copy -movflags +faststart recovered.mp4`. Logs remain at `~/.local/state/glint/glint.log`.
