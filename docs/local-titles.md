# Automatic local recording titles

`untangle.local_titles` extracts a short audio sample locally, transcribes it
with whisper.cpp, and sends only the transcript text to Codex CLI for a title.
It does not upload the video or audio. Title generation uses the Codex service
and existing Codex authentication, so the complete flow is **not offline**.
The helper never renames files, changes recording identity, or uploads anything.

## UI contract

```python
from pathlib import Path
from .local_titles import LocalTitleJob, local_title_capability

available, reason = local_title_capability()
job = LocalTitleJob(parent)
job.finished.connect(on_title_finished)
job.start(Path(video))
# Wire "Skip automatic title" to job.cancel.
```

Call the helper on the Qt main thread with its event loop running. Keep a
reference to the job until completion. `start` returns immediately and defers
even prerequisite failures until the next event-loop turn. Each job is
single-use; calling `start` twice raises `RuntimeError`.

The `finished(str title, str error)` signal fires once per started job:

- `(title, '')`: apply the title through the parent's existing naming and
  identity flow, then skip the manual prompt. Any subsequent upload belongs to
  the parent and must use its resulting recording identity.
- `('', error)`: show the existing manual prompt. This includes unavailable
  prerequisites, unsupported CLI options, transcription failure, insufficient
  speech, invalid/generic output, model/access failure, timeout, and cancellation.

`cancel()` is idempotent. Before `start`, it is a no-op. After `start`, it kills
the current process group and completes asynchronously when Qt reaps the helper.
Cancelling before the queued work begins starts no process. The parent should
ignore cancellation during shutdown and guard against stale recording identity.
Deleting the job or its parent kills remaining work and removes temporary files;
destruction does not promise a completion signal.

Ordinary completion and cancellation never wait for a process on the UI thread.
Only destruction of a still-running job uses a final wait of at most one second
after killing its process group. The explicit standalone Codex invocation avoids
leaving a request running in a shared daemon.

## Local prerequisites

`local_title_capability()` returns `(True, '')` when local prerequisites exist,
or `(False, actionable_reason)` otherwise. It only checks command locations and
model-file metadata. It does not run a process, read authentication files, make
an API call, validate model contents, or prove Codex account/model access.
`start` verifies Codex execution options asynchronously before extracting audio.

Inspection on 2026-10-23 found all supported prerequisites on this machine:

| Requirement | Installed location |
| --- | --- |
| ffmpeg | `/usr/bin/ffmpeg` |
| whisper.cpp CLI | `~/.local/bin/whisper-cli` |
| Existing English model | `~/.local/share/whisper.cpp/models/ggml-base.en.bin` |
| Codex CLI 0.163.0 | `~/.nvm/versions/node/v24.15.0/bin/codex` |

The default capability here is therefore available, provided ffmpeg and Codex
are on the app's `PATH`. The helper also checks `~/.local/bin/whisper-cli` when
it is absent from `PATH`. No missing prerequisite was found for this supported
path. Authentication and Luna access have deliberately not been checked.

The app's Python environment has neither `whisper` nor `faster_whisper` nor
PyTorch installed. The system Python has an unrelated `whisper` import without
PyTorch; this is not evidence of a working OpenAI Whisper transcriber. The
implementation uses the existing whisper.cpp executable instead of adding a
Python dependency or alternate backend.

On another machine, supply `ffmpeg` and `codex` on `PATH`, plus `whisper-cli` or
`whisper-cpp`, and an existing local ggml model. Set `UNTANGLE_WHISPER_MODEL` to
the model file to override the default path. An explicit missing model path fails
instead of choosing another model. This helper never installs software,
downloads models, or starts an authentication flow. The default `.en` model
transcribes English; another compatible model can be selected explicitly.

## Limits and request isolation

Audio extraction uses the first audio stream and at most the first **120
seconds**, converted to mono 16 kHz signed 16-bit PCM in a private temporary
directory. The ffmpeg protocol whitelist permits local files and pipes only;
`-nostdin` prevents interactive input. The sample can miss a topic introduced
later in the recording. Failure or an insufficient sample returns to manual
naming.

The per-stage deadlines are 10 seconds for CLI help, 30 seconds for extraction,
90 seconds for transcription, and 45 seconds for Codex. Each process runs in a
new Linux session so cancellation also kills descendants, including the native
Codex binary launched by its JavaScript wrapper. Combined stdout/stderr is
limited to 256 KiB per stage. Transcript and title-file reads are limited to
24,000 and 4,096 bytes. Temporary audio, transcript, instructions, schema, and
response files are removed on completion, failure, cancellation, and destruction.
Diagnostics are discarded rather than logged or displayed because they can
contain transcript or account data.

The installed CLI's `--help` verifies noninteractive execution, stdin prompts,
`--ignore-user-config`, `--strict-config`, `--ephemeral`, `--output-schema`,
`--output-last-message`, and read-only sandboxing. The title request pins:

```text
codex --no-daemon exec --ignore-user-config --strict-config --ephemeral
  --skip-git-repo-check --sandbox read-only --model gpt-6-luna
  -c model_reasoning_effort="medium" -c service_tier="priority"
  ... --json --output-schema SCHEMA --output-last-message RESULT -
```

These are individual process arguments, not a shell command. The transcript is
JSON-quoted and passed on stdin; recording paths and transcript text never
appear in Codex arguments. The working directory contains only temporary job
artifacts. User configuration and project instructions are excluded; existing
Codex authentication remains in use. Shell execution, unified execution,
plugins/hooks, browser/computer use, apps, image tools, memory tools, agent
delegation, and web search are disabled. The prompt explicitly forbids tools
and treats all transcript instructions as untrusted data. A reported tool action,
execution error, incomplete turn, or reported model substitution rejects the
result. Read-only sandboxing remains in effect even if the model ignores the
prompt.

The helper never retries with another model or service tier. It requires a
structured title with 3-10 words and at most 80 characters and rejects empty,
generic, multiline, malformed, or unsafe output. Factual accuracy still depends
on transcription and generation; syntax validation cannot prove a title's
meaning.

Official OpenAI references checked alongside the installed CLI:

- [CLI execution options](https://developers.openai.com/codex/cli/reference/).
- [Configuration reference](https://developers.openai.com/codex/config-reference/)
  documents reasoning effort and that legacy `fast` maps to request tier
  `priority`; the [configuration schema](https://developers.openai.com/codex/config-schema.json)
  also accepts explicit `priority`.
- [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) supports
  medium reasoning. These sources do not prove access for this account.

## Safe focused verification

```bash
env -u DISPLAY -u WAYLAND_DISPLAY -u RECIT_TEST_MIC_HARDWARE \
  -u RECIT_HARDWARE_PRIVATE_DISPLAY -u RECIT_NATIVE_PRIVATE_DISPLAY \
  -u RECIT_TEST_XVFB PYTHONPATH=src QT_QPA_PLATFORM=offscreen \
  .venv/bin/python -m unittest discover -s tests -p test_local_titles.py -v
```

Tests use synthetic files and inert Qt processes. They cover the success and
fallback contracts, cancellation, timeout, parent destruction, process groups,
temporary cleanup, CLI arguments, output bounds, and title/event validation.
They never run Codex inference, transcribe audio, inspect private recordings,
capture devices, or authenticate.
