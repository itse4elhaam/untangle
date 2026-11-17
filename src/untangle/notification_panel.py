"""Recorder notification panel: recent Loom cleanup outcomes with link actions."""
from datetime import datetime

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .loom import valid_share_url


def _label(text, name=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    widget.setWordWrap(True)
    if name:
        widget.setObjectName(name)
    return widget


def button_text(unread):
    return f'Notifications ({unread})' if unread else 'Notifications'


class NotificationPanel(QDialog):
    """Non-modal list; opening it marks everything read."""
    changed = Signal()

    def __init__(self, log, parent=None):
        super().__init__(parent)
        self.log = log
        self.setWindowTitle('Untangle · Notifications')
        self.setObjectName('notificationPanel')
        self.resize(460, 520)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 16)
        outer.addWidget(_label('Notifications', 'section'))
        self.status = _label('', 'muted')
        outer.addWidget(self.status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.rows = QVBoxLayout(self.body)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(8)
        scroll.setWidget(self.body)
        outer.addWidget(scroll, 1)
        footer = QHBoxLayout()
        self.clear_button = QPushButton('Clear all')
        self.clear_button.setAutoDefault(False)
        self.clear_button.clicked.connect(self.clear)
        footer.addWidget(self.clear_button)
        footer.addStretch()
        close = QPushButton('Close')
        close.setAutoDefault(False)
        close.clicked.connect(self.close)
        footer.addWidget(close)
        outer.addLayout(footer)

    def open_panel(self):
        self.log.mark_all_read()
        self.rebuild()
        self.changed.emit()
        self.show()
        self.raise_()
        self.activateWindow()

    def rebuild(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        entries = self.log.entries()
        self.status.setText(self.log.error or ('' if entries else 'No notifications yet.'))
        self.status.setVisible(bool(self.status.text()))
        self.clear_button.setEnabled(bool(entries))
        for entry in entries:
            self.rows.addWidget(self.row(entry))
        self.rows.addStretch()

    def row(self, entry):
        frame = QFrame()
        frame.setObjectName('notificationRow')
        frame.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        layout.addWidget(_label(entry.get('title', '')))
        if entry.get('detail'):
            layout.addWidget(_label(entry['detail'], 'muted'))
        try:
            when = datetime.fromtimestamp(float(entry.get('time'))).strftime('%b %d, %H:%M')
        except (TypeError, ValueError, OverflowError, OSError):
            when = ''
        if when:
            layout.addWidget(_label(when, 'muted'))
        url = valid_share_url(entry.get('url'))
        if url:
            actions = QHBoxLayout()
            copy = QPushButton('Copy link')
            copy.setAutoDefault(False)
            copy.clicked.connect(lambda *_, url=url: self.copy(url))
            actions.addWidget(copy)
            open_button = QPushButton('Open in Loom ↗')
            open_button.setAutoDefault(False)
            open_button.clicked.connect(lambda *_, url=url: QDesktopServices.openUrl(QUrl(url)))
            actions.addWidget(open_button)
            actions.addStretch()
            layout.addLayout(actions)
        return frame

    def copy(self, url):
        QApplication.clipboard().setText(url)
        self.status.setText('Loom link copied. Review permissions in Loom before sharing.')
        self.status.show()

    def clear(self):
        self.log.clear()
        self.rebuild()
        self.changed.emit()
