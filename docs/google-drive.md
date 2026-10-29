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
