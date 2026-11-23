# Google Drive setup and recovery

Setup is optional. Untangle uploads to Drive with [rclone](https://rclone.org/drive/),
through a Google Drive remote you configure yourself. Untangle never runs
`rclone config`, signs in or stores Google credentials. Opening Untangle, uploads
and scheduling are separate user actions. The in-app **Google Drive setup and
recovery…** button opens this guide even when Drive fails.

## Set up a remote

Install rclone (`sudo apt install rclone` or [rclone.org/install](https://rclone.org/install/)),
then run `rclone config` in a terminal: **n** for a new remote, a name such as
`gdrive`, storage type **drive**, full-access scope and auto config. Sign in with
the account that should hold the recordings. Check it with `rclone lsd gdrive:`.

The optional `./scripts/setup-drive-wizard.sh` walks through these steps and the
ones below. It never installs, signs in, launches, uploads, schedules or deletes.

## Choose a remote and destination

Open **Recordings > Google Drive…** and choose **Load Drive folders**. Untangle
uses the remote shown in the dialog, else `UNTANGLE_DRIVE_REMOTE`, else the
first `drive` remote from `rclone listremotes --long` (preferring names starting
with `gdrive`), the same discovery the [review tool](https://github.com/itse4elhaam/untangle/blob/main/docs/review.md) uses. **Find rclone
remotes** lists every Drive remote. Folders are listed four levels deep and saved
by Drive folder ID; **My Drive** is the root. Untangle remembers the last remote
and a folder for each remote. A saved remote that is no longer configured shows
as *(unavailable)* and blocks upload until you pick another. Shared-with-me and
deeper folders are not listed, but a saved folder ID appears as **Saved destination**.
Earlier versions saved one folder without its remote; it is reused only when that
remote's listing contains it, otherwise choose the destination again.

Untangle remembers an unapplied checkbox change and marks it as awaiting Save.
Save the destination and the optional **Archive automatically in the background**
setting. Saving never enables a timer. Manual **Upload selected to Google Drive…**
works with background archiving off. **Cancel current action** stops rclone.

Only after separately authorizing background uploads:

```bash
./scripts/setup-archive.sh
systemctl --user status untangle-archive.timer
```

The timer starts after five minutes, repeats 15 minutes after each run, defers
while Untangle is open and uploads only files unchanged across two runs at least
five minutes apart. It never captures or deletes. An encrypted `rclone.conf`
cannot be unlocked by the timer, so it skips the run. Background runs log to
`~/.local/state/glint/archive/diagnostics.jsonl` (exception types only).

## Verification and deletion

Each upload is recorded before transfer, then copied with `rclone copyto
--immutable`, which refuses to replace a different file of the same name.
A copy counts as uploaded only when the Drive file, matched by its ID, has the
local size and MD5. Retries keep the original destination. A failed or cancelled
upload is reported as unconfirmed; check Drive before retrying.

**Do not upload to Google Drive** blocks manual and background uploads and follows
renames and edits. Unreadable exclusions block uploads.

Manual local deletion needs confirmation but no remote check. After the seven-day
period from verified upload, **Review archived recordings…** offers cleanup, which
checks for a current matching Drive or Loom copy before and after confirmation.
Offline or uncertain checks block it. See [archive checks](https://github.com/itse4elhaam/untangle/blob/main/src/untangle/archive.py)
and [Loom constraints](https://github.com/itse4elhaam/untangle/blob/main/docs/loom-integration.md).

## Recovery, disabling and revocation

- rclone missing or no Drive remote: the dialog says so; follow **Set up a remote**.
- Expired or revoked sign-in: `rclone config reconnect gdrive:`, then retry.
- Offline, quota or permission errors: restore access, reload folders and keep
  local files until verified.
- No background upload: check the saved opt-in and remote, the timer, a closed app
  and two observations.

Stop future and active scheduled uploads:

```bash
systemctl --user disable --now untangle-archive.timer
systemctl --user stop untangle-archive.service
```

Earlier Untangle versions signed in with their own Google OAuth client. Its
`client.json` and `token.json` in `~/.local/share/glint/google-drive` are no
longer used and are never removed automatically. Saved folders and upload history
keep working. To remove them, close Untangle and delete those two files, the
originally downloaded Desktop client JSON and `~/.local/state/glint/drive-setup/progress.env`
with the file manager, then revoke the old project at [Google Account connections](https://myaccount.google.com/connections).
Keep `archive-uploads.json`; it holds verification history. Nothing here deletes
remote videos.

Owners: [DriveClient](https://github.com/itse4elhaam/untangle/blob/main/src/untangle/drive.py), [rclone runner](https://github.com/itse4elhaam/untangle/blob/main/src/untangle/rclone.py),
[Drive dialog](https://github.com/itse4elhaam/untangle/blob/main/src/untangle/drive_dialog.py), [archive](https://github.com/itse4elhaam/untangle/blob/main/src/untangle/archive.py);
tests in [test_drive.py](https://github.com/itse4elhaam/untangle/blob/main/tests/test_drive.py) and [test_archive.py](https://github.com/itse4elhaam/untangle/blob/main/tests/test_archive.py).
