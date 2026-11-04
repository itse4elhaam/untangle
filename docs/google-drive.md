# Google Drive setup and recovery

Run the repeatable interactive guide from this checkout:

```bash
./scripts/setup-drive-wizard.sh
```

It checks prerequisites and walks you through each manual stage. It opens relevant
Google pages and waits for confirmation. It does not install, launch Untangle,
sign in, upload, run a scheduler command, or delete recordings. Stop with Ctrl-C
and rerun to review or recover an existing setup. No setup is required to read this
page. In the app, **Settings > Google Drive setup and recovery…** and the same
button in **Recordings > Google Drive…** open this local guide.

The stages cover prerequisites, project/API, consent, Desktop client download,
private local configuration, browser sign-in, destination, opt-in settings,
scheduling, and verification/recovery. Only project ID and the hidden-entered
client file path are remembered in `~/.local/state/glint/drive-setup/progress.env`,
with directory mode 700 and file mode 600. This is wizard progress, not app
configuration. Never paste client secrets, JSON, tokens or browser callback URLs
into the terminal. Do not run with `bash -x` or record a terminal session.

## Prerequisites and missing tools

You need x86-64 Linux/X11, the supported OBS 27 libraries/plugins, Python 3.10+,
a Google account, internet, a local browser and a systemd user session.
Nothing below runs automatically. Approve installation separately before using
these commands. On Debian/Ubuntu, the next manual package steps are:

```bash
sudo apt update
sudo apt install python3 python3-venv ffmpeg v4l-utils pulseaudio-utils systemd xdg-utils
```

These supply `python3`, `ffmpeg`, `v4l2-ctl`, `pactl`, `systemctl` and `xdg-open`.
If `busctl` is absent, install your distribution's `systemd` package. If OBS is
missing, check `apt-cache policy obs-studio` first. Install `obs-studio` only if
the candidate is the supported version 27 with its plugins. If the distribution
ships another version, stop and arrange the supported runtime rather than
silently replacing OBS. Other distributions need their equivalent packages.

