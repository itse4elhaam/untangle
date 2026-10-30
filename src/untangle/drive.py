"""Google Drive integration. No network calls occur until explicitly requested."""
from .diagnostics import observed, failure as diagnostic_failure
import json
import os
from pathlib import Path

SCOPES = ['https://www.googleapis.com/auth/drive']


class DriveClient:
    def __init__(self, state=None):
        self.state = state or Path.home() / '.local/share/glint/google-drive'
        self.client_file = self.state / 'client.json'
        self.token_file = self.state / 'token.json'

    def save_private(self, path, content):
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state, 0o700)
        temporary = path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        temporary.replace(path)

    @observed("drive.configure")
    def configure(self, path):
        content = Path(path).read_text()
        data = json.loads(content).get('installed', {})
        if not data.get('client_id') or not data.get('client_secret'):
            raise ValueError('Choose an OAuth client JSON downloaded for a Desktop app.')
        self.save_private(self.client_file, content)
        self.disconnect()

    @observed("drive.login")
    def login(self):
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(self.client_file), SCOPES)
        credentials = flow.run_local_server(host='127.0.0.1', port=0, timeout_seconds=180,
                                            access_type='offline', prompt='consent')
        self.save_private(self.token_file, credentials.to_json())

    def service(self):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        if not self.token_file.exists():
            raise ValueError('Sign in with Google first.')
        credentials = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
        if not credentials.valid:
            if not credentials.refresh_token:
                raise ValueError('Your Google sign-in expired. Sign in again.')
            credentials.refresh(Request())
            self.save_private(self.token_file, credentials.to_json())
        return build('drive', 'v3', credentials=credentials, cache_discovery=False)

    @observed("drive.folders")
    def folders(self):
        service = self.service()
        folders = [('My Drive', 'root')]
        page = None
        while True:
            result = service.files().list(
                q="mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                fields='nextPageToken,files(id,name)', pageSize=1000, pageToken=page).execute()
            folders.extend((f['name'], f['id']) for f in result.get('files', []))
            page = result.get('nextPageToken')
            if not page:
                return folders

    @observed("drive.upload")
    def upload(self, paths, folder_id, progress):
        from googleapiclient.http import MediaFileUpload
        service = self.service()
        failures = []
        for path in paths:
            try:
                media = MediaFileUpload(str(path), resumable=True, chunksize=8 * 1024 * 1024)
                request = service.files().create(body={'name': path.name, 'parents': [folder_id]},
                                                 media_body=media, fields='id')
                response = None
                while response is None:
                    status, response = request.next_chunk(num_retries=3)
                    if status:
                        progress(f'{path.name}: {status.progress():.0%}')
                progress(f'Uploaded {path.name}')
            except Exception:
                failures.append(path.name)
        if failures:
            raise ValueError('Upload failed for: ' + ', '.join(failures) + '. Other files may have uploaded. Retrying creates new copies.')

    @observed("drive.disconnect")
    def disconnect(self):
        self.token_file.unlink(missing_ok=True)
