# UI standards

Review production Qt widgets, not an HTML or SVG imitation. Use [AGENTS.md](../AGENTS.md) for session safety, test isolation, compatibility, and delivery authority. [Brand guidance](brand.md) owns identity; `theme.py` owns styling values.

## Required behavior

- Essential mode, source, camera, microphone, and recording actions must be discoverable without opening advanced settings. Ordinary scrolling over a closed dropdown must not change the selection.
- Setup stays beside the preview. Recording state, elapsed time, Pause, and Stop remain reachable when setup is hidden or the library is open during a stable take. Countdown, preparation, and saving retain their guards. Sharing settings cannot mutate an active take.
- Preview expansion changes local layout, not recording composition. Canvas presets select framing; the compatibility Fit/Fill preference is not a visible picker. Camera crop/zoom, overlay size, and screen pointer zoom are distinct. Preserve per-mode preferences and input locks.
- Microphone off, monitoring off, waiting, no packets, silence, and signal are distinct. A meter never certifies intelligible speech or a saved file. Audio-check playback requires Play; returning releases its resources before setup resumes.
- Library selection stays silent until Play. Returning stops playback and preserves recorder setup. Upload choice is explicit for each take; failures retain local media and distinguish a known link from verified audience permissions.
- At 960 x 760 and 1120 x 840, both themes and recording modes must fit without overlapping primary controls, clipped actions, or horizontal scrolling. Long names can elide with full tooltips. Focus stays visible without changing geometry. Warnings need text as well as color.

Exact labels, control positions, and styling values belong to the source and current captures. Do not copy an old layout back into the app to satisfy a dated screenshot.

## Visual release gate

1. Run the required safe checks in AGENTS.md.
2. Regenerate affected complete windows through the isolated renderer:

   ```bash
   ./scripts/render-safe.sh docs/ux-overhaul/matrix ui
   ```

3. Inspect affected recorder, expanded controls, Settings, audio recovery, and populated/empty library states. Include long names, failures, both sizes/themes, and relevant canvas presets. Compare with the [reference gallery](ui-baselines/index.html); explain intended differences in the PR.
4. For the user-approved UX loop, obtain two fresh agent reviews of anonymous complete-window evidence and task traces. Preserve disagreements. This replaces routine manual visual QA only for styling, copy, layout, and the approved review/sharing navigation scope. Product and merge approval remain with the user.

The original overhaul also required user review of its stacked PRs and comparison video before merge. Only later explicit approval for that task superseded the hold; agent scores alone did not.

The manifests identify source/image hashes, dimensions, and mocked boundaries. PNGs are references, not pixel-hash assertions; font rasterization can differ. Geometry and interaction checks supplement visual review. Never crop away a defect or weaken a check to hide it.

Synthetic source pixels, devices, files, media backends, and service events establish only the disclosed evidence. Native input checks on private Xvfb establish that tested environment, not host-compositor behavior. Capture/audio changes, authentication, uploads, deletion, retention, recording formats, and live hardware acceptance remain outside visual-review authority.
