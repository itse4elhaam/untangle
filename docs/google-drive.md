# Google Drive setup and recovery

Setup is optional. Opening Untangle, installation, sign-in, uploads and scheduling
are separate user actions. The in-app **Google Drive setup and recovery…** button
opens this guide even when Drive fails.

## Prerequisites

Follow [Linux support/preflight](https://github.com/itse4elhaam/untangle/blob/main/docs/linux-support.md): x86-64 Linux, Python 3.10+,
OBS 27 on X11 or OBS 30–33 on X11/Wayland. Drive also needs internet, a Google
account and local browser; background scheduling needs a systemd user session.
Install/update the reviewed checkout only with explicit authorization via
`./scripts/install.sh`. This supplies Google libraries without enabling archiving.
Check a missing user bus with `systemctl --user status`; use a normal logged-in
session or ask the administrator, rather than enabling lingering/system services.

The optional `./scripts/setup-drive-wizard.sh` opens Google pages and pauses at
manual steps; Ctrl-C/rerun supports recovery. It never installs, signs in, launches,
uploads, schedules or deletes. Package hints assume Debian/Ubuntu; use Linux
support and preflight for platform-specific requirements and version checks.

Wizard progress stores only project ID/client path in
`~/.local/state/glint/drive-setup/progress.env`, directory/file modes 700/600.
Never paste secrets, JSON, tokens or callbacks into its prompts, use `bash -x`,
or record a credential-setup terminal session.

## Project, consent and Desktop client

In [Google Cloud](https://console.cloud.google.com/projectcreate), create/select a
project and enable the [Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com).
In **Google Auth platform**, configure Branding/support/contact details and Audience.
Personal accounts use External; Internal requires the project's organization.
Add the exact signing-in account under **Audience > Test users**. Register
`https://www.googleapis.com/auth/drive` under **Data Access**. Full Drive access
allows browsing existing folders; review it before consenting.

Under **Clients > Create Client**, choose **Desktop app**, create and download JSON.
A Web client, API key or service account cannot substitute. For a lost download,
manage/create a replacement Desktop client. Keep it outside repositories/shared
or synced folders; restrict its directory to 700 and file to 600:

```bash
mkdir -p "$HOME/.config/untangle-private"
chmod 700 "$HOME/.config/untangle-private"
# Move the download here with your file manager first.
chmod 600 "$HOME/.config/untangle-private/desktop-client.json"
```

In an authorized app session choose **Recordings > Google Drive… > Set up Google
OAuth client…**. Import replaces the client and forgets local sign-in; keep the
client for token-only recovery. Private copies live at
`~/.local/share/glint/google-drive/client.json` and `token.json`, modes 700/600.

External Testing grants for this scope expire after seven days. Publishing needs
separate review; Production does not guarantee permanent tokens, and Workspace
policy may block consent. Google UI/policy guidance was retained without external
revalidation in this audit. Consult [consent setup](https://developers.google.com/workspace/guides/configure-oauth-consent),
[Desktop quickstart](https://developers.google.com/workspace/drive/api/quickstart/python),
[audience rules](https://support.google.com/cloud/answer/15549945) and
[token expiry](https://developers.google.com/identity/protocols/oauth2).

## Sign in, destination and scheduling

Choose **Sign in with Google**, review consent with the test-user account and keep
the dialog open. The OAuth callback listens on `127.0.0.1` at a random port with
a three-minute timeout. Sign-in needs internet; offline access allows later token
refresh. The browser must be local, not on another SSH machine.

Create/select a writable folder in [My Drive](https://drive.google.com/drive/my-drive).
**Load Drive folders**, check account/permissions and distinguish duplicate names
by IDs; My Drive means root. Start with an owned folder; Shared Drive policies/listing
may differ. Save the destination and optional **Archive automatically in the
background** setting. Saving never enables a timer. Manual **Upload selected to
Google Drive…** works with background archiving off.

Only after separately authorizing background uploads:

```bash
./scripts/setup-archive.sh
systemctl --user status untangle-archive.timer
systemctl --user cat untangle-archive.service
```

This immediately enables the timer, using this checkout's `src` and installed
runtime. Keep the checkout; review/rerun after moving it. It starts after five
minutes, repeats 15 minutes after service completion, defers while Untangle is
open and requires two unchanged observations at least five minutes apart.
It never captures or deletes.

## Verification and deletion

With upload authorization, use an existing disposable video. Remote IDs persist
before transfer; retries retain their original destination. Check Drive before
retrying uncertainty. Size/checksum verification starts retention; inspect private
`archive-uploads.json` locally for `verified_at`, never share its contents.
Service success alone does not prove upload; individual errors are quiet to
protect OAuth details.

**Do not upload to Google Drive** blocks manual/background uploads and follows
renames/edits; **Allow Google Drive uploads** clears it. Copies/exports are new
recordings. Unreadable policy blocks uploads. Existing remote copies/in-progress
transfers remain unchanged.

Manual local deletion requires confirmation but no sign-in, connectivity or remote
check. Cancel keeps files; busy/symlink/changed files are protected. Remote copies
remain. After the seven-day period from verified upload, **Review archived recordings…** offers cleanup.
Archive cleanup checks a current matching remote copy before and after confirmation;
offline/uncertain checks block it. Never alter real timestamps to test retention.
See [delete_paths](https://github.com/itse4elhaam/untangle/blob/main/src/untangle/recordings.py),
[test_unarchived_recordings_can_be_deleted_after_confirmation](https://github.com/itse4elhaam/untangle/blob/main/tests/test_discard_cleanup.py),
and [archive checks](https://github.com/itse4elhaam/untangle/blob/main/src/untangle/archive.py). Loom availability does not itself
prove processing completion when the CLI omits that field; see [Loom constraints](https://github.com/itse4elhaam/untangle/blob/main/docs/loom-integration.md).

## Recovery, disabling and revocation

- Expired/revoked token or `invalid_grant`: stop scheduling below, check test users/
  policy and sign in again. Normal access-token refresh is automatic; expired
  refresh grants need consent.
- Missing/invalid client or redirect error: check API/project, import Desktop JSON
  and sign in. Do not edit callbacks or substitute a Web client.
- Denied consent: check exact test-user account; ask the Workspace administrator
  about restrictions. Review warnings against your own project/permissions.
- Timeout: let the action finish, check local browser, loopback/firewall and default
  browser, then retry. Offline/quota/permissions: restore network/storage/access,
  reload folders and keep local files until verified.
- No background upload: check saved opt-in/destination, timer, checkout/runtime,
  closed app and two observations. Reinstall/reschedule only with separate authorization.

Stop both future and active scheduled uploads:

```bash
systemctl --user disable --now untangle-archive.timer
systemctl --user stop untangle-archive.service
```

Uncheck automatic archiving and save. **Forget Google sign-in on this computer**
removes only the local token, not the timer, client or history. Revoke remote access
at [Google Account connections](https://myaccount.google.com/connections).
For full credential removal, stop timer/service, close Untangle, remove private
`client.json`, `token.json`, original download and wizard `progress.env` using the
file manager. Preserve `archive-uploads.json` unless deliberately surrendering
history/retry IDs. Nothing here deletes remote videos.

Implementation owners: [DriveClient](https://github.com/itse4elhaam/untangle/blob/main/src/untangle/drive.py),
[Drive dialog](https://github.com/itse4elhaam/untangle/blob/main/src/untangle/drive_dialog.py), [Drive policy](https://github.com/itse4elhaam/untangle/blob/main/src/untangle/drive_policy.py),
[archive scheduler](https://github.com/itse4elhaam/untangle/blob/main/scripts/setup-archive.sh). Regression owners:
[test_drive.py](https://github.com/itse4elhaam/untangle/blob/main/tests/test_drive.py), [test_archive.py](https://github.com/itse4elhaam/untangle/blob/main/tests/test_archive.py),
[test_drive_help.py](https://github.com/itse4elhaam/untangle/blob/main/tests/test_drive_help.py). Use [the safe runner](https://github.com/itse4elhaam/untangle/blob/main/docs/testing.md).
