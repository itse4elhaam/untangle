# Autonomous native Qt UX hill-climbing loop: feasibility

## Recommendation

Untangle already has most of the safe execution substrate for a bounded autonomous UX loop: synthetic Qt fixtures, real production widgets, real Qt input, actual-window screenshots, a bubblewrap test runner, and written visual acceptance rules. The missing pieces are a task/score contract, a controlled patch-and-compare harness, explicit artifact provenance for all scenes, and a review gate that prevents an automated score from authorizing merge. Start with low-risk hypotheses in spacing, labels, focus, and discoverability, not recording or device behavior.

A practical loop is: (1) select one measurable task and baseline scene; (2) generate a candidate patch on a branch; (3) run safe tests and screenshots under isolation; (4) compute hard acceptance metrics and compare image diffs; (5) reject regressions or retain a candidate; (6) open/update a PR with source diff, task score, before/after actual Qt captures, test output, and mock disclosures; (7) require human visual/product review before merge. Iteration can be autonomous within a small patch/iteration budget, but PR review remains the stopping boundary.

## Existing capabilities

- `scripts/test.sh` fails closed without `bwrap`; it runs with private `/dev`, `/run`, `/tmp`, no network, read-only host view, offscreen Qt, and clears display and hardware opt-ins. It sets `UNTANGLE_SYNTHETIC_SANDBOX=1`.
- `tests/test_ui_clickthrough.py` builds the production `untangle.app` widgets with mocked OBS/device/audio boundaries and sends real `QTest` mouse/keyboard input. Existing measurable checks cover control visibility/enabled state, text fit, overlap, geometry at 960×760 and 1120×840, themes, modes, focus traversal, countdown escape, audio-check return, silent selection then explicit playback, and state locking.
- `scripts/render-ui.py` drives that fixture and captures complete real Qt windows. Only the native preview is replaced with a software-painted synthetic scene; synthetic local files/preferences and mocked multimedia are used. It emits PNGs and a manifest with hashes, dimensions and disclosures. Related renderers (`render-settings-ui.py`, `render-loom-ui.py`, `render-naming-ui.py`) extend coverage to more real dialogs and flows.
- `docs/ui-standards.md` establishes the Clearline interaction contract, a release gate, capture sizes/themes, and that screenshots need human visual review and are not pixel-hash tests.
- `docs/testing.md` explains isolation and the limits of synthetic/device tests; it specifically distinguishes private-X11 overlay interaction from offscreen Qt and native capture.
- `docs/ui-baselines/` contains broad screenshot scenarios and an HTML index/manifest. UX review/audit materials exist in `docs/ux-audit-2026-11-04.md`, `docs/ux-review.html`, `docs/ux-review-images/`, `docs/ux-follow-through-images/`, and `docs/research/ux-comparison-apps.md`.

## Gaps for a repeatable optimization loop

1. **No canonical objective function.** Current assertions are useful binary invariants, but there is no versioned catalog mapping user task → starting state → action sequence → completion condition → score/penalty. Scores must not reward compactness if it harms legibility or hide useful controls.
2. **Screenshot pipeline is evidence generation, not candidate comparison.** The renderer emits images and hashes but has no stable region-aware visual delta report or automatic baseline/candidate gallery tied to a PR. Raw pixel thresholds would be brittle across font/Qt updates.
3. **Scenario coverage is split.** Main clickthrough, renderer, Settings, Loom and naming renderers each have setup assumptions. A loop needs one discoverable scenario registry and explicit coverage tags, including failure/long-name states.
4. **Private Xvfb is not the default UX path.** `scripts/test.sh` forces offscreen Qt and removes `RECIT_TEST_XVFB`; docs describe a separate private X server test for overlay input. Thus native window-manager/X11 behavior needs a separate safe lane, not silently mixed into ordinary optimization.
5. **No PR automation contract found.** Repository instructions require PRs and version/push before deploy, but the reviewed materials do not define an autonomous UX PR bot, iteration cap, score report, or merge policy. Verify CI workflow files before implementation; this report did not establish whether external CI configuration exists.
6. **Audit findings require reconciliation.** The Nov 4 audit records current-state limitations, parallel-stream work, and capture caveats. Treat it as dated evidence, not a live backlog. Re-render current production UI before selecting candidate targets.

