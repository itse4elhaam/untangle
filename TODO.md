# Untangle requested work

Do not deploy, install, activate timers, upload recordings, or launch the app without explicit authorization. Use only low, medium, or high reasoning for delegated work. Preserve the repository's device, speech, and safe-test safeguards.

## Delivered for review

- [x] Automatic Google Drive archiving, configurable destination, verified uploads, seven-day retention, in-app confirmation, and no deletion without a current Drive or Loom copy. PR #18 merged. Accountability reports installation separately authorized in another thread; verify that thread before asserting installed state. No deployment is authorized for the current batch.
- [x] Rename and delete icons beside individual recordings, retaining existing safety checks. PR #19; not deployed.

## Active implementation

- [x] Default to the highest-quality available camera. Rank advertised colour resolution at 30 fps, then frame rate; allow manual selection. Implementation committed in 76083e2; PR #20 is open. Root safe suite passed 609 tests, 3 skipped, in 69.161s. Not deployed in this batch.
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

## Coordination

- Root owns camera ranking/defaults only, plus integration and final reconciliation.
- UI setup delegate owns collapsed recorder details, Quick audio check relocation, and redundant heading/helper removal.
- Camera framing delegate owns separate camera/screen zoom preferences and Settings crop positioning.
- Drive wizard delegate owns repeatable human setup guidance and entry points.
- [Accountability thread](t3-thread://v1/mcp:db573d83-95fc-4f07-b994-2ffc3d8e5cec), medium.
- [Resize thread](t3-thread://v1/mcp:5cec8377-c5af-4f48-bdf9-fa5ee7988e65), high.
- [UX audit thread](t3-thread://v1/mcp:c254197a-aa4e-4bf7-a08e-1fb80a9c2612), low coordinator with explicitly requested high audit delegate.
- Resize interface: `CameraBubble.resized(float fraction)`; square alpha shape; size slider 12–42%; app updates existing framing API and normalized window-capture position. Resize idle-only; moving remains available during recording. No crop/zoom preference edits in resize stream.

## UX audit result received

- [x] High-effort GPT-6.1 Sol audit delivered for review in PR #21, head c3b6d6b9e3c8b7f5a76bdccbb3f7166d53172fca, based on feat/recorder-setup. Root inspected the diff and report; scope matches copy/tooltips/accessible names only. Delegate reports 609 safe tests passed, 3 skipped; no hosted checks/review decision reported.
- [ ] Integrate UX polish with other completed workstreams and verify the combined head. Current pixels remain unverified; older synthetic screenshots do not establish current layout acceptance.
- [ ] User decision on the eleven larger proposals in docs/ux-audit-2026-11-04.md (PR #21). None is approved or implemented by this report. Priorities include explaining deletion requirements before confirmation, showing actual archive scheduler status, Review saved recording, current library layout verification, capture/audio preflight summary, sharing/storage overview, operation-specific Drive feedback, audience visibility beside copying, shortcut discoverability, and future editor/separate-track architecture.
- Cancellation correction: Cancel upload already exists; only its discoverability from the library is proposed.
