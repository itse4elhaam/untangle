# Untangle requested work

Do not deploy, install, activate timers, upload recordings, or launch the app without explicit authorization. Use only low, medium, or high reasoning for delegated work. Preserve the repository's device, speech, and safe-test safeguards.

## Delivered for review

- [x] Automatic Google Drive archiving, configurable destination, verified uploads, seven-day retention, in-app confirmation, and no deletion without a current Drive or Loom copy. PR #18 merged. Accountability reports installation separately authorized in another thread; verify that thread before asserting installed state. No deployment is authorized for the current batch.
- [x] Rename and delete icons beside individual recordings, retaining existing safety checks. PR #19; not deployed.

## Active implementation

- [x] Default to the highest-quality available camera. Rank advertised colour resolution at 30 fps, then frame rate; allow manual selection. Implementation committed in 76083e2; PR #20 is open. Root safe suite passed 609 tests, 3 skipped, in 69.161s. Not deployed in this batch.
- [x] Collapse the lower recorder status/details area shown in the screenshot behind a disclosure control; collapsed by default. Preserve important errors and recording state visibility.
- [x] Move Quick audio check from the primary setup pane to Settings, preserving its existing checks and cleanup behavior.
- [x] Keep camera framing/zoom preferences separate for camera-only and screen-plus-camera setups, including reload and mode switching.
- [x] Remove the redundant “Recording setup” heading and the “Screen + optional camera.” / equivalent mode helper text, preserving mode controls.
- [x] Add a Settings control to reposition the camera image inside its fixed shape, like moving an image within a crop. Preserve the shape position/size; persist framing per setup and test boundaries.
- [x] Provide a complete repeatable Google Drive setup guide using the wizard skill for every human prerequisite: Google project/API, OAuth consent/Desktop client, local configuration/sign-in, destination, background scheduling, verification, troubleshooting and disabling. Do not run the wizard or activate anything.

## Dedicated workstreams requested by user

- [x] Implement floating camera boundary resizing. Preserves square alpha shape, movement, screen bounds and window-capture composition; uses the 12–42% size range and blocks resizing during recording/countdown/preparation/saving. Synthetic interaction and composition checks pass through `scripts/test.sh` (612 tests, 3 skipped; Xvfb unavailable). Review branch `feat/camera-widget-resize`, stacked on `feat/recorder-setup`; not deployed.
- [x] Create a UX/UI audit thread using GPT-6.1 Sol at high. Audit the complete app against Loom and Supercut, implement only small changes with negligible risk, and propose the others to the user. No change has literally zero risk; keep device, capture, upload, auth, and deletion behavior out of automatic polish.
- [x] Create an independent accountability thread to check every item here, track evidence/PRs and omissions, and report incomplete work without marking assumptions as done.

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

## Drive wizard integration

- PR #23, head a44526aa0063bf4d7d624604af56250c4c1b93c8, delivered ten-stage repeatable wizard, full local setup/recovery guide, and Settings/Drive guide buttons.
- Root merged it locally with UX/resize. Delegate full suite lacked PySide6; root therefore reruns using the project environment.
- Root found and fixed a keyboard regression: guide buttons must not become default dialog actions when Enter commits a combo. All 8 Settings UI tests pass after setting autoDefault false. Root also changed the wizard shebang to /bin/bash per AGENTS.md; template helpers remain unchanged.
- Full combined suite is pending after that fix. No wizard execution, OAuth, installation, timer activation, uploads, or live setup verification.

## Framing integration

- PR #25, dc03de17d1864c5e62b3a8c5d16718dd98639abb: independent camera/screen zoom and offsets, legacy preference migration, Settings drag pad/sliders/reset, explicit live-preview crop editing, and bounded mirror-aware source crop geometry. Root merged locally with size-only resize API intact.
- Root fixed lost-release crop dragging and disabled autoDefault on Center image. Five framing interaction tests and eight Settings UI tests pass after those fixes; shell syntax/diff checks pass. Full combined verification is still pending.
- Camera sensor/output and native X11 event delivery remain unverified; no app/device launch or deployment. Crop pad is schematic; real image feedback uses the existing recorder/bubble preview.

## Complete implementation assembled for verification

- PR #24, 3ab5cc164e6cd03eae0f87b681726b0bffb402c4, merged locally: collapsed-by-default recorder details, important feedback kept visible, Quick audio check in Settings, redundant setup heading/mode hint removed. New notice(detail=False), engine_notice(detail=False), and set_details_visible interfaces combine with framing and guide additions without conflicts.
- All implementation streams are now assembled in draft PR #26. Checked implementation items mean delivered code for review, not installation or native hardware acceptance.
- The earlier combined partial test run was superseded before merging #24, so source would not change during a run. Full suite now runs on the complete integrated source at /tmp/untangle-final-integrated.log. Final high-effort integration review and accountability reconciliation remain pending.
