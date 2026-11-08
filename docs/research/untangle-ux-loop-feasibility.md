# UX loop feasibility, historical assessment

Assessment date: 6 November 2026. This records design reasoning, not a current capability inventory. The later [overhaul evidence](../ux-overhaul/README.md) documents the implemented tools. [UI standards](../ui-standards.md) owns current acceptance policy; the original suggestion that every visual review must be human was superseded for the approved UX scope.

## Why a bounded loop

A screenshot score is a noisy proxy for usability. Reusing the same judges and scenes can reward their preferences while hiding failures elsewhere. Compare a specific task against a frozen baseline, retain the last accepted candidate, and reject any visual improvement that breaks behavior. Raw pixel equality is brittle across Qt/font versions.

The proposed evidence contract separates:

- Hard invariants: required tests, reachable actions, readable text, stable bounds, cleanup, and no unsafe boundary calls.
- Task outcomes: completion, wrong turns, action count, and visible state. Synthetic waiting time is a regression measure, not evidence of human speed.
- Visual judgment: anonymous complete-window comparisons with fixed references, fresh reviewers, and explicit disagreement.
- Coverage: reserved names, failures, sizes, themes, and keyboard paths that the builder did not use for tuning.

Use one builder at a time and a small coherent change. Keep tests and comparator references outside the builder's allowed edits. Changes in mixed UI/business-logic files need diff-level review; a filename allowlist cannot protect recording behavior by itself.

## Execution and stopping constraints

The controller stays outside the device/network sandbox. The Qt fixture runs inside it with synthetic media and bounded actions on the main thread. Reuse production widgets and existing fixture construction instead of building a second mock app. Unknown actions or targets outside the fixture must fail.

Current entry points are `scripts/test.sh`, `scripts/render-safe.sh`, and `scripts/ux_session.py`. The safe runner discovers its own private-Xvfb lane when prerequisites exist. Do not pass host display or hardware opt-ins, and do not bypass isolation when namespaces are unavailable. Missing native prerequisites block claims about that lane even if other tests pass.

The synthesized pilot budget was six rounds or two hours after setup, stopping earlier after two rounds without gain, repeated reviewer disagreement, missing required evidence, or usage exhaustion. These are pilot limits, not a recurring schedule or permission to change providers. Keep rejected rounds outside the repository; deliver selected evidence in the owning PR.

## Evidence limits

At assessment time, a common task catalog, candidate comparison, and controlled observation/action interface were proposed gaps. Later scripts may satisfy parts of them; inspect current source before proposing the same work again. No CI environment or unattended service was established by this assessment.

Offscreen layouts cannot certify native stacking, live Wayland/OBS output, Bluetooth speech quality, sustained encoding, service permissions, or real uploads. Those need separately authorized acceptance. A model preference is neither user research nor merge/deployment authority.
