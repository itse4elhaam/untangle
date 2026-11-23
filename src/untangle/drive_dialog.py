"""Selected-recording uploads and archive settings through the user's rclone Drive remote."""
import os
from urllib.parse import quote

from .widgets import ScrollComboBox
from .diagnostics import observed, failure as diagnostic_failure
from PySide6.QtCore import QThread, Signal, QSettings, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QMessageBox, QCheckBox, QScrollArea, QWidget)
from .drive import DriveClient, REMOTE_ENV
from .rclone import RcloneError, NoDriveRemote, normalize, preferred


PENDING_ARCHIVE_ENABLED = 'drive/pending_archive_enabled'


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
        except RcloneError as exc:
            # Fixed messages only; rclone output stays in exc.detail and is never shown or logged.
            diagnostic_failure('drive_dialog.rclone_failed', exc)
            self.failed.emit(str(exc))
        except Exception as exc:
            diagnostic_failure('drive_dialog.failed', exc)
            self.failed.emit('Google Drive could not finish this action. Check your connection, '
                             'the rclone remote and folder permissions. '
                             'Some files may have uploaded; check Drive before retrying.')


class DriveDialog(QDialog):
    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths = tuple(paths)
        self.client = DriveClient()
        self.task = None
        self.settings = QSettings('TrueDevs', 'Glint')
        self.default_remote = None
        self.setWindowTitle('Google Drive')
        self.resize(600, 650)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout = QVBoxLayout(content)
        note = QLabel('Untangle uploads with rclone, using a Google Drive remote you set up '
                      'yourself with "rclone config". Choose a remote and a destination folder, '
                      'then upload only the recordings you selected. Background archiving is optional.')
        note.setWordWrap(True)
        layout.addWidget(note)
        from .drive_help import show_drive_setup_guide
        self.setup_guide = QPushButton('Google Drive setup and recovery…')
        self.setup_guide.setAutoDefault(False)
        self.setup_guide.clicked.connect(lambda: show_drive_setup_guide(self))
        layout.addWidget(self.setup_guide)
        layout.addWidget(QLabel('rclone remote'))
        remote_row = QHBoxLayout()
        self.remotes = ScrollComboBox()
        from .archive import config
        archive = config()
        saved = self.settings.value('drive/remote') or archive.get('remote')
        if saved:
            self.remotes.addItem(normalize(saved), normalize(saved))
        self.remotes.currentIndexChanged.connect(self.remote_changed)
        remote_row.addWidget(self.remotes, 1)
        self.find_remotes = QPushButton('Find rclone remotes')
        self.find_remotes.clicked.connect(self.load_remotes)
        remote_row.addWidget(self.find_remotes)
        layout.addLayout(remote_row)
        self.refresh = QPushButton('Load Drive folders')
        self.refresh.clicked.connect(self.load_folders)
        layout.addWidget(self.refresh)
        self.folders = ScrollComboBox()
        self.folders.currentIndexChanged.connect(self.remember_folder)
        layout.addWidget(self.folders)
        self.archive_enabled = QCheckBox('Archive automatically in the background')
        self.applied_archive_enabled = bool(archive.get('enabled'))
        draft = self.settings.value(PENDING_ARCHIVE_ENABLED, self.applied_archive_enabled, type=bool)
        self.archive_enabled.setChecked(draft)
        layout.addWidget(self.archive_enabled)
        self.archive_pending = QLabel('Choose Save to apply this background archiving change.')
        layout.addWidget(self.archive_pending)
        self.archive_enabled.toggled.connect(self.remember_archive_choice)
        self.remember_archive_choice(self.archive_enabled.isChecked())
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
        self.cancel_button = QPushButton('Cancel current action')
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_task)
        layout.addWidget(self.cancel_button)
        legacy = self.client.legacy_sign_in()
        if legacy:
            # Never removed automatically; the guide explains removal and revocation.
            old = QLabel('An earlier Untangle Google sign-in is still saved on this computer but is '
                         'no longer used: ' + ', '.join(str(path) for path in legacy) + '. You can '
                         'remove it and revoke its access as described in the setup guide.')
            old.setTextFormat(Qt.PlainText)
            old.setWordWrap(True)
            layout.addWidget(old)
        self.status = QLabel('Choose Load Drive folders. Untangle finds your rclone Drive remote '
                             'if none is chosen.')
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.controls = [self.archive_refresh, self.archive_enabled, self.archive_save, self.remotes,
                         self.find_remotes, self.refresh, self.folders, self.upload]
        self.upload.setEnabled(False)

    def remember_archive_choice(self, enabled):
        pending = enabled != self.applied_archive_enabled
        self.archive_pending.setVisible(pending)
        if pending:
            self.settings.setValue(PENDING_ARCHIVE_ENABLED, enabled)
        elif self.settings.contains(PENDING_ARCHIVE_ENABLED):
            self.settings.remove(PENDING_ARCHIVE_ENABLED)
        else:
            return
        self.settings.sync()

    def remote_changed(self, _=None):
        if self.task is None:
            self.folders.clear()
            self.upload.setEnabled(False)
            if self.remotes.currentData():
                self.settings.setValue('drive/remote', self.remotes.currentData())
                self.settings.sync()

    def remember_folder(self, _=None):
        remote = self.remotes.currentData()
        folder = self.folders.currentData()
        self.upload.setEnabled(bool(self.paths and remote and folder))
        if remote and folder:
            self.settings.setValue('drive/remote', remote)
            self.settings.setValue('drive/folders/' + quote(remote, safe=''), folder)
            self.settings.sync()

    @observed("drive_dialog.load_remotes")
    def load_remotes(self, _=None):
        self.start(lambda progress: self.client.remotes(), self.show_remotes,
                   message='Looking for rclone Google Drive remotes…', completed='rclone remotes found.')

    def show_remotes(self, remotes, chosen=None):
        if not remotes:
            self.folders.clear()
            self.upload.setEnabled(False)
            self.status.setText(str(NoDriveRemote()))
            return
        current = chosen or self.remotes.currentData()
        self.default_remote = preferred(remotes)
        self.remotes.blockSignals(True)
        self.remotes.clear()
        for name in remotes:
            self.remotes.addItem(name, name)
        index = self.remotes.findData(current)
        if current and index < 0:
            self.remotes.addItem(f'{current} (unavailable)', current)
            index = self.remotes.count() - 1
            self.folders.clear()
            self.upload.setEnabled(False)
        self.remotes.setCurrentIndex(index if index >= 0 else self.remotes.findData(self.default_remote))
        self.remotes.blockSignals(False)
        if self.remotes.currentData() != current:
            self.remote_changed()
        self.status.setText('Choose a remote, then Load Drive folders.')

    def start(self, operation, done=None, *, message='Working…', completed='Action finished.'):
        if self.task is not None:
            return
        for control in self.controls:
            control.setEnabled(False)
        self.client.cancelled.clear()
        self.cancel_button.setEnabled(True)
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
        self.cancel_button.setEnabled(False)
        self.upload.setEnabled(bool(self.paths and self.remotes.currentData() and self.folders.currentData()))
        task.deleteLater()
        if success and done:
            done(task.result)

    def cancel_task(self):
        if self.task is not None:
            self.client.cancel()
            self.status.setText('Cancelling… rclone stops after its current step.')

    @observed("drive_dialog.load_folders")
    def load_folders(self, _=None):
        # Read widgets here: the worker thread must not touch Qt.
        remote = self.remotes.currentData()
        def operation(progress):
            found = None
            if remote:
                self.client.remote = remote
            else:
                found = self.client.remotes()
                if not found:
                    raise NoDriveRemote()
                self.client.remote = preferred(found)
            return found, self.client.remote, self.client.folders()
        self.start(operation, self.show_loaded, message='Loading Google Drive folders with rclone…')

    def show_loaded(self, result):
        found, remote, folders = result
        if found:
            self.show_remotes(found, remote)
        self.show_folders(folders)

    def show_folders(self, folders):
        from .archive import config
        remote = self.remotes.currentData()
        archive = config()
        saved = self.settings.value('drive/folders/' + quote(remote, safe='')) if remote else None
        archive_remote = archive.get('remote') or os.environ.get(REMOTE_ENV) or self.default_remote
        if not saved and archive_remote and remote == normalize(archive_remote):
            saved = archive.get('folder')
        if not saved:
            # Earlier releases stored a folder ID without its rclone remote.
            # Only reuse it when this remote's listing confirms the ID.
            saved = self.settings.value('drive/folder') or 'root'
            if saved != 'root' and all(identifier != saved for _, identifier in folders):
                saved = None
        self.folders.blockSignals(True)
        self.folders.clear()
        top, rest = folders[:1], sorted(folders[1:], key=lambda item: item[0].lower())
        for name, identifier in top + rest:
            self.folders.addItem(f'{name} ({identifier})', identifier)
        if folders and saved and self.folders.findData(saved) < 0:
            # Deep or shared-with-me folders are not listed; never fall back to My Drive silently.
            self.folders.addItem(f'Saved destination ({saved})', saved)
        self.folders.setCurrentIndex(self.folders.findData(saved))
        self.folders.blockSignals(False)
        self.upload.setEnabled(bool(self.paths and remote and self.folders.currentData()))
        self.status.setText('Choose a folder for the selected recordings.' if saved else
                            'Choose a destination. The previously saved folder could not be matched to this remote.')

    def save_archive(self):
        from .archive import config, configure
        try:
            enabled = self.archive_enabled.isChecked()
            remote = self.remotes.currentData()
            folder = self.folders.currentData()
            if not folder:
                saved = config()
                archive_remote = normalize(saved['remote']) if saved.get('remote') else None
                if enabled and (not saved.get('folder') or remote != archive_remote):
                    raise ValueError('Choose an rclone remote and load its folders first.')
                remote, folder = saved.get('remote'), saved.get('folder')
            configure(enabled, folder, remote=remote)
            self.applied_archive_enabled = enabled
            self.remember_archive_choice(enabled)
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
            'original destination; new uploads use the chosen folder. Copies are verified after upload.')
        if answer != QMessageBox.Yes:
            return
        self.remember_folder()
        destination = self.folders.currentText()
        self.client.remote = self.remotes.currentData() or self.client.remote
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
                      'Not started: cancelled' if row.get('status') == 'cancelled' else
                      'Failed or unconfirmed; check Drive before retrying')
            lines.append(f'{row["name"]}: {result}')
        lines.append('Copies are checksum-verified. Cleanup is offered after 7 days. '
                     'Retries reuse the saved archive copy in its original destination.')
        self.status.setText('\n'.join(lines))

    def reject(self):
        if self.task is None:
            super().reject()
        else:
            self.status.setText('Wait for the current operation to finish, or choose Cancel current action.')

    def closeEvent(self, event):
        if self.task is not None:
            event.ignore()
        else:
            super().closeEvent(event)
