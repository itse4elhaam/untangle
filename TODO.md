# Untangle requested work

Do not deploy, install, activate timers, upload recordings, or launch the app without explicit authorization. Use only low, medium, or high reasoning for delegated work. Preserve the repository's device, speech, and safe-test safeguards.

## Delivered for review

- [x] Automatic Google Drive archiving, configurable destination, verified uploads, seven-day retention, in-app confirmation, and no deletion without a current Drive or Loom copy. PR #18; not deployed.
- [x] Rename and delete icons beside individual recordings, retaining existing safety checks. PR #19; not deployed.

## Active implementation

- [ ] Default to the highest-quality available camera. Rank advertised colour resolution at 30 fps, then frame rate; allow manual selection. Synthetic parser/discovery tests are written; not yet committed.
- [ ] Collapse the lower recorder status/details area shown in the screenshot behind a disclosure control; collapsed by default. Preserve important errors and recording state visibility.
- [ ] Move Quick audio check from the primary setup pane to Settings, preserving its existing checks and cleanup behavior.
- [ ] Keep camera framing/zoom preferences separate for camera-only and screen-plus-camera setups, including reload and mode switching.
- [ ] Remove the redundant “Recording setup” heading and the “Screen + optional camera.” / equivalent mode helper text, preserving mode controls.
- [ ] Add a Settings control to reposition the camera image inside its fixed shape, like moving an image within a crop. Preserve the shape position/size; persist framing per setup and test boundaries.
- [ ] Provide a complete repeatable Google Drive setup guide using the wizard skill for every human prerequisite: Google project/API, OAuth consent/Desktop client, local configuration/sign-in, destination, background scheduling, verification, troubleshooting and disabling. Do not run the wizard or activate anything.

## Dedicated workstreams requested by user

- [ ] Create a focused camera-widget resize thread. Implement user resizing by dragging/extending its boundary, preserving the existing shape and recording geometry; no deployment.
- [ ] Create a UX/UI audit thread using GPT-6.1 Sol at high. Audit the complete app against Loom and Supercut, implement only small changes with negligible risk, and propose the others to the user. No change has literally zero risk; keep device, capture, upload, auth, and deletion behavior out of automatic polish.
- [ ] Create an independent accountability thread to check every item here, track evidence/PRs and omissions, and report incomplete work without marking assumptions as done.

## Delivery checks

- [ ] Every implementation has appropriate synthetic checks through scripts/test.sh, shell syntax checks where applicable, and a reviewable PR.
- [ ] Link every created or pushed PR to its thread. Keep dependent work in an explicit stack.
- [ ] Final reconciliation against this checklist and all user screenshots. No deployment.
