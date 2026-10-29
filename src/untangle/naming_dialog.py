"""Shared local recording name prompt. Renaming belongs to the caller."""
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .naming import editable_recording_title


class RecordingNameDialog(QDialog):
    """A retryable name editor; ``saved_path`` is set only after a successful save."""

    def __init__(self, parent: QWidget | None, path: Path,
                 rename: Callable[[str], Path], *, new_recording: bool = False,
                 discard: Callable[[], None] | None = None):
        super().__init__(parent)
        self.saved_path: Path | None = None
        self.discarded = False
        self._rename = rename
        self._discard = discard
        self._saving = False
        self._finished = False
        title = 'Name your recording' if new_recording else 'Rename recording'
        self.setWindowTitle(title)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setObjectName('title')
        heading.setWordWrap(True)
        layout.addWidget(heading)
        description = QLabel('Your recording is saved safely. This changes only its local name. '
                             'An existing Loom title stays unchanged.')
        description.setObjectName('muted')
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addSpacing(4)

        label = QLabel('Recording name')
        self.name_edit = QLineEdit(editable_recording_title(path))
        self.name_edit.setAccessibleName('Recording name')
        label.setBuddy(self.name_edit)
        layout.addWidget(label)
        layout.addWidget(self.name_edit)
        hint = QLabel('The filename extension is handled automatically.')
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.error_label = QLabel()
        self.error_label.setObjectName('error')
        self.error_label.setTextFormat(Qt.PlainText)
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.discard_button = QPushButton('Discard recording')
        self.discard_button.setObjectName('deleteRecording')
        self.discard_button.setAutoDefault(False)
        self.discard_button.clicked.connect(self.discard)
        self.discard_button.setVisible(discard is not None)
        buttons.addWidget(self.discard_button)
        buttons.addStretch()
        self.cancel_button = QPushButton('Keep current name' if new_recording else 'Cancel')
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.save_button = QPushButton('Save name')
        self.save_button.setObjectName('primary')
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.accept)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self.name_edit.textChanged.connect(self._validate)
        self._validate()
        self.name_edit.setFocus()
        self.name_edit.selectAll()
        self.resize(520, self.sizeHint().height())

    def _validate(self):
        valid = bool(self.name_edit.text().strip())
        self.save_button.setEnabled(valid and not self._saving and not self._finished)
        self.error_label.setText('' if valid else 'Enter a recording name to save.')
        self.error_label.setVisible(not valid)
        if self.isVisible():
            self._fit_content()

    def _fit_content(self):
        self.layout().activate()
        self.resize(self.width(), self.layout().totalHeightForWidth(self.width()))

    def accept(self):
        """Save via the caller, keeping the editor open when renaming fails."""
        if self._saving or self._finished:
            return
        if not self.name_edit.text().strip():
            self._validate()
            return
        self._saving = True
        self.save_button.setEnabled(False)
        try:
            self.saved_path = self._rename(self.name_edit.text().strip())
        except (OSError, ValueError) as error:
            self.error_label.setText(f'Could not save the name: {error}')
            self.error_label.show()
            self._fit_content()
            self.name_edit.setFocus()
        else:
            super().accept()
        finally:
            self._saving = False
            self.save_button.setEnabled(bool(self.name_edit.text().strip()) and not self._finished)

    def discard(self):
        """Delete through the caller after an explicit confirmation."""
        if self._discard is None or self._saving or self._finished:
            return
        answer = QMessageBox.question(self, 'Discard recording?',
            'Permanently delete this recording? This cannot be undone.',
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return
        try:
            self._discard()
        except OSError as error:
            self.error_label.setText(f'Could not discard the recording: {error}')
            self.error_label.show()
            self._fit_content()
            return
        self.discarded = True
        self.reject()

    def done(self, result):
        self._finished = True
        super().done(result)


def prompt_recording_name(parent: QWidget | None, path: Path,
                          rename: Callable[[str], Path], *,
                          new_recording: bool = False,
                          discard: Callable[[], None] | None = None) -> Path | None:
    """Return the renamed path on Save, or None when dismissed or discarded."""
    dialog = RecordingNameDialog(parent, path, rename, new_recording=new_recording, discard=discard)
    try:
        if dialog.exec() == QDialog.Accepted:
            return dialog.saved_path
        return None
    finally:
        dialog.deleteLater()
