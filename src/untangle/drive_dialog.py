"""Explicit Google authorization and selected-recording uploads."""
from .diagnostics import observed, failure as diagnostic_failure
from PySide6.QtCore import QThread, Signal, QSettings
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, QComboBox,
                               QFileDialog, QMessageBox)
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
        self.resize(540, 360)
        layout = QVBoxLayout(self)
        note = QLabel('Sign in with Google, choose a destination folder, then upload only the '
                      'recordings you selected. Google will ask for Drive access to browse '
                      'folders and upload files. Nothing uploads automatically.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.configure = QPushButton('Set up Google OAuth client…')
        self.configure.clicked.connect(self.configure_client)
        layout.addWidget(self.configure)
        self.login = QPushButton('Sign in with Google')
        self.login.clicked.connect(lambda: self.start(lambda progress: self.client.login(), self.load_folders))
        layout.addWidget(self.login)
        self.refresh = QPushButton('Load Drive folders')
        self.refresh.clicked.connect(self.load_folders)
        layout.addWidget(self.refresh)
        self.folders = QComboBox()
        layout.addWidget(self.folders)
        self.upload = QPushButton(f'Upload {len(paths)} selected recording(s)')
        self.upload.clicked.connect(self.upload_files)
        layout.addWidget(self.upload)
        self.disconnect = QPushButton('Forget Google sign-in on this computer')
        self.disconnect.clicked.connect(self.forget)
        layout.addWidget(self.disconnect)
        self.status = QLabel('Not connected. Set up a Desktop OAuth client, then sign in.'
                             if not self.client.token_file.exists() else 'Sign-in saved. Load folders to continue.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.controls = [self.configure, self.login, self.refresh, self.folders, self.upload, self.disconnect]
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

    def start(self, operation, done=None):
        if self.task is not None:
            return
        for control in self.controls:
            control.setEnabled(False)
        self.status.setText('Working… You can complete Google sign-in in your browser.')
        task = DriveTask(operation, self)
        self.task = task
        task.progress.connect(self.status.setText)
        task.failed.connect(self.status.setText)
        task.done.connect(lambda result: self.status.setText('Done.'))
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
        self.start(lambda progress: self.client.folders(), self.show_folders)

    def show_folders(self, folders):
        self.folders.clear()
        for name, identifier in sorted(folders):
            self.folders.addItem(f'{name} ({identifier})', identifier)
        index = self.folders.findData(self.settings.value('drive/folder', 'root'))
        self.folders.setCurrentIndex(max(index, 0))
        self.upload.setEnabled(bool(self.paths) and bool(folders))
        self.status.setText('Choose a folder for the selected recordings.')

    @observed("drive_dialog.upload_files")
    def upload_files(self):
        folder = self.folders.currentData()
        if not folder or not self.paths:
            return
        answer = QMessageBox.question(self, 'Upload to Google Drive',
            f'Upload {len(self.paths)} recording(s) to {self.folders.currentText()}? '
            'Uploading again creates additional copies.')
        if answer != QMessageBox.Yes:
            return
        self.settings.setValue('drive/folder', folder)
        self.start(lambda progress: self.client.upload(self.paths, folder, progress))

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
