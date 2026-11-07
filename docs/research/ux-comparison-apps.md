# UI/UX benchmarks for Untangle

Verified 2026-11-06 from official product pages, docs, release notes, and demos. Product-site claims are labeled as claims; no competitor application was launched or independently usability-tested.

## Recommendations

### 1. Cap: two clear recording paths

Use Cap's Instant/Studio split as the strongest direct benchmark. Instant optimizes for immediate sharing; Studio saves a local project for editing/export. Cap describes screen/window/area and camera-only capture, mic and system audio, plus an editor; its current official demo explicitly shows the modes. This maps well to Untangle's optional Loom path while preserving local-first recording. Offer a simple “record and save” default and a distinct “record and share” action, with destination and upload state obvious.

Availability caveat: Cap's current official site advertises native macOS, Windows, and Linux. Linux downloads now list DEB, AppImage, Fedora/RPM, and Arch; installation docs still say release builds currently publish x86_64 DEB, so package availability documentation is inconsistent. Its own changelog reports Linux Wayland/X11 capture and separate mic/system audio as shipped in v0.6. Cap's free personal use and local recording are advertised; commercial use requires paid license, and cloud/team features are paid. Treat pricing as current page copy, not a stable benchmark.

### 2. Screen Studio: recovery and recording affordances

Borrow the small friction reducers: pause/resume, countdown, global shortcut, speaker notes, and crash recovery. These are particularly relevant to a recorder where a missed take is expensive. Screen Studio's official page advertises them as shipped features, alongside post-recording crop/edit controls. Its polished editing and cursor effects are less central to Untangle's core than a reliable capture-to-library handoff.

Availability and cost: macOS only (official download page says macOS 13.1+); not a Linux product benchmark for implementation. Its current pricing page lists $9/month annual or $29/month monthly, with export unavailable without an active plan. Treat this as a UX reference, not a platform or pricing target.

### 3. OBS: source clarity and resilient local capture

Benchmark OBS for explicit source composition, audio mixer visibility, and local recording control. Official feature material documents display/window/webcam and other sources, per-source audio filters, and scene switching. Its Linux support is real and officially documented, including Flatpak and Ubuntu paths. OBS is powerful but configuration-heavy; Untangle should expose the common screen/window/camera and mic/system-audio choices directly, reserving advanced controls for settings. Its “Quickstart” and Auto Configuration Wizard are useful examples of onboarding, though the interface itself is not a simplicity benchmark.

## Exclusions and limits

- **Loom:** useful reference for asynchronous sharing, but official security material says its desktop recorder runs on Windows and macOS. Browser capture is not equivalent to a native Linux recorder; exclude as platform benchmark. Do not infer current pricing or Linux availability from old marketing/security material.
- **Tella:** no sufficiently clear primary-source evidence found in this research pass for a current native Linux app and current shipped workflow. Exclude pending direct official verification.
- **Cap claims vs observed:** the Cap homepage contains an interactive “How Cap works” product demo, which demonstrates the marketed Instant/Studio workflow; this was not a live installed-app usability test. The official install docs and changelog are stronger evidence for platform/shipped status.
- Competitor pages are not evidence that their workflow is easier in practice. These recommendations are feature benchmarks inferred from the fit to Untangle's stated local library, recovery, and optional sharing workflow.

## Primary sources

- Cap homepage and interactive demo: https://cap.so/
- Cap downloads/platforms: https://cap.so/download and https://cap.so/download/versions
- Cap installation and Linux package caveat: https://cap.so/docs/installation
- Cap quickstart / modes: https://cap.so/docs/quickstart
- Cap release notes (native app and Linux shipped details): https://cap.so/changelog
- Cap v0.6 release: https://cap.so/blog/cap-v06
- Screen Studio feature page: https://screen.studio/
- Screen Studio download/platform and trial/export limitation: https://screen.studio/download
- OBS features: https://obsproject.com/
- OBS Linux installation: https://obsproject.com/kb/linux-installation
- OBS system requirements: https://obsproject.com/kb/system-requirements
- Loom desktop platform evidence (official SOC 3 report): https://cdn.loom.com/assets/marketing/security/loom-soc-3-report.pdf
