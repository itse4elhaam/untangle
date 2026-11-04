"""Explicit Google authorization and selected-recording uploads."""
from .diagnostics import observed, failure as diagnostic_failure
from PySide6.QtCore import QThread, Signal, QSettings, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, QComboBox,
                               QFileDialog, QMessageBox, QCheckBox, QScrollArea, QWidget)
from .drive import DriveClient


class DriveTask(QThread):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    @observed("drive_dialog.run")
    def run(self):
        try:
            self.done.emit(self.operation(self.progress.emit))
        except Exception:
            # OAuth and HTTP exceptions can contain credentials or sensitive URLs.
            self.failed.emit('Google Drive could not finish this action. Check your connection, '
                             'folder permissions and OAuth setup, or sign in again. '
                             'Some files may have uploaded; check Drive before retrying.')


class DriveDialog(QDialog):
    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths = tuple(paths)
        self.client = DriveClient()
        self.task = None
        self.settings = QSettings('TrueDevs', 'Glint')
        self.setWindowTitle('Google Drive')
        self.resize(600, 650)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout = QVBoxLayout(content)
        note = QLabel('Sign in with Google, choose a destination folder, then upload only the '
                      'recordings you selected. Google will ask for Drive access to browse '
                      'folders and upload files. Background archiving is optional.')
        note.setWordWrap(True)
        layout.addWidget(note)
        from .drive_help import show_drive_setup_guide
        self.setup_guide = QPushButton('Google Drive setup and recovery…')
        self.setup_guide.setAutoDefault(False)
        self.setup_guide.clicked.connect(lambda: show_drive_setup_guide(self))
        layout.addWidget(self.setup_guide)
        self.configure = QPushButton('Set up Google OAuth client…')
        self.configure.clicked.connect(self.configure_client)
        layout.addWidget(self.configure)
        self.login = QPushButton('Sign in with Google')
        self.login.clicked.connect(lambda: self.start(lambda progress: self.client.login(), self.load_folders,
            message='Waiting for Google sign-in in your browser…', completed='Google sign-in saved.'))
        layout.addWidget(self.login)
        self.refresh = QPushButton('Load Drive folders')
        self.refresh.clicked.connect(self.load_folders)
        layout.addWidget(self.refresh)
        self.folders = QComboBox()
        layout.addWidget(self.folders)
        from .archive import config
        self.archive_enabled = QCheckBox('Archive automatically in the background')
        self.archive_enabled.setChecked(bool(config().get('enabled')))
        layout.addWidget(self.archive_enabled)
        self.archive_save = QPushButton('Save archive destination and settings')
        self.archive_save.clicked.connect(self.save_archive)
        layout.addWidget(self.archive_save)
        retention = QLabel('Cleanup is offered after 7 days from verified upload. '
                           'Local deletion always requires confirmation in the library.')
        retention.setWordWrap(True)
        layout.addWidget(retention)
        from .archive_status import archive_status
        self.archive_status = QLabel(archive_status())
        self.archive_status.setTextFormat(Qt.PlainText)
        self.archive_status.setWordWrap(True)
        layout.addWidget(self.archive_status)
        self.archive_refresh = QPushButton('Refresh archive status')
        self.archive_refresh.setAutoDefault(False)
        self.archive_refresh.clicked.connect(self.refresh_archive_status)
        layout.addWidget(self.archive_refresh)
        self.upload = QPushButton(f'Upload {len(paths)} selected recording(s)')
        self.upload.clicked.connect(self.upload_files)
        layout.addWidget(self.upload)
        self.disconnect = QPushButton('Forget Google sign-in on this computer')
        self.disconnect.clicked.connect(self.forget)
        layout.addWidget(self.disconnect)
        self.status = QLabel('Not connected. Set up a Desktop OAuth client, then sign in.'
                             if not self.client.token_file.exists() else 'Sign-in saved. Load folders to continue.')
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.controls = [self.archive_refresh, self.archive_enabled, self.archive_save, self.configure, self.login, self.refresh, self.folders, self.upload, self.disconnect]
        self.upload.setEnabled(False)

    @observed("drive_dialog.configure_client")
    def configure_client(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose Google Desktop OAuth client JSON', '', 'JSON (*.json)')
        if path:
            try:
                self.client.configure(path)
                self.folders.clear()
                self.upload.setEnabled(False)
                self.status.setText('Client configured. Sign in with Google to continue.')
            except (ValueError, OSError):
                self.status.setText('Could not read a valid Desktop OAuth client JSON.')

    def start(self, operation, done=None, *, message='Working…', completed='Action finished.'):
        if self.task is not None:
            return
        for control in self.controls:
            control.setEnabled(False)
        self.status.setText(message)
        task = DriveTask(operation, self)
        self.task = task
        task.progress.connect(self.status.setText)
        task.failed.connect(self.status.setText)
        task.done.connect(lambda result: self.status.setText(completed))
        # Wait for thread completion before allowing close or another operation.
        task.finished.connect(lambda: self.finished_task(task, done))
        task.done.connect(lambda result: setattr(task, 'result', result))
        task.start()

    def finished_task(self, task, done):
        success = hasattr(task, 'result')
        self.task = None
        for control in self.controls:
            control.setEnabled(True)
        self.upload.setEnabled(bool(self.paths) and self.folders.count() > 0)
        task.deleteLater()
        if success and done:
            done(task.result)

    @observed("drive_dialog.load_folders")
    def load_folders(self, _=None):
        self.start(lambda progress: self.client.folders(), self.show_folders,
                   message='Loading Google Drive folders…')

    def show_folders(self, folders):
        self.folders.clear()
        for name, identifier in sorted(folders):
            self.folders.addItem(f'{name} ({identifier})', identifier)
        from .archive import config
        index = self.folders.findData(config().get('folder') or self.settings.value('drive/folder', 'root'))
        self.folders.setCurrentIndex(max(index, 0))
        self.upload.setEnabled(bool(self.paths) and bool(folders))
        self.status.setText('Choose a folder for the selected recordings.')

    def save_archive(self):
        from .archive import configure
        try:
            configure(self.archive_enabled.isChecked(), self.folders.currentData())
            self.settings.setValue('drive/folder', self.folders.currentData())
            self.status.setText('Archive settings saved. This does not start or enable the scheduler. See the setup guide.')
            from .archive_status import archive_status
            self.archive_status.setText(archive_status())
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))

    @observed("drive_dialog.upload_files")
    def upload_files(self):
        folder = self.folders.currentData()
        if not folder or not self.paths:
            return
        answer = QMessageBox.question(self, 'Upload to Google Drive',
            f'Upload {len(self.paths)} recording(s) to {self.folders.currentText()}? '
            'Excluded recordings will be skipped. Existing archive copies are reused in their '
            'original destination; new uploads use the chosen folder. Copies are verified before cleanup.')
        if answer != QMessageBox.Yes:
            return
        self.settings.setValue('drive/folder', folder)
        destination = self.folders.currentText()
        self.start(lambda progress: self.client.upload(self.paths, folder, progress),
                   lambda outcomes: self.show_upload_results(outcomes, destination),
                   message=f'Uploading selected recordings to {destination}…')

    def refresh_archive_status(self):
        from .archive_status import scheduler_status, archive_status
        self.start(lambda progress: scheduler_status(),
                   lambda scheduler: self.archive_status.setText(archive_status(scheduler=scheduler)),
                   message='Reading archive scheduler status…',
                   completed='Archive status refreshed. No scheduler settings changed.')

    def show_upload_results(self, outcomes, destination):
        uploaded = sum(row.get('status') == 'uploaded' for row in outcomes)
        lines = [f'{uploaded} of {len(outcomes)} uploaded to {destination}.']
        for row in outcomes:
            result = ('Uploaded and verified' if row.get('status') == 'uploaded' else
                      'Skipped: Do not upload to Google Drive' if row.get('status') == 'excluded' else
                      'Failed or unconfirmed; check Drive before retrying')
            lines.append(f'{row["name"]}: {result}')
        lines.append('Verified copies satisfy the deletion check. Cleanup is offered after 7 days. '
                     'Retries reuse the saved archive copy in its original destination.')
        self.status.setText('\n'.join(lines))

    @observed("drive_dialog.forget")
    def forget(self):
        self.client.disconnect()
        self.folders.clear()
        self.upload.setEnabled(False)
        self.status.setText('Local Google sign-in removed. You can revoke Untangle access in your Google account.')

    def reject(self):
        if self.task is None:
            super().reject()
        else:
            self.status.setText('Wait for the current operation to finish. Google sign-in times out after three minutes.')

    def closeEvent(self, event):
        if self.task is not None:
            event.ignore()
        else:
            super().closeEvent(event)
