# Automatic local recording titles

Untangle extracts a short audio sample and transcribes it locally with whisper.cpp, then sends only transcript text to Codex CLI. Video and audio are not uploaded for naming. Codex uses existing authentication, so the complete flow is not offline. Automatic naming is opt-in.

The helper never renames files, changes recording identity or uploads. The caller owns those actions and any subsequent upload must use the resulting recording identity.

## Prerequisites

Supply `ffmpeg` and `codex` on PATH, `whisper-cli` or `whisper-cpp`, and an existing local ggml model. The helper also checks `~/.local/bin/whisper-cli`. The default model is `~/.local/share/whisper.cpp/models/ggml-base.en.bin`, for English. Set `UNTANGLE_WHISPER_MODEL` for another compatible model. A missing explicit path fails rather than selecting another model.

`local_title_capability()` checks command locations and model-file metadata only. It does not run processes, inspect authentication, validate model contents or prove account/model access. Starting a job checks required CLI options asynchronously. Nothing installs software, downloads a model or starts sign-in.

The original 2026-10-23 inspection found local prerequisites, including Codex CLI 0.163.0; authentication and Luna access were deliberately not checked. This is historical evidence, not current machine readiness. Existing whisper.cpp was chosen instead of adding a Python transcription dependency. An unrelated Python `whisper` import was not evidence of a working transcriber.

## Lifecycle contract

Use `LocalTitleJob` on the Qt main thread with its event loop running. Connect `finished` before `start(Path(video))`, and retain the job until completion. Start returns immediately; even prerequisite failures arrive on a later event-loop turn. Each job is single-use; a second start raises `RuntimeError`.

`finished(title, error)` fires once per started job under ordinary completion:

- A title with an empty error goes through the caller's naming/identity flow and skips manual prompting.
- An empty title with an error returns to manual naming, including missing prerequisites, insufficient speech, invalid output, model/access failure, timeout or cancellation.

Cancel is idempotent and a no-op before start. It kills the current process group and completes asynchronously after Qt reaps it. Cancellation before queued work starts launches no process. The caller must ignore shutdown cancellation and guard against stale recording identity.

Deleting the job or parent stops work and removes temporary files without promising a completion signal. Ordinary completion/cancellation never waits on the UI thread. Destruction alone may wait up to one second after killing a running process group. Standalone Codex execution avoids leaving a request in a shared daemon.

## Privacy and request limits

The sample uses the first audio stream and at most its first 120 seconds, so later topics may be missed. Temporary audio and request artifacts are private and removed on completion, failure, cancellation or destruction. Process diagnostics are discarded because they may contain transcript or account data.

Requests pin `gpt-6-luna`, medium reasoning and the **default service tier**. There is no retry with another model or tier. Transcript text travels as JSON-quoted stdin, never in command arguments; recording paths are excluded from Codex arguments. User configuration and project instructions are excluded, while existing authentication remains in use. Read-only, ephemeral execution disables tools and treats transcript instructions as untrusted data. Reported tool actions, execution failures, incomplete turns or model substitutions reject the result.

Stages have deadlines and bounded output. Generic or malformed titles fall back to manual naming; syntax checks cannot establish factual accuracy. Exact limits, subprocess arguments and validation live in [local_titles.py](../src/untangle/local_titles.py).

Historical reference checks used the [CLI reference](https://developers.openai.com/codex/cli/reference/), [configuration reference](https://developers.openai.com/codex/config-reference/), [schema](https://developers.openai.com/codex/config-schema.json) and [Luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna). Those checks recorded medium reasoning support and legacy fast-to-priority mapping, not account access. They are not a current vendor verification or the configured tier.

## Safe focused verification

```bash
UNTANGLE_TEST_PATTERN=test_local_titles.py ./scripts/test.sh
```

[Synthetic tests](../tests/test_local_titles.py) cover cancellation, cleanup, bounds and request isolation without inference, transcription, private recordings, capture or authentication. Passing them does not prove Codex account access.
