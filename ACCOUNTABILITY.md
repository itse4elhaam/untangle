# Historical accountability limits, 4 November 2026

This preserves evidence that cannot be reconstructed from current code. It is not a live backlog, deployment record, or standing authorization.

The original request batch covered archive retention, row actions, camera ranking, collapsed details, audio-check relocation, per-mode crop/zoom, resizing, a repeatable Drive guide, and UX follow-through. [PR #29](https://github.com/itse4elhaam/untangle/pull/29) preserves the integrated implementation and verification record, including its dependency ancestry. The retired TODO checklist and repeated test-count updates are replaced by that record.

## Evidence that remains limited

- The original storage answer reported 18 recordings and 11.0 GB logical size. Physical allocation was uncertain; this audit did not inspect personal recordings to repeat the measurement.
- Several requests referred to screenshots using "this" or "these". The accountability reader received an image reference without pixels. Source/test reconciliation therefore did not establish exact agreement with the original screenshot targets.
- Camera ranking uses advertised colour resolution usable at 30 fps, then frame rate. It is a capability proxy, not an optical-quality measurement. The original native resize scenario was skipped because Xvfb was unavailable. Later isolated input checks do not retroactively verify that historical run.
- Synthetic UI and mocked services did not establish real microphone intelligibility, encoded crop/resize pixels, OAuth/permissions, scheduler operation, or end-to-end uploads. Current verification procedures and remaining limits belong in [testing](docs/testing.md), rather than this historical record.
- The eleven UX proposals were subsequently authorized. Earlier pending-approval statements in the original audit were superseded. Authorization to merge/install applied to that batch only; reported installation was not independently verified by accountability.

[PR #31](https://github.com/itse4elhaam/untangle/pull/31) later changed manual deletion to require confirmation without a remote copy. Archive cleanup retained its seven-day eligibility and fresh remote verification. Earlier blanket remote-copy policy must not be used as current guidance.
