"""Caller-controlled recording controls; callers own capture visibility policy."""
from PySide6.QtCore import Qt, Signal, QRect, QEvent
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QMenu, QSizePolicy, QWidget, QToolTip
from . import floating


CONTROL_STRIP_HEIGHT = 120


class RecordingControls(QFrame):
    pause_requested = Signal()
    stop_requested = Signal()
    restart_requested = Signal()
    discard_requested = Signal()
    open_requested = Signal()
    hide_requested = Signal()
    strip_invalidated = Signal()

    def __init__(self):
        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        if QApplication.platformName() == 'xcb':
            flags |= Qt.X11BypassWindowManagerHint
        super().__init__(None, flags)
        self.setObjectName('recordingDock')
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self._strip_rect = None
        self._strip_ratio = None
        self._active = True
        self._placed = False
        self._drag_offset = None
        self._target = ''
        self._state = 'recording'
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
        for widget in [self, *self.findChildren(QWidget)]:
            widget.installEventFilter(self)
        self.resize(640, 100)
        self.update_state(state='recording', elapsed='00:00', target='', microphone='Microphone status unknown')

    def update_state(self, *, state, elapsed, target, microphone, warning='', hide_allowed=True):
        if state not in ('recording', 'paused', 'saving', 'starting'):
            raise ValueError(f'Unknown recording state: {state}')
        saving = state == 'saving'
        starting = state == 'starting'
        self._state = state
        self.update_state_label()
        self.elapsed_label.setText(elapsed)
        self._target = target
        self.target_label.setToolTip(target)
        self.target_label.setAccessibleName(target)
        self._elide_target()
        self.microphone_label.setText(self.microphone_label.fontMetrics().elidedText(
            microphone, Qt.ElideRight, 220))
        self.microphone_label.setToolTip('\n'.join(filter(None, (
            microphone, warning, 'Input data does not certify that speech was saved.'))))
        self.stop_button.setText('Cancel' if starting else 'Stop and save')
        self.pause_button.setText('Resume' if state == 'paused' else 'Pause')
        for button in (self.pause_button, self.stop_button, self.more_button):
            button.setEnabled(not saving)
        self.pause_button.setEnabled(not saving and not starting)
        self.more_button.setEnabled(not saving and not starting and self._strip_rect is None)
        self.menu.setEnabled(not saving and not starting and self._strip_rect is None)
        self.hide_button.setEnabled(not saving and hide_allowed)

    def update_state_label(self):
        suffix = ' · controls excluded' if self._strip_rect is not None else ''
        self.state_label.setText(self._state.capitalize() + suffix)

    @property
    def strip_rect(self):
        return QRect(self._strip_rect) if self._strip_rect is not None else None

    def event(self, event):
        if (event.type() == QEvent.DevicePixelRatioChange
                and getattr(self, '_strip_rect', None) is not None
                and self.devicePixelRatioF() != self._strip_ratio):
            self.hide()
            self.strip_invalidated.emit()
        return super().event(event)

    def eventFilter(self, watched, event):
        if self._strip_rect is not None and event.type() == QEvent.ToolTip:
            return True
        return super().eventFilter(watched, event)

    def show_in_strip(self, screen, height=CONTROL_STRIP_HEIGHT):
        self.hide()
        rect = screen.geometry()
        if height <= 0 or height > rect.height():
            raise ValueError('Invalid control strip height')
        strip = QRect(rect.left(), rect.bottom() - height + 1, rect.width(), height)
        self.ensurePolished()
        size = self.size().expandedTo(self.minimumSizeHint())
        if size.width() > strip.width() or size.height() > strip.height():
            raise ValueError('Recording controls do not fit inside the control strip')
        self.resize(size)
        self._strip_rect = strip
        self.update_state_label()
        self._strip_ratio = screen.devicePixelRatio()
        self.menu.close()
        QToolTip.hideText()
        self.more_button.setMenu(None)
        self.more_button.hide()
        self.menu.setEnabled(False)
        self.move(strip.center().x() - self.width() // 2,
                  strip.top() + (strip.height() - self.height()) // 2)
        self._placed = True
        self._active = True
        self.show()
        if not strip.contains(self.geometry()):
            self.hide()
            raise ValueError('Recording controls escaped the control strip')

    def _elide_target(self):
        self.target_label.setText(self.target_label.fontMetrics().elidedText(
            self._target, Qt.ElideRight, self.target_label.width()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide_target()

    def _clamp(self, position, screen):
        rect = self._strip_rect if self._strip_rect is not None else screen.availableGeometry()
        if self._strip_rect is not None:
            position.setY(self.y())
        position.setX(max(rect.left(), min(position.x(), rect.right() - self.width() + 1)))
        position.setY(max(rect.top(), min(position.y(), rect.bottom() - self.height() + 1)))
        return position

    def show_on_screen(self, screen):
        if self._strip_rect is not None:
            self._placed = False
        self._strip_rect = None
        self.update_state_label()
        self.more_button.setMenu(self.menu)
        self.more_button.show()
        saving = self.state_label.text() == 'Saving'
        self.more_button.setEnabled(not saving)
        self.menu.setEnabled(not saving)
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
        self._strip_rect = None
        self._placed = False

    def closeEvent(self, event):
        if self._active:
            self.hide_requested.emit()
            event.ignore()
        else:
            event.accept()