For missing `uv`, follow the [official uv installation instructions](https://docs.astral.sh/uv/getting-started/installation/).
One manual option, if `pipx` is already installed, is `pipx install uv`; restart
or update your shell's PATH before rerunning the wizard. Install a local browser
through your distribution if none exists, and configure its normal default-browser
association if `xdg-open` fails. Google account setup starts at
[Google Accounts](https://accounts.google.com/).

After approving installation of the reviewed checkout, run:

```bash
./scripts/install.sh
```

It installs the Python requirements, including the Google client libraries, into
`~/.local/share/glint/venv` and updates launchers. It does not activate archiving.
If imports are missing, rerun this installer only after approving that update.
A working systemd session can be checked manually with `systemctl --user status`.
If it reports no user bus, use a normal logged-in desktop session or ask your
system administrator; do not enable lingering or a system-wide service for this.

## Project, API and consent

Use the [Google Cloud project page](https://console.cloud.google.com/projectcreate)
to create a project, or select an existing project. Record its project ID in the
wizard. In the selected project, open the
[Drive API library page](https://console.cloud.google.com/apis/library/drive.googleapis.com)
and enable the API.

In **Google Auth platform > Branding**, use **Get Started** if configuration is
new. Enter an app name and support email, choose the audience, supply contact
information, review Google's policy, and create the configuration. Use External
for a personal account. Internal is for members of the project's Google Cloud
organization. Under **Audience > Test users > Add users**, add the exact account
that will sign in and save. In **Data Access > Add or Remove Scopes**, register
`https://www.googleapis.com/auth/drive` and save. These paths follow Google's
[consent configuration guide](https://developers.google.com/workspace/guides/configure-oauth-consent).

Untangle currently requests full Drive access so it can browse existing folders
and upload to your chosen destination. Review that permission before consenting.
External projects in Testing have seven-day authorization and refresh-token
expiry for this scope. For sustained use, review publishing and verification
requirements under Audience before making a separate publishing decision.
Production status does not guarantee a permanent token. Workspace administrator
policy can also block access. See Google's
[audience rules](https://support.google.com/cloud/answer/15549945) and
[token expiry guidance](https://developers.google.com/identity/protocols/oauth2).

## Desktop client and private files

In **Google Auth platform > Clients > Create Client**, choose **Desktop app**, name
it and create it. Download the JSON at creation and keep it private. A web client,
API key or service account does not replace this file. For a lost download,
manage or create a replacement Desktop client in the same project. Follow
[Google's Drive quickstart](https://developers.google.com/workspace/drive/api/quickstart/python)
and [client management instructions](https://support.google.com/cloud/answer/15549257).

Keep the JSON outside the repository and shared/synced directories. For example,
create a private directory, use the file manager to move the download into it as
`desktop-client.json`, then restrict it:

```bash
mkdir -p "$HOME/.config/untangle-private"
chmod 700 "$HOME/.config/untangle-private"
# Move the downloaded file here with your file manager before the next command.
chmod 600 "$HOME/.config/untangle-private/desktop-client.json"
```

In a separately authorized Untangle session, open **Recordings > Google Drive… >
Set up Google OAuth client…** and select that file. Importing replaces the current
client and forgets the old local sign-in. Keep the current client when recovering
only an expired token. The app copies client configuration to
`~/.local/share/glint/google-drive/client.json`; browser credentials go to
`token.json` in that directory. The app sets directory mode 700 and file mode 600.
Do not commit these files, put contents on command lines, or include them in logs.
The wizard stores only the selected source path, never credential contents.

## Sign in and choose a destination

Choose **Sign in with Google**, use your test-user account and review consent in
the browser. Untangle requests offline access and listens on `127.0.0.1` using a
random local port. Complete the flow within three minutes and keep the dialog
open. This uses a local browser on the same computer, not a remote SSH login.
If blocked, use recovery below rather than repeatedly retrying.

Create or select a writable folder in [My Drive](https://drive.google.com/drive/my-drive).
Choose **Load Drive folders** in Untangle, then the destination. Folder IDs beside
names distinguish duplicates; **My Drive** means the root. Start with a folder
owned by this account. Shared Drive listing and organization policies may differ.
For a missing folder, check the account and permissions, then reload.

For automatic archiving, check **Archive automatically in the background** and
choose **Save archive destination and settings**. Leave it unchecked for manual
uploads. Settings are stored privately in `archive.json`; the last folder is also
remembered in the existing app preferences. Saving does not enable a timer.
Changing the destination affects future uploads. An upload already assigned a
remote ID retains its original destination.

## Explicit background scheduling

Only after installing the reviewed version and separately approving background
uploads, run this from the checkout you intend to keep:

```bash
./scripts/setup-archive.sh
systemctl --user status untangle-archive.timer
systemctl --user cat untangle-archive.service
```

The script immediately enables the user timer. The service uses this checkout's
`src` and the installed private Python runtime, so keep the checkout in place.
After moving or updating the chosen checkout, review and rerun the scheduler
script explicitly to refresh its path. It starts after five minutes and runs
again 15 minutes after the preceding service finishes while your user session
runs. It defers while Untangle is open. It observes a file unchanged across two
runs at least five minutes apart. It never captures devices or deletes files.
It uses a saved remote ID so an interrupted archive can retry without a second
copy. Offline or inaccessible destinations leave local files intact.

## Verify only when uploads are authorized

Use an existing disposable, non-sensitive video, not a new live capture. Manual
uploads start from **Upload selected to Google Drive…** in the library. Load the
folders, choose the destination and confirm the upload. Manual uploads work even
when background archiving is off. Both manual and automatic uploads save the
remote ID before transfer and verify Drive size/checksum before starting retention.
Retries reuse that ID in its original folder, including after a partial failure.
Changing the chosen folder affects recordings that do not yet have a saved ID.
Check Drive before retrying an unconfirmed result.

To keep recordings off Drive, select them and choose **Do not upload to Google
Drive**. The row shows the exclusion, which blocks both manual and background
uploads and follows local renames and edits of the same file. Select them again
and choose **Allow Google Drive uploads** to clear it. Mixed selections are all
excluded when you choose Do not upload. Existing remote copies and transfers
already in progress are unchanged. A copied/exported file is a new recording
with its own upload choice. Unreadable exclusion settings block uploads.

Deletion normally requires a current verified remote copy. To delete without one,
check **Allow deletion without a backup**, then use the recording's delete button
or a bulk delete action. The confirmation warns that this may be the only copy
and defaults to Cancel. The checkbox resets after each attempt. Busy recordings,
symbolic links and files changed during confirmation remain protected. This
choice never enables automatic deletion.

For automatic verification, close Untangle and allow two timer runs. Check the
file in Drive and inspect the private local ledger without sharing its contents:

```bash
# Open locally in an editor; do not paste its contents into logs or support chats.
${EDITOR:-vi} "$HOME/.local/share/glint/google-drive/archive-uploads.json"
```

A row's `verified_at` records successful remote size/checksum verification.
Missing `verified_at` means retention has not begun. Check scheduling manually
with `systemctl --user list-timers untangle-archive.timer` and service status.
A successful service exit alone does not prove upload; individual failures are
intentionally quiet to keep OAuth details out of logs.

Seven days after a verified archive upload, the library offers cleanup.
**Review archived recordings…** opens the review again. Cancel must keep files.
Only confirm deletion for a disposable recording you intend to remove. Each
deletion requires a current matching, untrashed Drive copy or a completed Loom
copy whose saved metadata and remote existence checks pass. Offline or uncertain
checks block deletion. The timer never deletes. Do not change timestamps to
simulate this on real recordings; synthetic tests cover the seven-day boundary.

## Recovery, disabling and revocation

Rerun `./scripts/setup-drive-wizard.sh` for any missing prerequisite or lost setup.
The in-app setup/recovery button remains available during Drive failures.

- Expired or revoked token, or `invalid_grant`: stop scheduling below, check
  Audience/test users and policy, then **Sign in with Google** again. Testing
  grants expire after seven days. A short-lived access token normally refreshes
  automatically, but a revoked/expired refresh token requires consent again.
- No client/invalid client/redirect error: confirm this project's Drive API is
  enabled, download a Desktop client, import it and sign in again. Do not edit
  callback URLs or substitute a Web application client.
- Access denied: check the exact Google account is a test user. For organization
  restrictions or blocked consent, ask the Workspace administrator. Review any
  unverified-app warning against your own project and requested permissions.
- Browser timeout: wait for the action to finish, ensure the browser is local,
  check loopback/firewall policy and default browser, then retry sign-in.
- Offline, quota or permission failure: restore network, check Drive storage and
  writable destination permissions, reload folders and save the selection.
  Check Drive before manual retries. Keep local files until verification works.
- No background upload: check archive opt-in and destination are saved, timer is
  enabled, checkout/runtime paths still exist, and Untangle is closed. Allow two
  observations. Reinstall/reconfigure scheduling only with separate approval.

To disable future scheduled uploads and stop any current service:

```bash
systemctl --user disable --now untangle-archive.timer
systemctl --user stop untangle-archive.service
```

Disabling the timer alone may leave an active service running. In the Drive dialog,
uncheck automatic archiving and save. **Forget Google sign-in on this computer**
removes the local token only; it does not stop the timer, revoke remote permission,
remove the client JSON or delete upload history. Use
[Google Account connections](https://myaccount.google.com/connections) to remove
this project's access remotely. Reconnecting requires consent again.

For complete local credential removal, stop the timer/service, close Untangle,
then remove `client.json` and `token.json` in the private Drive directory and the
original download using your file manager. Remove the wizard's private
`progress.env` to forget its remembered paths. Preserve `archive-uploads.json`
unless intentionally giving up archive history and its deletion protection.
No step deletes remote recordings automatically.
