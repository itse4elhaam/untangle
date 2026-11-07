"""Caller-controlled recording controls; callers own capture visibility policy."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QMenu, QSizePolicy
from . import floating


class RecordingControls(QFrame):
    pause_requested = Signal()
    stop_requested = Signal()
    restart_requested = Signal()
    discard_requested = Signal()
    open_requested = Signal()
    hide_requested = Signal()

    def __init__(self):
        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        if QApplication.platformName() == 'xcb':
            flags |= Qt.X11BypassWindowManagerHint
        super().__init__(None, flags)
        self.setObjectName('recordingDock')
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self._active = True
        self._placed = False
        self._drag_offset = None
        self._target = ''
        self.elapsed_label = QLabel('00:00')
        self.elapsed_label.setObjectName('dockElapsed')
        font = self.elapsed_label.font()
        font.setPointSize(20)
        self.elapsed_label.setFont(font)
        self.state_label = QLabel()
        self.target_label = QLabel()
        self.target_label.setObjectName('dockTarget')
        self.target_label.setMinimumWidth(0)
        self.target_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.target_label.setMaximumWidth(220)
        self.microphone_label = QLabel()
        self.microphone_label.setObjectName('dockMicrophone')
        self.microphone_label.setWordWrap(False)
        self.microphone_label.setTextFormat(Qt.PlainText)
        self.target_label.setTextFormat(Qt.PlainText)
        self.microphone_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout = QHBoxLayout(self)
        layout.addWidget(self.elapsed_label)
        labels = QVBoxLayout()
        for label in (self.state_label, self.target_label, self.microphone_label):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            labels.addWidget(label)
        self.elapsed_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addLayout(labels, 1)
        for name, text, signal in (
            ('pause_button', 'Pause', self.pause_requested),
            ('stop_button', 'Stop and save', self.stop_requested),
            ('hide_button', 'Hide', self.hide_requested),
        ):
            button = QPushButton(text)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(signal.emit)
            setattr(self, name, button)
        self.stop_button.setObjectName('dockStop')
        self.more_button = QPushButton('More')
        self.more_button.setFocusPolicy(Qt.NoFocus)
        self.menu = QMenu(self)
        for text, signal in (('Restart', self.restart_requested), ('Discard', self.discard_requested),
                             ('Open Untangle', self.open_requested)):
            self.menu.addAction(text, signal.emit)
        self.more_button.setMenu(self.menu)
        for button in (self.pause_button, self.stop_button, self.more_button, self.hide_button):
            layout.addWidget(button)
        self.resize(640, 100)
        self.update_state(state='recording', elapsed='00:00', target='', microphone='Microphone status unknown')

    def update_state(self, *, state, elapsed, target, microphone, warning='', hide_allowed=True):
        if state not in ('recording', 'paused', 'saving'):
            raise ValueError(f'Unknown recording state: {state}')
        saving = state == 'saving'
        self.state_label.setText(state.capitalize())
        self.elapsed_label.setText(elapsed)
        self._target = target
        self.target_label.setToolTip(target)
        self.target_label.setAccessibleName(target)
        self._elide_target()
        self.microphone_label.setText(self.microphone_label.fontMetrics().elidedText(
            microphone, Qt.ElideRight, 220))
        self.microphone_label.setToolTip('\n'.join(filter(None, (
            microphone, warning, 'Input data does not certify that speech was saved.'))))
        self.pause_button.setText('Resume' if state == 'paused' else 'Pause')
        for button in (self.pause_button, self.stop_button, self.more_button):
            button.setEnabled(not saving)
        self.menu.setEnabled(not saving)
        self.hide_button.setEnabled(not saving and hide_allowed)

    def _elide_target(self):
        self.target_label.setText(self.target_label.fontMetrics().elidedText(
            self._target, Qt.ElideRight, self.target_label.width()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide_target()

    def _clamp(self, position, screen):
        rect = screen.availableGeometry()
        position.setX(max(rect.left(), min(position.x(), rect.right() - self.width() + 1)))
        position.setY(max(rect.top(), min(position.y(), rect.bottom() - self.height() + 1)))
        return position

    def show_on_screen(self, screen):
        rect = screen.availableGeometry()
        position = self.pos() if self._placed else rect.center() - self.rect().center()
        if not self._placed:
            position.setY(rect.bottom() - self.height() - 24)
        self.move(self._clamp(position, screen))
        self._placed = True
        self._active = True
        self.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            position = event.globalPosition().toPoint() - self._drag_offset
            screen = QApplication.screenAt(event.globalPosition().toPoint()) or self.screen()
            self.move(self._clamp(position, screen))

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def hideEvent(self, event):
        self._drag_offset = None
        floating.release_window_input(self)
        super().hideEvent(event)

    def finish(self):
        self._active = False
        self.hide()

    def closeEvent(self, event):
        if self._active:
            self.hide_requested.emit()
            event.ignore()
        else:
            event.accept()
