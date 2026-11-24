# Using Untangle

Open Untangle from the application launcher or run `untangle`. Opening it can activate capture devices.

## Record a take

1. Choose **Camera** or **Screen** in the left sidebar. Select your camera and microphone. Camera Off disables camera-only recording or removes the screen overlay.
2. On X11, choose a screen or window; refresh the list if needed. On Wayland, use the system picker and **Choose / change source** to retry or change selection.
3. In Camera mode, choose **Canvas** above the preview and adjust **Zoom**. Use Settings for quality, microphone cleanup, computer sound and camera appearance.
4. Check **Upload this take to Loom** to start uploading as soon as the saved MP4 is verified, without a name prompt. Unchecked takes stay local and use the usual naming. Untangle remembers the choice for later takes, including after restart, until you uncheck it here or in Sharing. Camera-only takes show a reminder during countdown when upload is on. Countdown freezes the choice for the current take.
5. Choose **Start recording** in the bottom bar. Escape cancels countdown or microphone preparation. Stop saves; Pause freezes capture. Discard and Restart ask for confirmation before deleting the take; Restart then begins a new take.

On X11, **Ctrl+Shift+F9** starts or stops, **F10** with the same modifiers pauses/resumes, and **F8** toggles pointer zoom. Wayland disables global shortcuts, pointer zoom and the floating camera; use recorder/tray controls. See [Linux support](linux-support.md) for limitations and pending live validation.

Recorder choices, including devices, canvas, zoom, overlay, floating-camera position and window size, save as you change them and survive restart. A disconnected camera or display shows as *Unavailable …* and blocks recording until you reconnect it or choose another (or Camera Off). Window capture asks for a window again.

Keep an X11 selected window open and unminimized. Closing or minimizing stops and saves with a warning. Computer sound captures system audio, not just that window. Entire-screen capture includes visible app windows, camera-widget menus and tooltips.

## Frame the camera

Canvas presets include landscape, Reels / Shorts, square, portrait and **Raw · source size**. Social presets crop the center; landscape normally fits with bars. Fit/Fill remains a saved preference, but its picker is hidden. Raw follows source dimensions with encoder alignment, not uncompressed encoding. The surrounding preview workspace is not recorded.

Camera Zoom crops from 100–300%; Reset returns to 100%. Overlay Size changes its area instead. Zoom cannot add detail. Capture controls lock during preparation, recording and saving. Sidebar toggles setup visibility without changing the canvas.

On X11, drag the floating camera to position it; its context menu offers recording controls. Custom masks use transparent PNG areas to hide the camera and opaque areas to show it. In entire-screen capture the camera is part of the desktop and can move out of frame during zoom; selected-window capture anchors it separately.

**Smaller camera recording files**, off by default, trades fine detail for size. It affects future camera takes only and prevents switching to screen presentation. Existing files stay unchanged.

## Check audio

Bluetooth earbuds have two modes: high-quality playback with no microphone, or hands-free, which adds the microphone but lowers playback quality.

