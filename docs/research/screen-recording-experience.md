# Active screen recording experience: competitor research

Historical research. External claims retain their original dates and confidence limits; they were not reverified during documentation cleanup. Current contributor policy is in [AGENTS.md](../../AGENTS.md).

Research date: 2026-11-08. Sources below are official product documentation/changelogs. This is documentation evidence, not hands-on observation; UI details not explicitly documented are marked unknown. Scope is active capture and immediate review, not setup or library design.

## Findings

| Product/platform | During recording | Capture / output and handoff |
|---|---|---|
| Loom desktop (macOS guide) | Official macOS guide documents a hidden toolbar during recording, microphone waveform, and a camera bubble that can move, snap to edges and change size. | Stop leads to a recording preview and copy/share flow. This macOS guide does not establish Linux capture exclusion. |
| Cap Desktop (macOS, Windows, Linux) | The current Quickstart documents a countdown and controls to pause, resume, restart, and stop when available for that session. Configurable shortcuts cover pause/resume, restart, stop; shortcuts are empty by default. Recent release notes describe a recording bar and start-cue timing. Camera overlay positioning/resizing and timer details are not specified in the cited docs. | Studio saves a local editable project; stopping opens its editor, with source media retained and explicit export/share afterward. Instant uploads while recording and prepares a share page. Camera/source choice is explicit (display/window/area/camera only); system permissions differ by OS. Cap is available on macOS, Windows, and Linux. |
| Screen Studio (macOS only) | Small recording widget shows elapsed time and offers finish, pause, restart, delete. It can be hidden via right-click; docs say it does not appear in final recording on macOS 12.3+. Countdown and global start/stop shortcut are documented. | Stop opens editor. Changelog says recording controls were removed from recording output (2025), supporting clean output as a deliberate guarantee. Camera bubble control/resize/move behavior is not established by sources collected. |

## Platform and evidence limits

- Screen Studio is explicitly a macOS product; do not imply Windows/Linux support.
- Cap officially publishes macOS, Windows, and Linux desktop builds. Some capabilities vary with session/state; official docs qualify pause/resume/restart availability.
- Loom findings come from the current official macOS getting-started guide. Do not transfer macOS capture behavior to Linux.
- These are docs/changelog claims, not firsthand behavioral observation. A visible timer is explicitly documented for Screen Studio; Cap’s changelog mentions time-counter fixes, but the current Quickstart does not promise a visible timer.

## Transferable recommendations for Untangle

1. Put pause/resume, restart, and stop on a compact persistent recording control, with elapsed time visible. Ensure stop remains easy to reach without covering the captured content.
2. Offer a short, configurable countdown and a clear “capture has started” cue only once capture is ready; make the countdown cancellable.
3. Define visibility by capture path: separate controls can stay visible outside a selected X11 window; whole-screen or unknown portal captures show controls only while paused. Hide them before resuming. Untangle cannot inherit Screen Studio’s macOS exclusion guarantee. Opening the main window or tray during full-screen capture can still enter the recording.
4. Preserve existing camera dragging and fix reattachment position regressions. Keep resizing and capture-input changes locked during a take; broader live compositor changes need their own design and verification.
5. Show which display/window/area, camera, and microphone are currently active, plus actionable permission/device errors. Reconfirm source state when capture starts.
6. Stopping should immediately hand off to playback/review, with a clear choice to keep/edit/export/share; preserve an editable/source recording where feasible. Distinguish this from any upload path.
7. Design Linux behavior explicitly: Cap documents Linux support, while Screen Studio is Mac-only. Do not copy macOS-only permission or menu-bar assumptions into Untangle.

## Official sources

- Loom official macOS guide: https://support.atlassian.com/loom/docs/get-started-with-loom-for-macos/
- Cap Quickstart (countdown, capture source, controls, Instant vs Studio): https://cap.so/docs/quickstart
- Cap keyboard shortcuts (configurable stop/restart/pause-resume; none default): https://cap.so/docs/recording/keyboard-shortcuts
- Cap Studio Mode (local editable project, stop-to-editor, explicit share): https://cap.so/docs/recording/studio-mode
- Cap installation/platform support and permission distinctions: https://cap.so/docs/installation
- Cap current changelog (Oct 28 2026; recording bar, start-cue and platform notes): https://cap.so/changelog
- Screen Studio managing recording in progress (timer/widget/actions/hide): https://screen.studio/guide/managing-recording-in-progress
- Screen Studio starting and finishing (stop paths, shortcut, editor handoff): https://screen.studio/guide/starting-finishing-the-recording
- Screen Studio changelog (pause/resume, output control removal): https://screen.studio/changelog
- Screen Studio product page (countdown, pause/resume): https://screen.studio/

## This pass

- Compact native controller: elapsed time, fixed target, microphone input state, pause/resume, stop and confirmed restart/discard.
- Selected X11 window: controller may stay visible without being part of that window’s drawable.
- Whole display / portal: controller pauses first, hides before resume; no global exclusion promise.
- Stop reachability: keep Untangle visible unless a tray, confirmed stop shortcut or interactive camera bubble is available. Late shortcut failure restores a visible route when necessary.
- Existing encoding, audio processing, capture selection, save/recovery and upload consent remain unchanged. Input telemetry is not proof that saved speech is intelligible.

## Next hill-climbing loop

Use the same deterministic tasks for each candidate: start a selected-window take, keep typing/selecting in the target, pause, move controls, resume, stop, recover a failed stop, and review before sharing. Run safe unit/workflow checks and private-Xvfb native input checks. Capture production Qt steps with synthetic sources and explicitly label mocked encoding/audio/save events. Compare baseline/candidate evidence and have an independent agent reject regressions in Stop reachability, focus, capture locks or consent. Keep only improvements that pass; send one reviewable PR and one before/after video. Real hardware, portal/compositor and saved-audio quality remain separate opt-in verification, never a silent substitute for synthetic evidence.
