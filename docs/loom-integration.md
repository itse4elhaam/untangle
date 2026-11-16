# Loom integration constraints

Original inspection: 2026-10-23, official Atlassian sources and installed
`~/.local/share/glint/twg` help/static code only. No account probe, login, logout,
upload or capture ran. External/installed-CLI observations below were not
revalidated in the 2026-11-09 documentation audit.

## CLI evidence and uncertainty

[loom.py](../src/untangle/loom.py) owns arguments, capability detection and parsers;
[app.py](../src/untangle/app.py) runs nonblocking QProcess operations after user
actions. [test_loom.py](../tests/test_loom.py) and
[test_loom_workflow.py](../tests/test_loom_workflow.py) own payload/workflow coverage.
Use JSON stdout with summaries disabled; see the
[output reference](https://github.com/atlassian/twg-cli/blob/main/skills/twg/references/OUTPUT.md)
and [command catalog](https://developer.atlassian.com/cloud/twg-cli/commands/commands-catalog/).

`whoami` establishes Atlassian identity, not Loom membership, upload entitlement
or AI settings. `logout` revokes OAuth and removes the selected TWG profile,
affecting other products on that profile; no Loom-only disconnect was found.

Probe upload/rename help rather than assuming flags. The inspected uploader used
a positional file, lacked upload visibility, and preserved the original extension
even with a title override. The app therefore corrects differing titles after
publication and applies sharing separately when needed. Failed rename/sharing
must retain the link and warning. See the [changelog](https://developer.atlassian.com/cloud/twg-cli/changelog/)
for publication-success/visibility-failure exit code 3.

The inspected CLI had no intermediate JSON transfer-progress contract. A final
byte count cannot become invented progress. Local `upload.phase` durations include
CLI processing waits, cannot isolate network throughput or Loom processing, and
establish no speed improvement. Timings exclude filenames, links and output.

New uploads default to Anyone with the link. Saved private/workspace choices
still apply; changing the preference does not alter existing Loom videos.

Video-get did not request deletion flags or `isComplete`. Null/404, private/forbidden, archived and network failures cannot
prove deletion. Keep links. Only explicit deletion evidence permits
`UploadStore.mark_remote_deleted`; the synthetic future `DELETED` payload is not
a claim that today's CLI emits it. Never probe destructively.

## Auto titles

The inspected [Loom guidance](https://support.atlassian.com/loom/docs/how-auto-titles-summaries-and-chapters-work/)
said every plan could use auto titles with speech/transcript and at least 30 seconds
of video; editing first could prevent generation. Imported-video support remained
unresolved in [LOOM-21](https://jira.atlassian.com/browse/LOOM-21).
The CLI normally supplies the filename even without an override. Preserve returned
titles and promise no AI output.

**Let Loom generate titles when available** is off by default and omits explicit
titling/rename. It cannot verify or enable a remote setting. No supported public
CLI reads/enables auto titles; the changelog hid `loom settings get` because its
field was internal-only. Do not invent properties or use undocumented APIs.
Prior guidance pointed to video **Settings > Set Defaults > Enhancements/Loom AI**,
with admin policy at [Workspace Settings](https://www.loom.com/settings/workspace).

## Metadata ownership

One app-owned [UploadStore](../src/untangle/upload_store.py) serves library and
upload controller at explicit `STATE / 'uploads.json'`. It mutates metadata only,
never videos/Loom. Atomic private writes preserve unreadable/malformed/unsupported
files and expose errors; failed reads must not erase links.

Records bind to device, inode, size and modification time. Missing folders never
prune history. Transfer completion must still match the original identity before
attaching metadata or copying links, including after sharing. Rename metadata only
after successful local rename; remove it after manual local deletion or explicit Forget.
Verified-upload cleanup ([loom_cleanup.py](../src/untangle/loom_cleanup.py)) instead
marks the row `local_copy: deleted` before unlinking and keeps it, so the link survives
the file. If the marker cannot be saved the file is kept; if the unlink fails the marker
is reverted. Loom offers no checksum. Cleanup needs a fresh video-get of the same
video that is playable and whose `playableDuration` matches the local ffprobe duration
within 1 s or 1%. The installed CLI (checked 16 November 2026) omits `isComplete` from
video-get but returns `playableDuration`; an explicit `isComplete: false` still blocks.
Unplayable results retry for about 20 minutes, then keep the file.
Interrupted uploading/processing becomes uncertain with known links retained:
check Loom before retrying to avoid duplicates. See
[test_upload_store.py](../tests/test_upload_store.py) and
[synthetic UI evidence/limits](loom-ui/README.md).
