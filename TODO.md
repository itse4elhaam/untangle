# Untangle requested work

Do not deploy, install, activate timers, upload recordings, or launch the app without explicit authorization. Use only low, medium, or high reasoning for delegated work. Preserve the repository's device, speech, and safe-test safeguards.

## Delivered for review

- [x] Automatic Google Drive archiving, configurable destination, verified uploads, seven-day retention, in-app confirmation, and no deletion without a current Drive or Loom copy. PR #18 merged. Accountability reports installation separately authorized in another thread; verify that thread before asserting installed state. No deployment is authorized for the current batch.
- [x] Rename and delete icons beside individual recordings, retaining existing safety checks. PR #19; not deployed.

## Implemented for review

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

- [x] Every implementation has appropriate synthetic checks through scripts/test.sh, shell syntax checks where applicable, and a reviewable PR.
- [x] Link every created or pushed PR to its thread. Keep dependent work in an explicit stack.
- [x] Final source/test reconciliation against this checklist and screenshot targets. Independent accountability found no missing implementation item. Current pixels and native/live-service acceptance remain unverified; no deployment.

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
- [x] Integrate UX polish with other completed workstreams and verify the combined head. Current pixels remain unverified; older synthetic screenshots do not establish current layout acceptance.
- [x] User authorized implementation of the eleven larger proposals on 4 November 2026, superseding the earlier pending decision. Historical proposal text follows: User decision on the eleven larger proposals in docs/ux-audit-2026-11-04.md (PR #21). None is approved or implemented by this report. Priorities include explaining deletion requirements before confirmation, showing actual archive scheduler status, Review saved recording, current library layout verification, capture/audio preflight summary, sharing/storage overview, operation-specific Drive feedback, audience visibility beside copying, shortcut discoverability, and future editor/separate-track architecture.
- Cancellation correction: Cancel upload already exists; only its discoverability from the library is proposed.

## Drive wizard integration

- PR #23, head a44526aa0063bf4d7d624604af56250c4c1b93c8, delivered ten-stage repeatable wizard, full local setup/recovery guide, and Settings/Drive guide buttons.
- Root merged it locally with UX/resize. Delegate full suite lacked PySide6; root therefore reruns using the project environment.
- Root found and fixed a keyboard regression: guide buttons must not become default dialog actions when Enter commits a combo. All 8 Settings UI tests pass after setting autoDefault false. Root also changed the wizard shebang to /bin/bash per AGENTS.md; template helpers remain unchanged.
- Full combined suite passed after this fix; see final evidence below. No wizard execution, OAuth, installation, timer activation, uploads, or live setup verification.

## Framing integration

- PR #25, dc03de17d1864c5e62b3a8c5d16718dd98639abb: independent camera/screen zoom and offsets, legacy preference migration, Settings drag pad/sliders/reset, explicit live-preview crop editing, and bounded mirror-aware source crop geometry. Root merged locally with size-only resize API intact.
- Root fixed lost-release crop dragging and disabled autoDefault on Center image. Five framing interaction tests and eight Settings UI tests pass after those fixes; shell syntax/diff checks pass. Full combined verification passed; see final evidence below.
- Camera sensor/output and native X11 event delivery remain unverified; no app/device launch or deployment. Crop pad is schematic; real image feedback uses the existing recorder/bubble preview.

## Complete implementation assembled for verification

- PR #24, 3ab5cc164e6cd03eae0f87b681726b0bffb402c4, merged locally: collapsed-by-default recorder details, important feedback kept visible, Quick audio check in Settings, redundant setup heading/mode hint removed. New notice(detail=False), engine_notice(detail=False), and set_details_visible interfaces combine with framing and guide additions without conflicts.
- All implementation streams are now assembled in draft PR #26. Checked implementation items mean delivered code for review, not installation or native hardware acceptance.
- The earlier combined partial test run was superseded before merging #24, so source would not change during a run. Full suite now runs on the complete integrated source at /tmp/untangle-final-integrated.log. High-effort integration review passed without actionable findings; final accountability reconciliation is requested with the evidence below.

## Final root verification

- Complete implementation source at 7550d2d7b24bedf38341b1153b57c23355eda8a3 (draft PR #26) includes all user-authorized workstreams. `./scripts/test.sh` exited 0: 625 tests in 73.762s, OK with 3 skips. `bash -n scripts/*.sh bin/*` and `git diff --check` passed.
- A new independent GPT-6.1 Sol high static integration review of that head returned no actionable findings. It did not run tests or inspect the root test log; its conclusion is limited to source review.
- Screenshot targets are reconciled to implemented controls: row action icons; camera-quality default; lower Recording details disclosure; Quick audio check in Settings; floating camera boundary resize; mode-specific Zoom; removed setup heading/mode helper; Settings camera-image-position crop pad/sliders/live-drag toggle. Related interaction, migration, geometry and keyboard checks pass in the synthetic suite.
- Current actual app pixels, native X11 mouse/camera output, optical camera quality and live Google OAuth/scheduling/upload remain unverified. Advertised resolution/frame rate are the camera quality proxy. Native Xvfb scenario is skipped because Xvfb is unavailable. No safety restriction was bypassed.
- No current-batch installation, runtime update, launch, OAuth, uploads or timer activation. PRs remain reviewable; no remote PR merge performed. Larger UX proposals remain unapproved/unimplemented. Independent final accountability confirmed source/synthetic delivery complete for review with no missing implementation items. Its evidence and explicit acceptance limits are preserved in ACCOUNTABILITY.md.

## PR #26 base update and screenshot follow-up

- [x] Merge updated feat/recorder-setup at e904206911cecb5fdc7a4797ad8f0e50d09d470f into feat/recorder-improvements, retaining both audit text and the incoming screenshot follow-up. No runtime source conflict or discarded feature.
- [x] Re-run isolated safe suite: 625 tests in 74.078s, 3 skipped; Python compile of 30 sources and shell syntax pass.
- [x] Add newly rendered light/dark screenshots, source/PNG hashes and limitations in docs/pr26-ui; embed key views in the PR. Prior current-pixel limitations above describe earlier verification; these captures now provide inspected synthetic Qt layout evidence only. Native/hardware/live-service limits remain.
- The user subsequently authorized all eleven UX proposals in the dedicated Complete Untangle UX follow-through thread. Earlier entries saying unapproved are historical and superseded. That separate thread owns implementation and conclude-thread; PR #26 does not claim those new features.


## Authorized UX follow-through, 4 November 2026

The new focused request supersedes earlier unapproved/unimplemented and no-install statements for this batch. Conclude-thread authorizes merge and local installation after pushed versioned changes pass safe checks. No live capture, speech, authentication, uploads or timer activation is authorized.

- [x] 1. Library active transfer navigates to recorder cancellation controls. Existing confirmation and uncertain outcomes retained. `test_recordings_loom.py`.
- [x] 2. Remote-copy prerequisite and safe Archive selected action precede deletion consent. Fresh final remote and file-identity checks retained; offline/missing/changed/partial cases covered in `test_recordings_loom.py`.
- [x] 3. Drive separately shows destination saved, archive enabled, explicit read-only scheduler observation and historical verified upload. `test_archive_status.py`, `test_drive_dialog.py`; guide retained.
- [x] 4. Review saved recording selects final named file, stays silent until Play, follows later rename, handles missing/deleted files. Existing naming/error/discard suites plus `test_ux_follow_through.py`.
- [x] 5. Current 960x760 library clipping repaired with separate archive/action rows and reserved status line. Four fresh long-title uploaded/error captures in `docs/ux-follow-through-images/`, source hashes recorded. Synthetic geometry checks pass.
- [x] 6. Countdown includes target/camera/microphone/desktop-audio summary and honest readiness text. Existing Escape/readiness paths preserved; `test_ux_follow_through.py` plus countdown/audio suites.
- [x] 7. Settings opens shared local/archive/sharing overview linking Drive and Loom, independent credentials explained, TWG-wide sign-out warning retained. `test_app.py`, `test_drive_dialog.py`.
- [x] 8. Operation-specific Drive progress, per-file success/unconfirmed outcomes and destination. Partial success retained, duplicate warning and manual-retention limits explicit. `test_drive.py`, `test_drive_dialog.py`.
- [x] 9. Audience and command-verification status beside both Copy Loom link locations. Unverified copy remains possible with explicit warning; title/permission failures separate. Retry clears verification. `test_ux_follow_through.py`, existing Loom workflow tests.
- [x] 10. Read-only Settings shortcut list and right-click/resize bubble discovery. Existing registration detects conflicts and reports tray fallback; no remapping needed or changed. `test_ux_follow_through.py` and existing shortcut coverage.
- [x] 11. Safe source/track schema and versioned-export design in `docs/editing-projects.md`; working accurate trim editor preserves source and versions. Existing composed video/mixed audio explicitly baked; future independent capture/layout needs schema extension, no false separate-source capture claim. Ten `test_editing.py` checks cover actual synthetic export, cancellation, disk-full, recovery, locks and dialog cleanup.

Integrated safe runner: 648 tests in 80.678s, OK with 3 skips. Shell syntax and diff checks passed. All capture/service/native limits remain. Local lifecycle recorded below after delivery.


Final integration includes main 8e9cfcd recording quality/optional camera compression. Isolated full suite passed **652 tests in 82.432s, 3 skips**. Final Drive-worker shutdown guard then passed all five focused follow-through tests through the same runner. Export quit waits for cancellation cleanup; Drive quit waits for its bounded operation. Shell syntax and diff checks pass. PR #29 is the merge-preserving main rollup containing #19/#20/#23/#24/#25/#26 ancestry. User-authorized local delivery uses an immutable git-archive release and the existing installer after merge, with no app launch. Actual merge/install result will be recorded in PR and final handoff rather than claimed in advance here.