- **Automatic microphone** uses the system default input as it is when the take starts, such as a wireless receiver, and never switches the earbuds. (Earlier versions used the earbuds' microphone whenever they were the sound output.)
- To record with the earbuds' microphone, choose *<earbuds> microphone (switches on when recording starts)*. Untangle switches them to hands-free only when a recording starts.
- It restores the earlier mode as soon as the take stops, is discarded or fails, or Untangle quits. Music or video on the earbuds does not delay that; another app still using the earbud microphone does.
- If Untangle crashes or is killed mid-take, its next launch takes over that restore. It finishes once the earbuds are connected and no app uses their microphone, unless their mode was changed outside Untangle.
- If Untangle cannot save its restore record, it does not switch the earbuds and says why. Earbuds already in hands-free with a microphone are used as they are.
- With the earbud microphone selected, or a Bluetooth microphone as the system default input, live levels pause and show *Earbud mic switches on when recording starts*. Quick audio check explains that it cannot test that microphone without lowering playback quality.
- Other microphones keep live levels and Quick audio check. Turn levels off to release idle monitoring.
- Quick audio check captures four seconds only after **Record sample**, and plays only after **Play sample**.

Untangle checks connection, mute and volume without changing system gain or mute, then requests fresh nonzero microphone samples. Microphone Off bypasses this check. Clean microphone suppression may hide very quiet speech; try disabling it when diagnosing. Computer sound cannot satisfy the microphone check.

Suppression does not cancel speaker echo or fix overload; the microphone limiter cannot protect the combined mix. Levels do not prove intelligible saved audio. Bluetooth silence remains unresolved. Restoration never overrides a profile changed outside Untangle, and waits while another app records from the earbud microphone. See [audio notes](audio-notes.md) and [troubleshooting](audio-troubleshooting.md).

## Name and review

Videos save to `~/Videos/RecIt`. Automatic naming is opt-in; older AI preferences are reset once. It transcribes locally, then sends transcript text to Codex using Luna, medium reasoning and the default service tier. **Name manually** cancels; failures fall back to the manual prompt. **Keep current name** preserves the filename. Loom-bound takes skip the prompt; with automatic naming on, they are named after the share result. A failure, or a file in playback, frame review or editing, keeps the saved name. [Privacy, prerequisites and lifecycle](local-titles.md).

Open **Recordings**, search or select a video, then **Play**. Selection alone does not play. Rename or F2 changes the local title without overwriting another file; Loom links follow the rename, but upstream titles stay unchanged. Copy path, delete and upload actions operate on the selection. Back to recorder stops playback. Volume, mute, pane split and each Drive remote's folder are remembered.

The library can open during recording or upload. Stop/Pause remain reachable during recording; conflicting file actions are locked. Countdown and busy save/preparation block entry. An idle library cannot start a take.

## Loom

Use **Sharing → Connect Loom account** and complete browser consent yourself. The official CLI owns credentials; connecting does not upload. Upload a selected video from Recordings, or opt in before a take. Sharing changes save immediately, even if you close the dialog.

Opted-in takes upload one at a time, in order, with the audience and title choices selected at countdown. A queued take that changed is skipped with a notice. Save errors, discards and recovery never start an upload. **Save** while quitting mid-recording keeps that take local; takes saved earlier finish uploading first.

The link is copied once Loom confirms the requested audience, without waiting for titles or processing; **Skip title update** ends the title step early. A notification then says the upload is complete and the link copied, noting when Loom is still processing. If the audience is not confirmed, nothing is copied automatically; the notification asks you to review sharing in Loom instead. The link still appears with a warning and can be copied by hand after you check sharing in Loom. Title failures also keep the link. Local filenames supply titles unless **Let Loom generate titles when available** is on; then Loom may choose its own and no rename is sent.

Upload time is mostly file size, so recordings are capped at 400 kbps per frame per second (12 Mbps at 4K30); 1440p and below are unchanged and camera quality is not lowered further. The official CLI uploads only a finished file, so no fixed time to a link is promised. CLIs without upload visibility apply sharing afterwards, so account defaults apply briefly. Failures keep local files; check Loom before retrying an interrupted upload to avoid duplicates. An expired sign-in offers **Reconnect Loom…**, which forces a fresh login. **Forget Loom link** removes local metadata only. Disconnect signs out the selected TWG profile across Atlassian products.

**Delete local copy after a verified Loom upload** in Sharing is on by default. After an upload, Untangle asks Loom for the video again and permanently deletes the local file (not Trash) only when Loom reports the same video playable with the same length, and the file is unchanged. Loom offers no checksum, so this is a length and identity check, not a byte comparison. Processing, recording or playing that file delays the check for about 20 minutes; unknown or mismatched results, or a frame review using the file, keep it. **Notifications** in the recorder header lists upload and cleanup outcomes with Copy link and Open in Loom. They are mirrored as tray messages where supported, except a copy kept because automatic deletion is off; clicking a tray message opens the list. Deleted recordings keep their links under **On Loom only** in Recordings.

Imported-video AI titles remain unconfirmed. Historical [vendor notes](https://support.atlassian.com/loom/docs/upload-or-import-videos/) recorded Business/Business + AI/Enterprise eligibility, excluded AI trials, and 4 GB/12-hour limits; these and real account upload remain unverified here. `loom.truedevs.tech` was not configured. The official CLI was chosen because the recording SDK is not a local-file upload API. See [capability evidence and official sources](loom-integration.md); [Drive setup](google-drive.md) is separate.

## Recovery

Interrupted recordings may leave MKV files. Select one in Recordings and choose **Prepare MP4**. Successful stream-copy conversion removes the MKV; failure preserves it. Review before uploading. Alternatively, use `ffmpeg -i recording.mkv -c copy -movflags +faststart recovered.mp4`. Logs remain at `~/.local/state/glint/glint.log`.
