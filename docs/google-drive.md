# Google Drive uploads

Open the recordings library and select the recordings to upload. Click **Google Drive…**.

For the first connection:

1. In Google Cloud Console, create or select a project and enable the Google Drive API.
2. Configure the OAuth consent screen. If the application is in testing, add your Google account as a test user.
3. Create an OAuth client of type **Desktop app** and download its JSON file.
4. In Untangle, choose **Set up Google OAuth client…** and select that file.
5. Click **Sign in with Google** and finish consent in your browser.
6. Load folders, choose the destination, and click **Upload selected recordings**.

Untangle requests Drive access to list existing folders and upload to the folder you choose. Folder IDs are shown alongside names to distinguish duplicate names. The destination is remembered. Uploads are manual and resumable during the current operation; retrying a completed upload creates another copy. If an operation fails, check Drive before retrying because earlier files may have succeeded.

Client configuration and refresh credentials are stored under `~/.local/share/glint/google-drive` with private directory and file permissions. **Forget Google sign-in on this computer** removes the local token. Revoke access in your Google account to invalidate authorization remotely.

The Google libraries are installed through `requirements.txt`. No Google login or upload occurs during ordinary tests. Sign-in waits at most three minutes. Keep the dialog open until its current operation finishes.

## Automatic archiving

In the library, open **Google Drive…**, sign in, load folders, choose your destination,
and select **Archive automatically in the background**. Save the archive settings.
You can return here to change the destination or disable future uploads.

After installing the reviewed version of Untangle, explicitly run
`./scripts/setup-archive.sh` to schedule the uploader. It runs every 15 minutes while
your user session is running, even when Untangle is closed. It defers while Untangle
is open and observes each file unchanged across two runs before uploading it.
It never opens capture devices or deletes files. Disable scheduling with
`systemctl --user disable --now untangle-archive.timer`.

Uploads use a persisted Drive file ID so an interrupted job can retry without
creating another copy. A missing or inaccessible destination leaves local files intact.
Changing the destination affects future uploads; existing uploads stay in their original folder.

After seven days from a verified Drive upload, opening the library offers cleanup.
**Review archived recordings…** opens the same review again. Cancel keeps all copies.
Deletion requires confirmation and a current remote check. A Drive copy must have the
same size and checksum and must not be trashed. A completed Loom copy may also satisfy
the protection if its saved metadata matches the local file and Loom confirms it exists.
Offline or uncertain checks block deletion. Ordinary library deletion and saved-recording
discard also require a remote copy. Discarding an active recording preserves the saved file.

For focused safe checks, set `UNTANGLE_TEST_PATTERN` to a test filename before
running `./scripts/test.sh`. The same device, network, and filesystem isolation applies.
