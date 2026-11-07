# Theo Browne: UI hill climbing

Research note, 2026-11-06. Scope: identify the recent video and assess whether its approach transfers to automated UX iteration for Untangle, a Linux Qt recording app. No application launch or device access was performed.

## Video identification

**Agents Sucked At UI (Until Today)**, Theo - t3.gg, published **November 3, 2026**, runtime about 31:44. Official YouTube URL: https://www.youtube.com/watch?v=xq0eB8vxeqk . Search results and third-party catalog metadata identify this as the episode about using a model review council and hill climbing. I could not retrieve an official channel page or a transcript from YouTube in this research pass. Therefore the date/title/URL are metadata cross-checked against search-indexed catalog results, not first-hand viewing. The date is also rendered in a non-Gregorian form by one catalog; November 3 is corroborated by another index.

## What is supported about the method

The indexed synopsis says Theo iteratively prompted Opus and hill-climbed its UI output, with multiple models scoring screenshots. An indexed topic summary places the UI hill-climb discussion around 6:57 and mentions iterative visual changes, but that is a secondary summary, not a verified transcript. Do **not** treat those times or details as transcript-verified. No exact prompt, scoring rubric, acceptance rule, or timestamped step can be stated from primary transcript evidence here.

**Inference:** this is a generate → render → solicit visual critique → revise loop. A model score is a noisy proxy for user experience; repeated optimization against the same judges can overfit their preferences.

## Primary-source references for practical loops

- Qt Test documents GUI testing with simulated mouse and keyboard input: https://doc.qt.io/qt-6/qtest-overview.html . This is directly relevant to exercising Qt widgets and interactions; it does not itself define a design-quality metric.
- Qt's QTest API documents key-event simulation: https://doc.qt.io/qt-6/qtest.html .
- Playwright's visual comparison docs explain screenshot baselines and review/update of references: https://playwright.dev/docs/test-snapshots . This is browser-focused, so only the baseline discipline transfers directly to Qt.
- Playwright accessibility guidance recommends combining automated checks with manual assessment and inclusive user testing: https://playwright.dev/docs/accessibility-testing . The exact browser tooling does not transfer, but the limitation of automation does.
- GUIrilla research proposes systematic exploration through native accessibility APIs and a manually verified benchmark: https://arxiv.org/abs/2510.16051 . This is research evidence for structured desktop exploration, not proof of an off-the-shelf Qt workflow.

## Assessment for Untangle

- **Gaming:** High risk if the same model council, prompts, and screenshots both propose and judge every iteration. Scores can reward superficial polish, regressions hidden outside the screenshot, and judge-specific conventions. Keep a held-out set of screens/states and compare with stable criteria; periodically use human review.
- **Blind A/B:** Useful for reducing anchoring when comparing candidate screenshots, but not sufficient. Blind comparisons still inherit the evaluator's taste and can miss usability, discoverability, and workflow failures. Include task success and interaction checks.
- **Fixed scenarios:** Necessary for reproducibility (same window size, theme, scale factor, seeded library data, and UI state), but a narrow fixed suite can be gamed. Add varied states: empty library, populated library, long names, errors, loading, keyboard navigation, and constrained window sizes.
- **Functional safety:** Treat visual optimization as gated by functional invariants. Run the repository's isolated test runner and synthetic/mocked UI checks; never use live capture devices as an optimization loop. Preserve cleanup and no-device boundaries. A prettier screenshot cannot compensate for broken recording controls or resource leaks.
- **Stop/budget rules:** Set a fixed iteration/token/time budget before the loop; accept a change only when it improves the visual rubric without failing functional gates or held-out scenarios. Stop on plateau, judge disagreement, regression, or budget exhaustion. Do not chase a 10/10 consensus as an absolute stopping rule.

These recommendations are an application of the cited testing capabilities and common experimental-design reasoning, not a claim that Theo used these safeguards. Repository instructions prohibit opening the app without authorization and prohibit live device tests; this note respects those constraints.

## Source confidence

Video identity and date: medium confidence, metadata sources only. Video method: low-to-medium confidence, indexed secondary summaries; exact transcript and timestamps unavailable. Qt testing capabilities: high confidence, official Qt documentation. Screenshot baseline and accessibility-loop caveats: high confidence for Playwright's documented browser practice, transfer to native Qt is inference. GUIrilla: research abstract only; inspect the paper/code before adopting details.
