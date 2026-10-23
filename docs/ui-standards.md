# UI standards

The shipped interface is Clearline, in light and dark modes. Review actual production Qt widgets. Do not substitute an HTML or SVG recreation of the app.

## Required behavior

- Mode, camera, microphone, computer sound and live-monitor controls are visible on entry. Only less frequent settings need a disclosure.
- Setup stays left of the large preview. The recording action stays at the lower right; Recordings and Sharing stay outside the scrolling setup region.
- Screen mode names its display or window. Camera mode states that only the camera is recorded. Expanding the camera changes local layout, not output composition.
- Canvas and Fit/Fill stay above the preview. Camera zoom, percentage and Reset stay with the camera selector; widget size and pointer zoom remain separate. Presets retain their aspect ratio in the preview and encoded canvas.
- More options scrolls its fields into view on opening at 960 × 760. New canvas, quality and camera framing controls lock through countdown, preparation, recording and saving.
- Microphone off, monitoring off, waiting, no packets, silence and signal are distinct. A live meter never certifies a saved file or intelligible speech.
- The audio check retains visible source context and a clear return. Returning safely releases the check, unlocks setup and permits a different input. Samples play only after Play sample.
- Library selection is silent. Play is explicit. Return releases playback and preserves recorder setup.
- At 960 × 760 and 1120 × 840, both themes and both recording modes must fit. No overlapping primary controls, clipped action text or horizontal scrolling. Long device names may elide with a full tooltip.
- Focus must remain visible and must not change control geometry. Stop, saving and recoverable errors retain readable text; color alone is insufficient.

## Release gate

1. Run `./scripts/test.sh`. This includes actual Qt click-through checks, layout checks, ownership/recovery tests and an installer test in an isolated temporary home.
2. Run `bash -n scripts/*.sh bin/*`.
3. Regenerate the synthetic Qt captures with `.venv/bin/python scripts/render-ui.py --output docs/ui-baselines`. Inspect recorder, expanded camera, advanced settings, audio failure/recovery, and populated/empty library at both sizes and themes. Inspect long names and failure states at the minimum size.
4. Compare the complete client windows to the pinned captures in `ui-baselines/`. Explain intended changes in the PR. Do not accept a screenshot cropped around a defect or a test weakened to hide it.

The canvas matrix covers landscape, Reels / Shorts, square, 4:5, zoom/reset and Fit/Fill at both sizes and themes, including screen-plus-camera portrait and square scenes. Only capture pixels are synthetic; source crop/placement uses the production composition helper. Native OBS filter execution and encoded pixels still need separately authorized capture verification.

[Browse the pinned Qt windows](ui-baselines/index.html). The manifest records source hashes, PNG hashes, exact dimensions and the mocked boundaries for each image.

The PNGs are review references, not exact pixel-hash assertions. Font rasterization and Qt patch releases can differ. The tests pin interaction, geometry and text fit; a human visual review checks hierarchy and appearance.

All captures use isolated settings, mocked device/engine boundaries, a painted SYNTHETIC source and synthetic local media. They do not open capture devices, change Bluetooth profiles, play audible audio or change desktop accessibility settings. Never use the production app launch as an incidental verification step.