## Proposed task and score format

Keep tasks deterministic and user-centered, e.g. “switch to camera, identify selected microphone and reach Record without scrolling” or “find a saved take and play it only after explicit action.” Each task definition should name a fixture, setup script, supported sizes/themes/modes, action sequence, completion signal, hard constraints, and evidence outputs.

Use a gated score, not one scalar alone:

- **Hard gates:** all existing safe tests pass; zero primary-control overlaps/clipping; required controls reachable/visible; no new scrolling; stable window bounds; no unsafe boundary invoked.
- **Task outcome:** completed/not completed, action count, and whether the intended state is unambiguous from visible text/state.
- **Visual review features:** component bounds and spacing changes, image-diff heatmap, and full-window captures. Image similarity is diagnostic only; do not optimize toward pixel equality.
- **Complexity budget:** restrict edits to an allowlist of UI/source files and a small diff/iteration budget; abort on changes to capture, audio, networking, persistence, or safety boundaries unless separately requested.

Candidate improvement hypotheses (validate against current captures before changing): (a) reduce redundant recorder helper text while preserving explicit mode/device context; (b) improve hierarchy between setup controls and preview; (c) make the primary recording action and recovery status easier to scan at minimum size; (d) standardize long-device-name treatment and tooltips; (e) make audio-check return/input-change actions more discoverable. These are hypotheses from `docs/ui-standards.md` and the audit, not verified defects.

## Safe execution architecture

Run ordinary Qt tasks under the existing bubblewrap policy with synthetic devices and temporary settings/media. For flows whose correctness depends on native X11 pointer routing or stacking, run a separate private Xvfb lane using the existing `RECIT_TEST_XVFB` capability described in `docs/testing.md`; never inherit host `DISPLAY`/Wayland or hardware opt-ins. Screenshots should come from the actual production widget tree. Reuse existing fixture construction and renderer hooks rather than creating a second mock app. Add an explicit scenario manifest recording patched classes, synthetic inputs, capture dimensions, Qt/PySide versions, and environment isolation. Keep artifacts temporary for iteration; attach only selected evidence to the PR.

CI is feasible if its Linux image supplies Python dependencies, `bwrap`, Xvfb where needed, and compatible Qt plugins/software GLX for the subset that exercises native X11/OBS compositing. Separate the inexpensive offscreen deterministic lane from the slower Xvfb lane. Do not make CI depend on a physical camera, microphone, Bluetooth, host desktop, live service account, uploads, or audio output. If namespace creation is unavailable, fail closed as the current runner does.

## What mocks cannot prove

Synthetic devices and mocks cannot establish camera/microphone enumeration quality, Bluetooth profile selection or microphone intelligibility, actual OBS rendering/encoded pixels, real media decode stability or audible playback, desktop compositor/window-manager stacking beyond the private server tested, Wayland behavior, user preference migration across installed state, network/service permissions, upload success, or performance under real workloads. Offscreen screenshots also cannot prove native desktop rendering fidelity. They establish deterministic layout, widget state, and interaction against the mocked boundaries only. Any such claim needs separately authorized hardware/service acceptance.

## Actionable first increment

1. Re-render current recorder/library/settings/failure scenes and reconcile the output with the Nov 4 audit.
2. Add a small task catalog for 3–5 high-frequency flows, reusing `ClearlineClickthrough` actions and assertions.
3. Make renderer outputs include task IDs, source revision, environment versions and mock-boundary disclosure in a PR-friendly summary.
4. Add a candidate/baseline gallery and region-aware diff as review aids; retain human inspection and existing geometry/text assertions as the authority.
5. Run on a dedicated PR branch, produce a single bounded candidate PR with before/after captures and safe-suite evidence, and require maintainer approval. Do not auto-merge or deploy.
