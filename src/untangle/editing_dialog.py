"""Silent trim controls for local recording projects. No capture or playback."""
import threading
from pathlib import Path

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout)

from .editing import RecordingProject


class ExportWorker(QThread):
    result = Signal(object, str)

    def __init__(self, project, start, end, parent):
        super().__init__(parent)
        self.project, self.start_time, self.end_time = project, start, end
        self.cancel = threading.Event()

    def run(self):
        try:
            self.result.emit(self.project.export(self.start_time, self.end_time, self.cancel), '')
        except Exception as exc:
            self.result.emit(None, str(exc))


class EditingDialog(QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.project = RecordingProject(path)
        self.worker = None
        self.closing = False
        self.last_output = None
        self.outcome = (None, '')
        self.setWindowTitle('Edit / export recording')
        self.resize(560, 440)
        layout = QVBoxLayout(self)
        source = QLabel(f'Original: {Path(path).name}')
        source.setWordWrap(True)
        layout.addWidget(source)
        explanation = QLabel('Trim a new version. The original stays unchanged. '
                             'Screen and camera are baked together; recorded audio is mixed. '
                             'This file cannot be reframed into separate tracks. No automatic playback or upload.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        form = QFormLayout()
        self.start_time = QDoubleSpinBox()
        self.end_time = QDoubleSpinBox()
        for control in (self.start_time, self.end_time):
            control.setRange(0, 864000)
            control.setDecimals(2)
            control.setSuffix(' s')
        self.start_time.setAccessibleName('Trim start in seconds')
        self.end_time.setAccessibleName('Trim end in seconds, zero for recording end')
        form.addRow('Start', self.start_time)
        form.addRow('End, 0 = recording end', self.end_time)
        layout.addLayout(form)
        quality = QLabel('Export: H.264 / AAC MP4. Re-encoding can reduce quality. '
                         'Each attempt gets a new version number.')
        quality.setWordWrap(True)
        layout.addWidget(quality)
        self.history = QLabel()
        self.history.setWordWrap(True)
        layout.addWidget(self.history)
        self.status = QLabel('Choose a time range, then export.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        buttons = QHBoxLayout()
        self.export_button = QPushButton('Export new version')
        self.export_button.clicked.connect(self.export)
        self.folder_button = QPushButton('Open project folder')
        self.folder_button.clicked.connect(self.open_folder)
        self.cancel_button = QPushButton('Close')
        self.cancel_button.clicked.connect(self.reject)
        for button in (self.export_button, self.folder_button, self.cancel_button):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.refresh_history()

    def refresh_history(self):
        try:
            versions = self.project.history()
            recent = versions[-4:]
            text = '; '.join(f"v{item['number']:04d}: {item['status']}" for item in recent)
            self.history.setText('Recent exports: ' + (text or 'none yet'))
        except Exception as exc:
            self.history.setText(str(exc))
            self.export_button.setEnabled(False)

    def export(self):
        if self.worker is not None:
            return
        start, end = self.start_time.value(), self.end_time.value()
        if end and end <= start:
            self.status.setText('End must be later than start. Use zero for the recording end.')
            return
        self.closing = False
        self.outcome = (None, '')
        self.worker = ExportWorker(self.project, start, end, self)
        self.worker.result.connect(self.export_result)
        self.worker.finished.connect(self.export_finished)
        self.export_button.setEnabled(False)
        self.start_time.setEnabled(False)
        self.end_time.setEnabled(False)
        self.cancel_button.setText('Cancel export')
        self.status.setText('Exporting a new local version. The original stays unchanged.')
        self.worker.start()

    def export_result(self, path, error):
        self.outcome = (path, error)

    def export_finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.last_output, error = self.outcome
        self.start_time.setEnabled(True)
        self.end_time.setEnabled(True)
        self.export_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText('Close')
        self.status.setText(error or f'Saved {self.last_output}. Open the project folder to review. '
                            'No media has been played or uploaded.')
        self.refresh_history()
        if self.closing:
            super().reject()

    def open_folder(self):
        if self.project.directory.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project.directory)))

    def reject(self):
        if self.worker is not None:
            self.closing = True
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self.status.setText('Cancelling export. Waiting for the encoder to stop safely…')
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
