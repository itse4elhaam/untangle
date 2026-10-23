# Loom CLI integration

Checked 23 October 2026 against official Atlassian sources and the installed
`~/.local/share/glint/twg` help. Only help and static CLI code were inspected.
No account probe, login, logout, upload, remote mutation, or capture was run.

## Commands and payloads

Use `-o json --output-summary none` to receive JSON directly on stdout, with
stderr kept separate. This disables file-backed agent summaries, as described
in Atlassian's [output reference](https://github.com/atlassian/twg-cli/blob/main/skills/twg/references/OUTPUT.md).
Run these commands through nonblocking QProcess only after the relevant user
action. The helpers in `untangle.loom` never execute commands.

* Account identity: `twg whoami -o json --output-summary none`. Help describes
  `data.accountId`, `data.name`, and `data.email`. A successful response proves
  Atlassian identity, not Loom membership, upload entitlement, or AI settings.
  `parse_account_status` returns `connected`, `disconnected`, or `unknown`;
  `auto_titles_entitled` and `auto_titles_enabled` remain `None`.
* Disconnect: `twg logout -o json --output-summary none`. This revokes OAuth and
  removes the selected TWG login profile and its credentials, affecting other
  products using that profile. No Loom-only disconnect command was found.
* Inspect a saved video: `twg loom video get <id-or-url> -o json --output-summary none`.
  `parse_video_info` returns `available`, `deleted`, or `unknown`, plus `url`,
  `title`, `remote_id`, `visibility`, and `is_complete`. The installed single-video response
  uses `data.id`, `data.name`, and `data.url`; `name` becomes the stored title.
  It does not request `isComplete`; `is_complete` remains `None` unless an
  actual boolean is returned. A successful get cannot establish processing
  completion when that field is absent.
* Upload: `twg loom video upload <absolute-file> -o json --output-summary none`.
  Probe `--help` first. The installed CLI uses a positional file and has no
  `--visibility`. Apply `twg loom video visibility set <id-or-url> --visibility owner|workspace|public -o json --output-summary none`
  separately. Newer releases can advertise visibility on upload. The
  [official changelog](https://developer.atlassian.com/cloud/twg-cli/changelog/)
  also documents exit code 3 when publication succeeds but visibility fails.
* Manual title edit, when explicitly requested: probe `loom video rename --help`,
  then `twg loom video rename <id-or-url> --title <title> -o json --output-summary none`.
  `rename_title_args` and `upload_args` require advertised title options before
  using them. `supports_option` matches option declarations exactly.

These operations are listed in the official [command catalog](https://developer.atlassian.com/cloud/twg-cli/commands/commands-catalog/).
The installed upload response contains `data.video`, including `id`, `name`,
`url`, `isComplete`, and `isArchived`, plus a final `data.transfer` byte count.
`parse_upload_result` returns `uploaded`, `processing`, `uncertain`, or `failed`.
It preserves a known remote link on partial failure so retry cannot silently
create a duplicate. It never extracts URLs from arbitrary error messages.

The installed CLI does not wire intermediate transfer callbacks to stdout,
and no public JSON upload-progress event contract was found. Show an
indeterminate indicator. `parse_upload_progress` accepts labeled human
uploading/processing lines and an actual percentage if present; a final
`transfer.bytes` count never becomes invented progress.

## Remote deletion

The inspected video-get query does not request deletion flags. Null results,
404/not-found errors, forbidden/private responses, archived videos, and network
failures cannot prove deletion. Keep the existing link and report `unknown`.
The parser accepts an explicit future `data.status: "DELETED"` with a video ID
as deletion evidence; the synthetic test is not a claim that the current CLI
emits it. Only confirmed deletion may call `UploadStore.mark_remote_deleted`.
No destructive probe is appropriate.

## Auto titles

Loom says auto titles are available on every plan and need a transcript with
speech and at least 30 seconds of video. Editing the title before generation
can prevent it. Therefore the default upload path omits `--title`, including
filename-derived titles. See [Loom's auto-title guidance](https://support.atlassian.com/loom/docs/how-auto-titles-summaries-and-chapters-work/).

This does **not** establish auto-title support for imported Untangle videos.
Atlassian's [request to apply AI features to uploaded videos](https://jira.atlassian.com/browse/LOOM-21)
is still unresolved. The CLI normally supplies the source filename when no
override is given. Preserve Loom's returned title and avoid promising AI output.

There is no supported public CLI to read or enable auto titles. The changelog
says `loom settings get` is hidden because its backing field is internal-only.
Do not invent JSON properties or call undocumented settings APIs. A local
preference to accept Loom titles cannot verify or enable a remote setting.

Loom's guidance directs users to a video's **Settings > Set Defaults**, then
**Enhancements** or **Loom AI**, depending on their plan. Workspace admins can
manage workspace-wide AI policy at [Workspace Settings](https://www.loom.com/settings/workspace).

## Local metadata

`UploadStore(STATE / 'uploads.json')` owns an explicit metadata file. `get`,
`update`, `remove`, `rename`, and `mark_remote_deleted` never mutate videos or
Loom. Writes use a private temporary file and atomic replacement; unreadable,
malformed, or unsupported metadata remains untouched and exposes `store.error`.
Mutations raise `OSError` when the original cannot be read safely.

Records bind to device, inode, size, and modification time. Replaced or modified
files do not inherit a previous link. Missing folders never trigger pruning.
Call `rename(old, new)` after a successful local rename and `remove(path)` after
local deletion or an explicit Forget action. Constructor recovery changes
`uploading` and `processing` to `uncertain`, retaining any known remote metadata.
One app-owned store instance should serve both the library and upload controller.

Uploads snapshot the source identity before starting. Completion must still
match that identity before attaching metadata or copying a link, including
after a separate sharing-permissions command. A local file replaced during
transfer must never inherit the original video's remote link.

See [UI evidence and safe reproduction](loom-ui/README.md) for synthetic
screenshots, render commands, and the remaining live-validation limits.
