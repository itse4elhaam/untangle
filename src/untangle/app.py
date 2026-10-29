#!/usr/bin/env python3
"""Untangle: a small native frontend for the OBS recording engine."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time

from PySide6.QtCore import Qt, QTimer, Signal, QThread, QProcess, QUrl, QSettings
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPen, QPixmap, QShortcut, QKeySequence, QCursor
from .floating import CameraBubble, ZoomMotion
from .windows import WindowCatalog
from .recordings import Recordings
from .camera_image import CameraAdjustments, CameraControlError, restore_saved
from .naming import next_recording_path, recording_files
from .naming import recording_title, rename_recording
from .naming_dialog import prompt_recording_name
from .local_titles import LocalTitleJob, local_title_capability
from .upload_store import UploadStore
from .loom import (parse_account_status, parse_video_info, parse_upload_result,
                   parse_upload_progress, valid_share_url, video_id)
from .audio_devices import AudioDevices, AudioDeviceError
from .audio_debug import AudioTrace, emit
from .engine import recording_audio_warning
from .composition import canvas_dimensions
from .microphone_meter import MicrophoneMeter
from .idle_audio import IdleAudio
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QSlider, QCheckBox, QFileDialog, QFrame,
    QSystemTrayIcon, QMenu, QMessageBox, QSizePolicy, QDialog, QLineEdit, QStackedWidget, QScrollArea, QProgressBar,
)

ROOT = Path(__file__).resolve().parents[2]
ICON = ROOT / 'assets/untangle-mark.svg'
VIDEOS = Path.home() / 'Videos/RecIt'
STATE = Path.home() / '.local/state/glint'
from .theme import stylesheet, apply_theme, load_fonts

# Kept as a public constant for offscreen consumers of the recorder style.
STYLE = stylesheet('light')


def label(text, kind=None):
    item = QLabel(text)
    if kind:
        item.setObjectName(kind)
    return item


def cameras():
    result = []
    for path in sorted(Path('/sys/class/video4linux').glob('video*')):
        device = '/dev/' + path.name
        try:
            info = subprocess.run(['v4l2-ctl', '-d', device, '--list-formats-ext'], capture_output=True, text=True, timeout=2).stdout
            # Ignore metadata and infrared devices. Preserve capture devices with colour formats.
            if any(fmt in info for fmt in ('MJPG', 'YUYV', 'NV12', 'RGB3', 'H264')):
                result.append((path.joinpath('name').read_text().strip(), device))
        except (OSError, subprocess.TimeoutExpired):
            continue
    return result


def microphones():
    try:
        return AudioDevices().microphones()
    except AudioDeviceError:
        return []


class Hotkeys(QThread):
    toggle = Signal()
    pause = Signal()
    zoom = Signal()
    unavailable = Signal(str)

    def run(self):
        import select
        try:
            from Xlib import X, XK, display, error
            conn = display.Display()
            root = conn.screen().root
            mapping = {}
            for key, action in [('F8', self.zoom), ('F9', self.toggle), ('F10', self.pause)]:
                code = conn.keysym_to_keycode(XK.string_to_keysym(key))
                mapping[code] = action
                for locks in (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask):
                    catcher = error.CatchError(error.BadAccess)
                    root.grab_key(code, X.ControlMask | X.ShiftMask | locks, False, X.GrabModeAsync, X.GrabModeAsync, onerror=catcher)
                    conn.sync()
                    if catcher.get_error():
                        self.unavailable.emit('Global shortcuts are in use. Use the tray icon to stop recording.')
            while not self.isInterruptionRequested():
                if conn.pending_events() or select.select([conn.fileno()], [], [], .25)[0]:
                    event = conn.next_event()
                    if event.type == X.KeyPress and event.detail in mapping:
                        mapping[event.detail].emit()
            root.ungrab_key(X.AnyKey, X.AnyModifier)
            conn.sync()
            conn.close()
        except Exception as exc:
            self.unavailable.emit(f'Global shortcuts unavailable. Use the tray icon. {exc}')


class Preview(QWidget):
    resized = Signal(int, int)
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WA_NativeWindow)
        self.setAttribute(Qt.WA_PaintOnScreen)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    def paintEngine(self):
        return None
    def resizeEvent(self, event):
        self.resized.emit(self.width(), self.height())
        super().resizeEvent(event)


class CanvasPreview(QFrame):
    """Keep the native sink inside an outlined canvas, without reparenting it."""
    def __init__(self, preview):
        super().__init__()
        self.setObjectName('previewWorkspace')
        self.setMinimumSize(320, 180)
        self.preview = preview
        self.preview.setParent(self)
        self.preview.setMinimumSize(16, 16)
        self._canvas = (1920, 1080)

    def set_canvas(self, width, height):
        self._canvas = width, height
        self.arrange()

    def arrange(self):
        bounds = self.contentsRect().adjusted(14, 14, -14, -14)
        width, height = self._canvas
        scale = min(max(1, bounds.width()) / width, max(1, bounds.height()) / height)
        width, height = max(1, round(width * scale)), max(1, round(height * scale))
        self.preview.setGeometry((self.width() - width) // 2, (self.height() - height) // 2,
                                 width, height)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange()

    def paintEvent(self, event):
        super().paintEvent(event)
        from .theme import tokens
        painter = QPainter(self)
        painter.setPen(QPen(QColor(tokens(QApplication.instance().property('untangleTheme'))['control_border']), 1))
        painter.drawRect(self.preview.geometry().adjusted(-1, -1, 0, 0))


class FinishWorker(QThread):
    finished_file = Signal(str, str)
    def __init__(self, engine, path):
        super().__init__()
        self.engine, self.path = engine, path
        self.audio_trace = getattr(engine, 'audio_trace', None)
    def run(self):
        started = time.monotonic()
        try:
            self.engine.stop()
            if self.engine.audio_expected is True:
                warning = recording_audio_warning(self.path, self.audio_trace)
                if warning:
                    self.engine.errors.append(warning)
            self.finished_file.emit(str(self.path), '')
        except Exception as exc:
            emit(self, 'finish.failed', level='warning', exception_type=type(exc).__name__,
                 duration_ms=round((time.monotonic() - started) * 1000))
            self.finished_file.emit(str(self.path), str(exc))


class AudioWorker(QThread):
    result = Signal(object, str)

    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action
        self.audio_trace = getattr(parent, 'audio_trace', None)

    def run(self):
        started = time.monotonic()
        try:
            self.result.emit(self.action(), '')
        except Exception as exc:
            emit(self, 'audio_worker.failed', level='warning', exception_type=type(exc).__name__,
                 duration_ms=round((time.monotonic() - started) * 1000))
            self.result.emit(None, str(exc))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Untangle')
        self.setWindowIcon(QIcon(str(ICON)))
        self.resize(1120, 840)
        self.setMinimumSize(960, 760)
        self.prefs = QSettings('TrueDevs', 'Glint')  # Preserve existing preferences.
        self.engine = None
        self._framing_explicit = False
        self.audio_devices = AudioDevices()
        self.audio_worker = None
        self.idle_audio = IdleAudio(self)
        self.selected_source = None
        self.preparing_audio = False
        self._audio_generation = 0
        self._audio_warning_since = None
        self._closing = False
        self._capture_window_state = None
        self._audio_retry_at = 0
        self.recording = False
        self.paused = False
        self.busy = False
        self.counting = False
        self.mode = 'camera'
        self.mask_path = self.prefs.value('mask', '')
        self.last_file = None
        self.recordings = None
        self.camera_adjustments = None
        self._camera_image_applied = None
        self.process = None
        self.worker = None
        self.started = 0
        self.pause_started = 0
        self.paused_duration = 0
        self.quit_after_save = False
        self._configure_pending = False
        self._live_update_failed = False
        self.configuration_valid = False
        self.recording_error = ''
        self.recording_error_baseline = 0
        self.zoom_motion = ZoomMotion()
        self.window_catalog = WindowCatalog()
        self.bubble = CameraBubble()
        self.bubble.stop_requested.connect(self.stop)
        self.bubble.pause_requested.connect(self.toggle_pause)
        self.bubble.zoom_requested.connect(self.toggle_zoom)
        self.bubble.open_requested.connect(self.reveal)
        self.bubble.moved.connect(self.move_camera_overlay)
        VIDEOS.mkdir(parents=True, exist_ok=True)
        STATE.mkdir(parents=True, exist_ok=True)
        self.upload_store = UploadStore(STATE / 'uploads.json')
        self.loom_account = {'status': 'unknown'}
        self._account_operation = None
        self.loom_probes = set()
        self._loom_check_paths = set()
        self._upload_output = ''
        self._upload_errors = ''
        self._upload_active = False
        self._title_job = None
        self.build()
        self.set_theme(self.prefs.value('theme', 'light'))
        self.setup_tray()
        self.restore_preferences()
        self.hotkeys = Hotkeys(self)
        self.hotkeys.toggle.connect(self.toggle_record)
        self.hotkeys.pause.connect(self.toggle_pause)
        self.hotkeys.zoom.connect(self.toggle_zoom)
        self.hotkeys.unavailable.connect(self.notice)
        self.hotkeys.start()
        QShortcut(QKeySequence('Escape'), self, activated=self.cancel_countdown)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        self.configure_timer = QTimer(self)
        self.configure_timer.setSingleShot(True)
        self.configure_timer.timeout.connect(self.configure)
        self.start_timer = QTimer(self)
        self.start_timer.setSingleShot(True)
        self.start_timer.timeout.connect(self.start)
        self.zoom_timer = QTimer(self)
        self.zoom_timer.setTimerType(Qt.PreciseTimer)
        self.zoom_timer.setInterval(16)
        self.zoom_timer.timeout.connect(self.animate_zoom)
        self.upload_timer = QTimer(self)
        self.upload_timer.setInterval(1000)
        self.upload_timer.timeout.connect(self.update_upload_elapsed)
        QTimer.singleShot(300, self.initialize)

    def build(self):
        from PySide6.QtWidgets import QScrollArea

        class RecordButton(QPushButton):
            def setText(self, text):
                super().setText(text)
                self.setProperty('stopping', text.startswith('■'))
                self.style().unpolish(self)
                self.style().polish(self)

        container = QWidget()
        self.pages = QStackedWidget()
        self.recorder_page = container
        self.pages.addWidget(container)
        self.setCentralWidget(self.pages)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(str(ICON)).pixmap(36, 36))
        header.addWidget(logo)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title_box.addWidget(label('Untangle', 'title'))
        title_box.addWidget(label('Screen and camera recording', 'muted'))
        header.addLayout(title_box)
        header.addStretch()
        self.theme_choice = QComboBox()
        self.theme_choice.setAccessibleName('Appearance')
        self.theme_choice.addItem('Light', 'light')
        self.theme_choice.addItem('Dark', 'dark')
        self.theme_choice.currentIndexChanged.connect(lambda: self.set_theme(self.theme_choice.currentData()))
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle('Settings')
        self.settings_dialog.resize(560, 640)
        settings_outer = QVBoxLayout(self.settings_dialog)
        settings_outer.setContentsMargins(24, 24, 24, 20)
        settings_outer.addWidget(label('Settings', 'title'))
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_body = QWidget()
        settings_scroll.setWidget(settings_body)
        settings_outer.addWidget(settings_scroll, 1)
        self.settings_layout = QVBoxLayout(settings_body)
        self.settings_layout.setContentsMargins(0, 12, 8, 12)
        self.settings_layout.setSpacing(12)
        self.settings_layout.addWidget(label('Appearance', 'section'))
        self.settings_layout.addWidget(self.theme_choice)
        self.settings_layout.addWidget(label('Recording names', 'section'))
        self.auto_titles = QCheckBox('Generate a name from the recording')
        self.auto_titles.setChecked(self.prefs.value('auto_titles', True, type=bool))
        self.auto_titles.toggled.connect(lambda value: self.prefs.setValue('auto_titles', value))
        self.settings_layout.addWidget(self.auto_titles)
        self.title_capability = label('', 'muted')
        self.title_capability.setWordWrap(True)
        self.settings_layout.addWidget(self.title_capability)
        title_privacy = label('Speech is transcribed on this computer. Codex receives transcript text to generate a title using Luna, Medium, Fast. The video stays local.', 'muted')
        title_privacy.setWordWrap(True)
        self.settings_layout.addWidget(title_privacy)
        settings_done = QPushButton('Done')
        settings_done.setAutoDefault(False)
        settings_done.setDefault(False)
        settings_done.clicked.connect(self.settings_dialog.accept)
        settings_outer.addWidget(settings_done, 0, Qt.AlignRight)
        self.settings_dialog.finished.connect(lambda _: self.save_preferences())
        self.sidebar_button = QPushButton('Sidebar')
        self.sidebar_button.setObjectName('quiet')
        self.sidebar_button.setCheckable(True)
        self.sidebar_button.setChecked(True)
        self.sidebar_button.setToolTip('Show or hide recording controls')
        self.sidebar_button.toggled.connect(self.set_sidebar_visible)
        header.addWidget(self.sidebar_button)
        self.settings_button = QPushButton('Settings')
        self.settings_button.setObjectName('quiet')
        self.settings_button.clicked.connect(self.open_settings)
        header.addWidget(self.settings_button)
        self.pause_button = QPushButton('Pause')
        self.pause_button.hide()
        self.pause_button.clicked.connect(self.toggle_pause)
        header.addWidget(self.pause_button)
        self.record_button = RecordButton('●  Start recording')
        self.record_button.setObjectName('record')
        self.record_button.setEnabled(False)
        self.record_button.setFixedWidth(190)
        self.record_button.clicked.connect(self.toggle_record)
        self.record_button.setMinimumHeight(36)
        header.addWidget(self.record_button)
        layout.addLayout(header)

        content = QGridLayout()
        self.recorder_content = content
        content.setHorizontalSpacing(20)
        content.setVerticalSpacing(10)
        content.setRowStretch(0, 1)
        content.setColumnStretch(0, 0)
        content.setColumnStretch(1, 1)
        controls = QVBoxLayout()
        controls.setSpacing(4)
        side = QWidget()
        side.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.controls_panel = QScrollArea()
        self.controls_panel.setObjectName('sidebar')
        self.controls_panel.setWidgetResizable(True)
        self.controls_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.controls_panel.setFixedWidth(276)
        self.controls_panel.setWidget(side)
        side.setLayout(controls)
        controls.setContentsMargins(0, 0, 10, 0)
        summary = controls
        summary.setContentsMargins(12, 12, 12, 12)
        summary.addWidget(label('Recording setup', 'section'))
        self.setup_sections = []

        def section(title, advanced=False):
            frame = QFrame()
            frame.setObjectName('setupSection')
            outer = QVBoxLayout(frame)
            outer.setContentsMargins(0, 4, 0, 4)
            outer.setSpacing(6)
            body = QWidget()
            body_layout = QVBoxLayout(body)
            body_layout.setContentsMargins(0, 0, 0, 0)
            body_layout.setSpacing(6)
            outer.addWidget(label('Recording' if advanced else title, 'section'))
            outer.addWidget(body)
            (self.settings_layout if advanced else summary).addWidget(frame)
            return body_layout

        controls = self.capture_setup = section('Record')
        modes = QHBoxLayout()
        self.screen_button = QPushButton('Screen')
        self.camera_button = QPushButton('◉  Camera')
        for button, mode in [(self.screen_button, 'screen'), (self.camera_button, 'camera')]:
            button.setCheckable(True)
            button.setObjectName('mode')
            button.setMinimumHeight(42)
            button.clicked.connect(lambda checked, m=mode: self.set_mode(m))
            modes.addWidget(button)
        controls.addLayout(modes)
        self.mode_hint = label('Your screen, with you in the corner.', 'muted')
        self.mode_hint.setWordWrap(True)
        controls.addWidget(self.mode_hint)
        controls.addSpacing(0)
        self.capture_label = label('Capture', 'section')
        controls.addWidget(self.capture_label)
        self.capture_kind = QComboBox()
        self.capture_kind.addItem('Entire screen', 'screen')
        self.capture_kind.addItem('A specific window', 'window')
        controls.addWidget(self.capture_kind)
        self.screen = QComboBox()
        for index, screen in enumerate(QApplication.screens()):
            geo = screen.geometry()
            ratio = screen.devicePixelRatio()
            self.screen.addItem(f'{screen.name()} · {round(geo.width() * ratio)} × {round(geo.height() * ratio)}', index)
        controls.addWidget(self.screen)
        self.window_row = QWidget()
        window_layout = QHBoxLayout(self.window_row)
        window_layout.setContentsMargins(0, 0, 0, 0)
        self.capture_window = QComboBox()
        self.capture_window.setMinimumWidth(0)
        self.capture_window.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.capture_window.addItem('Select a window…', None)
        window_layout.addWidget(self.capture_window, 1)
        self.refresh_button = QPushButton('↻')
        self.refresh_button.setFixedWidth(40)
        self.refresh_button.setToolTip('Refresh open windows')
        self.refresh_button.clicked.connect(self.refresh_windows)
        window_layout.addWidget(self.refresh_button)
        self.window_row.setVisible(False)
        controls.addWidget(self.window_row)
        controls = self.camera_setup = section('Camera')
        self.camera = QComboBox()
        self.camera.addItem('Camera off', None)
        for name, path in cameras():
            self.camera.addItem(name, path)
        if self.camera.count() > 1:
            self.camera.setCurrentIndex(1)
        camera_row = QHBoxLayout()
        camera_row.setSpacing(8)
        camera_row.addWidget(self.camera, 1)
        self.camera_toggle = QPushButton('On')
        self.camera_toggle.setCheckable(True)
        self.camera_toggle.setAccessibleName('Camera enabled')
        self.camera_toggle.setFixedWidth(48)
        self.camera_toggle.clicked.connect(self.toggle_camera)
        camera_row.addWidget(self.camera_toggle)
        controls.addLayout(camera_row)
        self.camera_settings_button = QPushButton('Picture settings')
        self.camera_settings_button.setAccessibleName('Camera picture settings')
        self.camera_settings_button.setToolTip('Brightness, contrast, exposure, white balance and focus')
        self.camera_settings_button.clicked.connect(self.open_camera_adjustments)
        controls.addWidget(self.camera_settings_button)
        self._last_camera_device = self.camera.currentData()
        controls = self.microphone_setup = section('Microphone')
        self.microphone = QComboBox()
        self.microphone.addItem('Automatic microphone', 'default')
        self.microphone.addItem('Microphone off', None)
        for name, source in microphones():
            self.microphone.addItem(name, source)
        controls.addWidget(self.microphone)
        self.audio_check_button = QPushButton('Quick audio check')
        self.audio_check_button.clicked.connect(self.open_audio_check)
        summary.addWidget(self.audio_check_button)
        self.live_microphone = QCheckBox('Live microphone levels')
        self.live_microphone.setChecked(True)
        self.live_microphone.setToolTip('Uses your microphone while the recorder is visible. Bluetooth headsets use hands-free audio. Turn off to release the microphone.')
        self.live_microphone.toggled.connect(lambda _: self.idle_audio.reconcile())
        self.settings_layout.addWidget(label('Audio', 'section'))
        self.settings_layout.addWidget(self.live_microphone)
        self.microphone_meter = MicrophoneMeter()
        self.clean_microphone = QCheckBox('Clean microphone')
        self.clean_microphone.setChecked(True)
        self.clean_microphone.setToolTip('Reduce background microphone noise and control loud peaks. Turn off to record the microphone without processing. Computer sound is unchanged.')
        self.desktop_audio = QCheckBox('Include computer sound')
        self.settings_layout.addWidget(self.desktop_audio)
        controls.addSpacing(4)

        self.widget_panel = QFrame()
        self.widget_panel.setObjectName('panel')
        widget_layout = QVBoxLayout(self.widget_panel)
        widget_layout.setContentsMargins(14, 12, 14, 14)
        widget_layout.setSpacing(9)
        widget_layout.addWidget(label('YOUR CAMERA WIDGET', 'eyebrow'))
        self.shape = QComboBox()
        for name, value in [('Circle', 'circle'), ('Rounded square', 'rounded'), ('Square', 'square'), ('Custom shape…', 'custom')]:
            self.shape.addItem(name, value)
        widget_layout.addWidget(self.shape)
        size_row = QHBoxLayout()
        size_row.addWidget(label('Size', 'muted'))
        self.size = QSlider(Qt.Horizontal)
        self.size.setRange(12, 42)
        self.size.setValue(23)
        size_row.addWidget(self.size)
        widget_layout.addLayout(size_row)
        self.position = QComboBox()
        for name, value in [('Bottom right', 'bottom-right'), ('Bottom left', 'bottom-left'), ('Top right', 'top-right'), ('Top left', 'top-left')]:
            self.position.addItem(name, value)
        widget_layout.addWidget(self.position)
        self.mask_button = QPushButton('Choose shape image…')
        self.mask_button.setVisible(False)
        self.mask_button.clicked.connect(self.choose_mask)
        widget_layout.addWidget(self.mask_button)
        self.mirror = QCheckBox('Mirror my camera')
        self.mirror.setChecked(True)
        controls = self.output_setup = section('More options', advanced=True)
        controls.addWidget(self.widget_panel)
        controls.addWidget(self.mirror)
        controls.addWidget(self.clean_microphone)
        controls.addWidget(label('Recording quality', 'muted'))
        quality_row = QHBoxLayout()
        self.quality = QComboBox()
        self.quality.addItem('4K · 30 fps', (3840, 2160))
        self.quality.addItem('1080p · 30 fps', (1920, 1080))
        quality_row.addWidget(self.quality)
        controls.addLayout(quality_row)
        content.addWidget(self.controls_panel, 0, 0)

        right = QVBoxLayout()
        right.setSpacing(6)
        preview_top = QHBoxLayout()
        self.preview_title = label('Camera preview', 'section')
        preview_top.addWidget(self.preview_title)
        self.focus_button = QPushButton('Expand camera')
        self.focus_button.setCheckable(True)
        self.focus_button.toggled.connect(self.focus_camera)
        preview_top.addWidget(self.focus_button)
        preview_top.addStretch()
        self.encoder_label = label('Starting recording engine…', 'muted')
        self.encoder_label.setWordWrap(True)
        right.addLayout(preview_top)
        self.capture_caption = label('', 'muted')
        self.capture_caption.setWordWrap(True)
        self.capture_caption.hide()
        canvas_row = QHBoxLayout()
        canvas_row.addWidget(label('Canvas', 'muted'))
        self.canvas = QComboBox()
        self.canvas.setAccessibleName('Recording canvas')
        for title, value in [('Landscape · 16:9', 'landscape'), ('Reels / Shorts · 9:16', 'portrait'),
                             ('Square · 1:1', 'square'), ('Portrait · 4:5', 'portrait45'),
                             ('Raw · source size', 'raw')]:
            self.canvas.addItem(title, value)
        canvas_row.addWidget(self.canvas, 1)
        self.framing = QComboBox(self)
        self.framing.setAccessibleName('Source framing')
        self.framing.addItem('Fit · whole image', 'fit')
        self.framing.addItem('Fill · crop center', 'fill')
        self.framing.setToolTip('Fit keeps the whole source with black bars. Fill crops the center to cover the canvas. Camera widgets always crop to a square.')
        self.framing.hide()
        self.canvas_panel = QWidget()
        canvas_row.setContentsMargins(0, 0, 0, 0)
        self.canvas_panel.setLayout(canvas_row)
        right.addWidget(self.canvas_panel)
        self.camera_zoom_panel = QWidget()
        camera_zoom_layout = QVBoxLayout(self.camera_zoom_panel)
        camera_zoom_layout.setContentsMargins(0, 0, 0, 0)
        camera_zoom_layout.setSpacing(12)
        camera_zoom_header = QHBoxLayout()
        camera_zoom_header.addWidget(label('Zoom', 'muted'))
        camera_zoom_header.addStretch()
        camera_zoom_row = QHBoxLayout()
        camera_zoom_row.setSpacing(4)
        self.camera_zoom_minus = QPushButton('−')
        self.camera_zoom_plus = QPushButton('+')
        for button, name, step in ((self.camera_zoom_minus, 'Zoom camera out', -10),
                                   (self.camera_zoom_plus, 'Zoom camera in', 10)):
            button.setObjectName('cameraZoomStep')
            button.setAccessibleName(name)
            button.setToolTip(name + ' by 10%')
            button.setFixedWidth(28)
            button.setAutoRepeat(True)
            button.clicked.connect(lambda checked=False, amount=step:
                self.camera_zoom.setValue(self.camera_zoom.value() + amount))
        camera_zoom_row.addWidget(self.camera_zoom_minus)
        self.camera_zoom = QSlider(Qt.Horizontal)
        self.camera_zoom.setAccessibleName('Camera framing zoom')
        self.camera_zoom.setRange(100, 300)
        self.camera_zoom.setSingleStep(10)
        self.camera_zoom.setPageStep(25)
        self.camera_zoom.setToolTip('Center crop your camera from 100% to 300%. Camera widget size and pointer zoom are separate.')
        camera_zoom_row.addWidget(self.camera_zoom, 1)
        camera_zoom_row.addWidget(self.camera_zoom_plus)
        self.camera_zoom_value = label('100%')
        self.camera_zoom_value.setMinimumWidth(42)
        camera_zoom_header.addWidget(self.camera_zoom_value)
        camera_zoom_header.addSpacing(16)
        self.camera_zoom_reset = QPushButton('Reset')
        self.camera_zoom_reset.setObjectName('cameraZoomReset')
        self.camera_zoom_reset.setAccessibleName('Reset camera zoom')
        self.camera_zoom_reset.clicked.connect(lambda: self.camera_zoom.setValue(100))
        camera_zoom_header.addWidget(self.camera_zoom_reset)
        camera_zoom_layout.addLayout(camera_zoom_header)
        camera_zoom_layout.addLayout(camera_zoom_row)
        self.camera_setup.addWidget(self.camera_zoom_panel)
        self.canvas_note = self.capture_caption
        self.preview = Preview()
        self.preview.resized.connect(self.resize_preview)
        self.preview_frame = CanvasPreview(self.preview)
        right.addWidget(self.preview_frame, 1)
        right.addWidget(self.microphone_meter)
        self.source_note = label('4K output · source detail depends on your display and camera.', 'muted')
        self.source_note.setWordWrap(True)
        self.output_setup.addWidget(self.source_note)
        zoom_row = QHBoxLayout()
        self.zoom_button = QPushButton('⌖  Zoom to pointer')
        self.zoom_button.setCheckable(True)
        self.zoom_button.setEnabled(False)
        self.zoom_button.setToolTip('While recording, press Ctrl + Shift + F8 to zoom in or out at your pointer.')
        self.zoom_button.clicked.connect(self.toggle_zoom)
        zoom_row.addStretch()
        zoom_row.addWidget(self.zoom_button)
        self.zoom_amount = QComboBox()
        for title, value in [('1.5×', 1.5), ('2×', 2.0), ('2.5×', 2.5)]:
            self.zoom_amount.addItem(title, value)
        self.zoom_amount.setCurrentIndex(1)
        zoom_row.addWidget(self.zoom_amount)
        right.addLayout(zoom_row)
        self.status = label('Preparing your recording setup…')
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(38)
        right.addWidget(self.status)
        self.cancel_title_button = QPushButton('Name manually')
        self.cancel_title_button.hide()
        self.cancel_title_button.clicked.connect(self.cancel_automatic_title)
        right.addWidget(self.cancel_title_button, 0, Qt.AlignLeft)
        self.upload_panel = QFrame()
        self.upload_panel.setObjectName('panel')
        upload_layout = QVBoxLayout(self.upload_panel)
        upload_layout.setContentsMargins(12, 10, 12, 10)
        upload_layout.setSpacing(6)
        self.upload_heading = label('Upload to Loom', 'section')
        upload_layout.addWidget(self.upload_heading)
        self.upload_detail = label('Your local recording stays on this computer.', 'muted')
        self.upload_detail.setWordWrap(True)
        self.upload_detail.setTextFormat(Qt.PlainText)
        upload_layout.addWidget(self.upload_detail)
        self.upload_link = label('', 'muted')
        self.upload_link.setTextFormat(Qt.PlainText)
        self.upload_link.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.upload_link.setWordWrap(True)
        upload_layout.addWidget(self.upload_link)
        self.upload_progress = QProgressBar()
        self.upload_progress.setAccessibleName('Loom upload progress')
        self.upload_progress.setFixedHeight(12)
        self.upload_progress.setTextVisible(False)
        upload_layout.addWidget(self.upload_progress)
        upload_actions = QHBoxLayout()
        self.upload_open = QPushButton('Open in Loom ↗')
        self.upload_open.clicked.connect(self.open_uploaded_video)
        self.upload_copy = QPushButton('Copy Loom link')
        self.upload_copy.clicked.connect(self.copy_uploaded_link)
        self.upload_retry = QPushButton('Retry upload')
        self.upload_retry.clicked.connect(self.retry_upload)
        self.upload_library = QPushButton('Recordings')
        self.upload_library.clicked.connect(lambda: self.open_recordings(getattr(self, '_upload_file', None)))
        for button in (self.upload_open, self.upload_copy, self.upload_retry, self.upload_library):
            upload_actions.addWidget(button)
        upload_layout.addLayout(upload_actions)
        self.upload_panel.hide()
        right.addWidget(self.upload_panel)
        shortcuts = self.shortcuts = label('Ctrl+Shift+F9  record / stop  ·  Ctrl+Shift+F10  pause  ·  Ctrl+Shift+F8  zoom', 'muted')
        shortcuts.setWordWrap(True)
        right.addWidget(shortcuts)
        summary.addStretch()
        # Device/window labels must not set the scroll content's minimum width.
        # Qt then resizes it to the viewport, including the vertical scrollbar.
        for combo in side.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.zoom_amount.setMinimumContentsLength(3)
        self.zoom_amount.setMaximumWidth(90)
        self.preview_column = right
        content.addLayout(right, 0, 1, 2, 1)
        self.navigation_footer = QWidget()
        self.navigation_footer.setFixedWidth(276)
        navigation = QHBoxLayout(self.navigation_footer)
        navigation.setContentsMargins(0, 0, 10, 0)
        navigation.setSpacing(6)
        self.library_button = QPushButton('Recordings')
        self.library_button.clicked.connect(lambda: self.open_recordings())
        self.sharing_button = QPushButton('Sharing')
        self.sharing_button.clicked.connect(self.sharing_settings)
        for button in (self.library_button, self.sharing_button):
            button.setObjectName('footerNavigation')
            navigation.addWidget(button, 1)
        content.addWidget(self.navigation_footer, 1, 0, Qt.AlignLeft | Qt.AlignBottom)
        layout.addLayout(content, 1)
        self.config_controls = [self.screen_button, self.camera_button, self.capture_kind, self.capture_window, self.refresh_button, self.screen, self.camera, self.camera_toggle, self.microphone, self.clean_microphone, self.desktop_audio, self.shape, self.size, self.position, self.mask_button, self.mirror, self.quality, self.canvas, self.framing, self.camera_zoom, self.camera_zoom_reset, self.camera_zoom_minus, self.camera_zoom_plus, self.camera_settings_button]
        for combo in (self.screen, self.capture_window, self.microphone):
            combo.currentIndexChanged.connect(self.schedule_configure)
        self.camera.currentIndexChanged.connect(self.camera_changed)
        self.capture_kind.currentIndexChanged.connect(self.capture_changed)
        self.shape.currentIndexChanged.connect(self.shape_changed)
        self.size.valueChanged.connect(self.camera_size_changed)
        self.position.currentIndexChanged.connect(self.camera_position_changed)
        self.mirror.toggled.connect(self.camera_mirror_changed)
        self.clean_microphone.toggled.connect(self.schedule_configure)
        self.desktop_audio.toggled.connect(self.schedule_configure)
        self.quality.currentIndexChanged.connect(self.quality_changed)
        self.canvas.currentIndexChanged.connect(self.canvas_changed)
        self.framing.currentIndexChanged.connect(self.camera_framing_changed)
        self.framing.activated.connect(self.framing_selected)
        self.camera_zoom.valueChanged.connect(self.camera_zoom_changed)
        self.set_mode('screen', configure=False)
        for combo in (self.screen, self.capture_window, self.capture_kind, self.camera, self.microphone):
            combo.currentIndexChanged.connect(self.update_setup_summary)

    def open_settings(self):
        if self.busy or self.recording or self.counting:
            return
        available, reason = local_title_capability()
        self.title_capability.setText('Local transcription is ready. Codex access is checked when naming a recording.' if available else reason)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def set_sidebar_visible(self, visible):
        if not hasattr(self, 'controls_panel'):
            return
        self.controls_panel.setVisible(visible and not self.focus_button.isChecked())
        self.navigation_footer.setVisible(visible)
        self.sidebar_button.setText('Hide sidebar' if visible else 'Show sidebar')
        self.prefs.setValue('sidebar_visible', visible)

    def set_theme(self, name):
        name = name if name in ('light', 'dark') else 'light'
        apply_theme(QApplication.instance(), name)
        self.theme_choice.blockSignals(True)
        self.theme_choice.setCurrentIndex(self.theme_choice.findData(name))
        self.theme_choice.blockSignals(False)
        self.prefs.setValue('theme', name)
        if self.recordings and hasattr(self.recordings, 'theme_choice'):
            self.recordings.theme_choice.blockSignals(True)
            self.recordings.theme_choice.setCurrentIndex(self.recordings.theme_choice.findData(name))
            self.recordings.theme_choice.blockSignals(False)

    def update_setup_summary(self, *_):
        if not hasattr(self, 'capture_caption'):
            return
        capture = ('Camera only' if self.mode == 'camera' else
            self.capture_kind.currentText() + ' · ' +
            (self.capture_window.currentText() if self.capture_kind.currentData() == 'window' else self.screen.currentText()))
        width, height = self.output_dimensions()
        if hasattr(self, 'preview_frame'):
            self.preview_frame.set_canvas(width, height)
        self.capture_caption.setText(f'{capture} · {width} × {height}')
        self.capture_caption.setToolTip(f'{capture} · {width} × {height} · 30 fps')
        self.preview_title.setText(f'{"Camera" if self.mode == "camera" else "Screen"} · {width} × {height}')
        self.preview_title.setToolTip(self.capture_caption.toolTip())
        self.camera_zoom_value.setText(f'{self.camera_zoom.value()}%')
        self.update_camera_controls()
        for combo in (self.camera, self.microphone, self.screen, self.capture_window):
            combo.setToolTip(combo.currentText())

    def output_dimensions(self):
        if self.mode == 'camera' and self.canvas.currentData() == 'raw':
            dimensions = getattr(self.engine, '_camera_dimensions', None) if self.engine else None
            if (isinstance(dimensions, tuple) and len(dimensions) == 2
                    and all(type(n) is int and n >= 16 for n in dimensions)):
                return dimensions[0] // 4 * 4, dimensions[1] // 2 * 2
            return self.quality.currentData()
        return (canvas_dimensions(self.quality.currentData(), self.canvas.currentData())
                if self.mode == 'camera' else self.quality.currentData())

    def effective_framing(self):
        if self.canvas.currentData() == 'raw':
            return 'fit'
        return self.framing.currentData() if self.mode == 'camera' else 'fit'

    def recommended_framing(self):
        return 'fill' if self.mode == 'camera' and self.canvas.currentData() not in ('landscape', 'raw') else 'fit'

    def select_default_framing(self):
        self._framing_explicit = False
        self.framing.blockSignals(True)
        self.framing.setCurrentIndex(self.framing.findData(self.recommended_framing()))
        self.framing.blockSignals(False)

    def canvas_changed(self):
        if self.recording or self.busy or self.counting:
            return
        if self.mode != 'camera':
            self.update_setup_summary()
            return
        self.select_default_framing()
        self.quality_changed()

    def framing_selected(self):
        self._framing_explicit = True
        self.save_preferences()

    def update_camera_controls(self):
        enabled = bool(self.camera.currentData()) and not (self.recording or self.busy or self.counting)
        camera_on = bool(self.camera.currentData())
        self.camera_toggle.setChecked(camera_on)
        self.camera_toggle.setText('On' if camera_on else 'Off')
        self.camera_toggle.setToolTip('Turn camera off' if camera_on else 'Turn camera on')
        self.camera_toggle.setEnabled(self.camera.count() > 1 and not (self.recording or self.busy or self.counting))
        self.camera_zoom.setEnabled(enabled)
        self.camera_settings_button.setEnabled(enabled)
        self.camera_zoom_minus.setEnabled(enabled and self.camera_zoom.value() > 100)
        self.camera_zoom_plus.setEnabled(enabled and self.camera_zoom.value() < 300)
        self.camera_zoom_reset.setEnabled(enabled and self.camera_zoom.value() != 100)

    def toggle_camera(self, enabled):
        if self.recording or self.busy or self.counting:
            self.update_camera_controls()
            return
        if not enabled:
            self.camera.setCurrentIndex(0)
        else:
            index = self.camera.findData(self._last_camera_device) if self._last_camera_device else -1
            if index <= 0:
                index = 1 if self.camera.count() > 1 else 0
            self.camera.setCurrentIndex(index)

    def camera_changed(self):
        if self.camera.currentData():
            self._last_camera_device = self.camera.currentData()
        self.schedule_configure()
        if (not self.camera.currentData() and self.engine and not self.in_library()
                and not (self.recording or self.busy or self.counting)):
            self.configure_timer.stop()
            self.configure()

    def apply_camera_framing(self, **changes):
        self.update_setup_summary()
        if self.in_library():
            self._configure_pending = True
            self.configuration_valid = False
            return
        if (not self.engine or not self.configuration_valid or not self.camera.currentData()
                or self.in_library() or self.recording or self.busy or self.counting):
            return
        try:
            self.engine.set_camera_framing(**changes)
            self.save_preferences()
        except Exception as exc:
            self._live_update_failed = True
            self.configuration_valid = False
            self.record_button.setEnabled(False)
            self.notice(f'Could not update camera framing: {exc}')

    def camera_zoom_changed(self):
        self.apply_camera_framing(camera_zoom=self.camera_zoom.value() / 100)

    def camera_framing_changed(self):
        self.apply_camera_framing(framing=self.effective_framing())

    def arrange_camera_bubble(self):
        if (self.mode != 'screen' or not self.bubble.isVisible() or not self.engine
                or self.recording or self.busy or self.counting):
            return
        screen = QApplication.screens()[self.screen.currentIndex()]
        self.bubble.arrange(screen, self.size.value() / 100, self.position.currentData(),
            self.shape.currentData(), self.mask_path,
            mirror_mask=self.capture_kind.currentData() == 'window' and self.mirror.isChecked())
        ratio = self.bubble.devicePixelRatioF()
        self.engine.resize_camera_preview(round(self.bubble.width() * ratio), round(self.bubble.height() * ratio))

    def camera_size_changed(self):
        self.apply_camera_framing(size=self.size.value() / 100)
        self.arrange_camera_bubble()

    def camera_position_changed(self):
        self.apply_camera_framing(position=self.position.currentData())
        self.arrange_camera_bubble()

    def camera_mirror_changed(self):
        self.apply_camera_framing(mirror=self.mirror.isChecked())
        if self.bubble.isVisible() and not (self.recording or self.busy or self.counting):
            self.bubble.apply_shape(self.shape.currentData(), self.mask_path,
                mirror_mask=self.capture_kind.currentData() == 'window' and self.mirror.isChecked())

    def uses_floating_camera(self):
        # A desktop bubble is captured by XShm, so it follows screen cropping.
        # Screen view always uses landscape Fit. A remembered camera-only
        # canvas must not alter the desktop bubble's recording path.
        return (self.mode == 'screen' and bool(self.camera.currentData())
                and self.capture_kind.currentData() == 'screen')

    def setup_tray(self):
        self.tray = QSystemTrayIcon(QIcon(str(ICON)), self)
        self.tray.setToolTip('Untangle · Ready to record')
        menu = QMenu()
        menu.addAction('Open Untangle', self.reveal)
        self.tray_record = menu.addAction('Start recording', self.toggle_record)
        self.tray_pause = menu.addAction('Pause', self.toggle_pause)
        self.tray_pause.setEnabled(False)
        self.tray_zoom = menu.addAction('Zoom to pointer · Ctrl+Shift+F8', self.toggle_zoom)
        self.tray_zoom.setEnabled(False)
        menu.addSeparator()
        menu.addAction('Quit Untangle', self.close)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.reveal() if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.show()

    def restore_preferences(self):
        for name in ('camera', 'microphone', 'shape', 'position', 'quality'):
            widget = getattr(self, name)
            saved = self.prefs.value(name)
            if saved is not None:
                index = widget.findText(str(saved))
                if index >= 0:
                    widget.setCurrentIndex(index)
        if self.prefs.contains('microphone_id'):
            source = self.prefs.value('microphone_id') or None
            index = self.microphone.findData(source)
            if index < 0:
                self.microphone.addItem('Unavailable microphone: ' + source, source)
                index = self.microphone.count() - 1
            self.microphone.setCurrentIndex(index)
        self.size.setValue(int(self.prefs.value('size', 23)))
        self.mirror.setChecked(self.prefs.value('mirror', True, type=bool))
        self.clean_microphone.setChecked(self.prefs.value('clean_microphone', True, type=bool))
        self.desktop_audio.setChecked(self.prefs.value('desktop_audio', False, type=bool))
        self.live_microphone.setChecked(self.prefs.value('live_microphone', True, type=bool))
        for name, default in (('canvas', 'landscape'), ('framing', 'fit')):
            widget = getattr(self, name)
            widget.blockSignals(True)
            widget.setCurrentIndex(max(0, widget.findData(self.prefs.value(name, default))))
            widget.blockSignals(False)
        self._framing_explicit = self.prefs.value('framing_explicit', False, type=bool)
        try:
            zoom = int(self.prefs.value('camera_zoom', 100))
        except (TypeError, ValueError, OverflowError):
            zoom = 100
        self.camera_zoom.setValue(max(100, min(300, zoom)))
        self.set_mode(self.prefs.value('mode', 'camera'), configure=False)
        self.sidebar_button.setChecked(self.prefs.value('sidebar_visible', True, type=bool))
        self.set_sidebar_visible(self.sidebar_button.isChecked())
        # The first canvas release saved the inherited Fit as if it were a user
        # choice. Correct that camera-preset default once; later explicit Fit
        # choices are tagged and survive restarts.
        if (not self.prefs.contains('framing_explicit') and self.mode == 'camera'
                and self.canvas.currentData() not in ('landscape', 'raw') and self.framing.currentData() == 'fit'):
            self.select_default_framing()
            self.update_setup_summary()
        files = recording_files(VIDEOS)
        if files:
            self.set_last(files[0])

    def save_preferences(self):
        self.prefs.setValue('live_microphone', self.live_microphone.isChecked())
        for name in ('camera', 'microphone', 'shape', 'position', 'quality'):
            self.prefs.setValue(name, getattr(self, name).currentText())
        self.prefs.setValue('microphone_id', self.microphone.currentData() or '')
        self.prefs.setValue('size', self.size.value())
        self.prefs.setValue('mirror', self.mirror.isChecked())
        self.prefs.setValue('clean_microphone', self.clean_microphone.isChecked())
        self.prefs.setValue('desktop_audio', self.desktop_audio.isChecked())
        self.prefs.setValue('canvas', self.canvas.currentData())
        self.prefs.setValue('framing', self.framing.currentData())
        self.prefs.setValue('framing_explicit', self._framing_explicit)
        self.prefs.setValue('camera_zoom', self.camera_zoom.value())
        self.prefs.setValue('mode', self.mode)
        self.prefs.setValue('mask', self.mask_path)
        self.prefs.sync()

    def initialize(self):
        if self._closing or self.in_library() or self.engine:
            return
        try:
            if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
                raise RuntimeError('This version needs an X11 session. Sign in with an Xorg session to record.')
            from .engine import Engine
            w, h = self.output_dimensions()
            self.engine = Engine(int(self.preview.winId()), w, h, fps=30)
            self.resize_preview(self.preview.width(), self.preview.height())
            self.configure()
        except Exception as exc:
            self.notice(f'Could not start the recording engine: {exc}')
            self.encoder_label.setText('Engine unavailable')
            self.record_button.setEnabled(False)

    def quality_changed(self):
        self.update_setup_summary()
        if self.recording or self.busy or self.counting:
            return
        if self.in_library():
            self._configure_pending = True
            self.configuration_valid = False
            return
        # A canvas retry can recover a failed live edit, but cannot validate a
        # pending device change or a source configuration that never succeeded.
        if (not self.engine or self.in_library() or self._configure_pending
                or not (self.configuration_valid or getattr(self, '_live_update_failed', False))):
            return
        try:
            self.engine.set_canvas(*self.output_dimensions())
            if self.camera.currentData():
                self.engine.set_camera_framing(framing=self.effective_framing(),
                    camera_zoom=self.camera_zoom.value() / 100,
                    size=self.size.value() / 100, mirror=self.mirror.isChecked())
            self._live_update_failed = False
            self.configuration_valid = True
            self.record_button.setEnabled(True)
            self.save_preferences()
        except Exception as exc:
            self._live_update_failed = True
            self.configuration_valid = False
            self.record_button.setEnabled(False)
            self.notice(f'Could not update the recording canvas: {exc}')

    def set_mode(self, mode, configure=True):
        if self.recording or self.busy or self.counting:
            return
        self.mode = mode if mode in ('screen', 'camera') else 'screen'
        if configure and self.mode == 'camera' and not self._framing_explicit:
            self.select_default_framing()
        self.configuration_valid = False
        self.screen_button.setChecked(self.mode == 'screen')
        self.camera_button.setChecked(self.mode == 'camera')
        camera_mode = self.mode == 'camera'
        self.canvas_panel.setVisible(camera_mode and not self.focus_button.isChecked())
        self.focus_button.setVisible(camera_mode)
        if not camera_mode:
            self.focus_button.setChecked(False)
        self.preview_title.setText('Camera preview' if camera_mode else 'Screen preview')
        self.capture_label.setVisible(not camera_mode)
        self.capture_kind.setVisible(not camera_mode)
        self.screen.setVisible(not camera_mode and self.capture_kind.currentData() == 'screen')
        self.window_row.setVisible(not camera_mode and self.capture_kind.currentData() == 'window')
        self.zoom_button.setVisible(not camera_mode)
        self.zoom_amount.setVisible(not camera_mode)
        self.widget_panel.setVisible(self.mode == 'screen')
        self.screen.setEnabled(self.mode == 'screen')
        self.capture_kind.setEnabled(self.mode == 'screen')
        self.capture_window.setEnabled(self.mode == 'screen')
        self.refresh_button.setEnabled(self.mode == 'screen')
        self.mode_hint.setText('Screen + optional camera.' if self.mode == 'screen' else 'Camera only, in your canvas.')
        self.update_setup_summary()
        if configure:
            self.schedule_configure()

    def focus_camera(self, expanded):
        self.controls_panel.setVisible(not expanded and self.sidebar_button.isChecked())
        self.navigation_footer.setVisible(self.sidebar_button.isChecked())
        self.canvas_panel.setVisible(self.mode == 'camera' and not expanded)
        self.recorder_content.removeItem(self.preview_column)
        if expanded:
            self.recorder_content.addLayout(self.preview_column, 0, 0, 1, 2)
        else:
            self.recorder_content.addLayout(self.preview_column, 0, 1, 2, 1)
        self.focus_button.setText('Show controls' if expanded else 'Expand camera')

    def capture_changed(self):
        window_mode = self.capture_kind.currentData() == 'window'
        self.screen.setVisible(self.mode == 'screen' and not window_mode)
        self.window_row.setVisible(self.mode == 'screen' and window_mode)
        if window_mode:
            self.refresh_windows()
        self.schedule_configure()

    def refresh_windows(self):
        previous = self.capture_window.currentData()
        self.capture_window.blockSignals(True)
        self.capture_window.clear()
        try:
            windows = self.window_catalog.list()
            for title, wid in windows:
                self.capture_window.addItem(title, wid)
            if not windows:
                self.capture_window.addItem('No open windows. Open one, then refresh.', None)
            index = self.capture_window.findData(previous)
            self.capture_window.setCurrentIndex(max(0, index))
            self.capture_window.setToolTip(self.capture_window.currentText())
        except Exception as exc:
            self.capture_window.addItem('Window list unavailable', None)
            if hasattr(self, 'status'):
                self.notice(f'Could not list windows: {exc}')
        finally:
            self.capture_window.blockSignals(False)
        self.schedule_configure()

    def shape_changed(self):
        custom = self.shape.currentData() == 'custom'
        self.mask_button.setVisible(custom)
        if custom and not self.mask_path and self.engine:
            self.choose_mask()
        self.schedule_configure()

    def choose_mask(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose a camera shape. White/opaque areas keep your image.', str(Path.home()), 'Shape images (*.png *.webp *.bmp)')
        if path:
            self.mask_path = path
            self.mask_button.setText(Path(path).name)
            self.schedule_configure()
        elif not self.mask_path:
            self.shape.setCurrentIndex(0)

    def schedule_configure(self, *_):
        self.update_setup_summary()
        if hasattr(self, 'configure_timer') and self.engine and not (self.recording or self.busy or self.counting):
            self.configuration_valid = False
            self.record_button.setEnabled(False)
            self._live_update_failed = False
            self._configure_pending = True
            self.configure_timer.start(180)

    def configure(self, microphone=None, recording_setup=False):
        if not recording_setup:
            key = (self.microphone.currentData(), self.clean_microphone.isChecked())
            if self.idle_audio.source and self.idle_audio.key != key:
                self.idle_audio.stop()
            microphone = self.idle_audio.source
        if self.in_library() or not self.engine or self.recording or (self.busy and not recording_setup):
            return
        self._configure_pending = False
        self._live_update_failed = False
        self.configuration_valid = False
        try:
            self.hide_bubble()
            camera = self.camera.currentData()
            window_id = self.capture_window.currentData() if self.capture_kind.currentData() == 'window' and self.mode == 'screen' else None
            if self.mode == 'screen' and self.capture_kind.currentData() == 'window':
                if not window_id or not self.window_catalog.geometry(window_id):
                    raise ValueError('Select an open window. Refresh the list if needed.')
            if self.mode == 'camera' and not camera:
                self.engine.clear_video()
                self.save_preferences()
                self.notice('Camera off. Turn it on to record in Camera mode.')
                return
            self.engine.set_canvas(*self.output_dimensions())
            self.engine.configure(mode=self.mode, camera=camera, microphone=microphone,
                microphone_processing=self.clean_microphone.isChecked(),
                desktop_audio=recording_setup and self.desktop_audio.isChecked(), shape=self.shape.currentData(),
                mask_path=self.mask_path or None, size=self.size.value() / 100,
                position=self.position.currentData(), screen=self.screen.currentData() or 0,
                mirror=self.mirror.isChecked(), floating_camera=self.uses_floating_camera(), window_id=window_id,
                camera_zoom=self.camera_zoom.value() / 100, framing=self.effective_framing())
            if self.mode == 'camera' and self.canvas.currentData() == 'raw':
                self.engine.set_canvas(*self.output_dimensions())
                self.update_setup_summary()
            if self.mode == 'screen' and camera and (self.uses_floating_camera() or window_id):
                self.show_bubble()
            self.restore_camera_image(camera)
            self.record_button.setEnabled(True)
            self.configuration_valid = True
            self.engine_notice('Setup selected. Microphone readiness is checked before recording.')
            self.encoder_label.setText('Recording engine ready')
            screen = QApplication.screens()[self.screen.currentIndex()]
            geo = screen.geometry()
            ratio = screen.devicePixelRatio()
            width, height = self.output_dimensions()
            output = f'{width} × {height} · 30 fps'
            self.source_note.setText(f'{output} output · Display source {round(geo.width() * ratio)} × {round(geo.height() * ratio)}. '
                + ('Source resolution determines actual detail.' if camera else 'Camera is off.'))
            if self.mode == 'camera':
                self.source_note.setText(f'{self.camera.currentText()} · {output} output · Camera zoom {self.camera_zoom.value()}%.')
            if window_id:
                self.source_note.setText(f'{output} · Recording only the selected window. Keep it open and unminimized.')
            self.save_preferences()
        except Exception as exc:
            self.record_button.setEnabled(False)
            self.notice(f'Check your setup: {exc}')

    def resize_preview(self, width, height):
        if self.engine:
            ratio = self.preview.devicePixelRatioF()
            self.engine.resize_preview(round(width * ratio), round(height * ratio))

    def show_bubble(self):
        screen = QApplication.screens()[self.screen.currentIndex()]
        self.bubble.arrange(screen, self.size.value() / 100, self.position.currentData(), self.shape.currentData(), self.mask_path,
            mirror_mask=self.capture_kind.currentData() == 'window' and self.mirror.isChecked())
        self.bubble.recording = self.recording
        self.bubble.show()
        try:
            self.engine.attach_bubble(self.bubble)
        except Exception:
            self.bubble.hide()
            raise

    def hide_bubble(self):
        if self.engine:
            self.engine.detach_camera_preview()
        self.bubble.hide()

    def move_camera_overlay(self):
        if self.engine and self.mode == 'screen' and self.capture_kind.currentData() == 'window':
            bounds = QApplication.screens()[self.screen.currentIndex()].availableGeometry()
            dx = max(1, bounds.width() - self.bubble.width())
            dy = max(1, bounds.height() - self.bubble.height())
            self.engine.set_camera_position((self.bubble.x() - bounds.left()) / dx, (self.bubble.y() - bounds.top()) / dy)

    def toggle_zoom(self, *_):
        if not self.recording or self.busy or self.mode != 'screen':
            self.zoom_button.setChecked(False)
            return
        self.zoom_motion.enabled = not self.zoom_motion.enabled
        self.zoom_motion.last_time = time.monotonic()
        self.zoom_button.setChecked(self.zoom_motion.enabled)
        self.zoom_button.setText('⌖  Zoom out' if self.zoom_motion.enabled else '⌖  Zoom to pointer')
        self.bubble.zoomed = self.zoom_motion.enabled
        self.tray_zoom.setText('Zoom out · Ctrl+Shift+F8' if self.zoom_motion.enabled else 'Zoom to pointer · Ctrl+Shift+F8')
        self.zoom_timer.start()

    def animate_zoom(self):
        if not self.engine or not self.recording or self.busy or self.mode != 'screen':
            self.zoom_timer.stop()
            return
        if self.paused:
            self.zoom_motion.last_time = time.monotonic()
            return
        screen = QApplication.screens()[self.screen.currentIndex()]
        bounds = screen.geometry()
        pointer = QCursor.pos()
        x, y = self.zoom_motion.x, self.zoom_motion.y
        if bounds.contains(pointer):
            x = (pointer.x() - bounds.left()) / bounds.width()
            y = (pointer.y() - bounds.top()) / bounds.height()
        if self.capture_kind.currentData() == 'window':
            geometry = self.window_catalog.geometry(self.capture_window.currentData())
            if not geometry:
                return  # The recording health check will save if the target closes.
            px, py = self.window_catalog.pointer()
            wx, wy, width, height = geometry
            if wx <= px < wx + width and wy <= py < wy + height:
                x, y = (px - wx) / width, (py - wy) / height
            else:
                x, y = self.zoom_motion.x, self.zoom_motion.y
        try:
            factor, x, y = self.zoom_motion.step(self.zoom_amount.currentData(), x, y)
            self.engine.set_screen_zoom(factor, x, y)
            if not self.zoom_motion.enabled and factor == 1.0:
                self.zoom_timer.stop()
        except Exception as exc:
            self.zoom_timer.stop()
            self.notice(f'Pointer zoom stopped: {exc}')

    def reset_zoom(self):
        self.zoom_timer.stop()
        self.zoom_motion.reset()
        self.zoom_button.setChecked(False)
        self.zoom_button.setEnabled(False)
        self.zoom_button.setText('⌖  Zoom to pointer')
        self.tray_zoom.setEnabled(False)
        self.tray_zoom.setText('Zoom to pointer · Ctrl+Shift+F8')
        self.bubble.zoomed = False
        if self.engine:
            self.engine.set_screen_zoom(1.0, .5, .5)

    def toggle_record(self):
        if self.in_library():
            return
        if self.recording:
            self.stop()
        elif self.counting:
            self.cancel_countdown()
        elif self.engine and not self.busy and self.record_button.isEnabled():
            self.counting = True
            self.countdown = 3
            self.lock_controls(True)
            self.record_button.setText('Cancel · 3')
            self.notice('Starting in 3… Get your explanation ready. Esc cancels.')
            self.count_timer = QTimer(self)
            self.count_timer.timeout.connect(self.countdown_tick)
            self.count_timer.start(1000)

    def countdown_tick(self):
        if self.in_library():
            return
        self.countdown -= 1
        if self.countdown:
            self.record_button.setText(f'Cancel · {self.countdown}')
            self.notice(f'Starting in {self.countdown}… Esc cancels.')
        else:
            self.count_timer.stop()
            # Hide before capture starts, avoiding the preview recursion in the recording.
            if self.mode == 'screen':
                self._capture_window_state = self.windowState() & ~Qt.WindowMinimized
                self.hide()
            self.start_timer.start(250)

    def cancel_countdown(self):
        if self.preparing_audio:
            self.audio_start_failed('Microphone check cancelled. Recording has not started.')
            return
        if self.counting:
            self.count_timer.stop()
            self.start_timer.stop()
            self.counting = False
            self.lock_controls(False)
            self.record_button.setText('●  Start recording')
            self.notice('Countdown cancelled. Ready when you are.')
            self.restore_capture_window()

    def start(self):
        if self._closing or self.in_library() or self.busy or self.recording or not self.counting or not self.configuration_valid:
            return
        if self.audio_worker and self.audio_worker.isRunning():
            self.start_timer.start(100)  # Serialize preparation with deferred restoration.
            return
        self.counting = False
        self.busy = self.preparing_audio = True
        self.record_button.setEnabled(False)
        self.notice('Preparing microphone…')
        selection = self.microphone.currentData()
        trace = self.idle_audio.audio_trace if self.idle_audio.source else None
        if not isinstance(trace, AudioTrace):
            trace = AudioTrace()
            trace.event('session.start', selection=selection, processing=self.clean_microphone.isChecked(),
                        desktop_audio=self.desktop_audio.isChecked())
        self.audio_trace = self.engine.audio_trace = self.audio_devices.audio_trace = trace
        emit(self, 'record.requested', selection=selection, processing=self.clean_microphone.isChecked(),
             desktop_audio=self.desktop_audio.isChecked())
        self._audio_generation += 1
        generation = self._audio_generation
        if self.idle_audio.source:
            source = self.idle_audio.transfer()
            self.audio_prepared(source, '')
            return
        self._capture_owner = self.audio_devices.hold_capture()
        self.run_audio(lambda: self.audio_devices.prepare(selection),
            lambda source, error: self.audio_prepared(source, error)
            if generation == self._audio_generation else None)

    def run_audio(self, action, callback):
        generation = self._audio_generation
        worker = self.audio_worker = AudioWorker(action, self)
        worker.result.connect(callback)
        def finished():
            if self.audio_worker is worker:
                self.audio_worker = None
            worker.deleteLater()
            if generation != self._audio_generation and not self.preparing_audio and not self._closing:
                self.retry_audio_restore()
        worker.finished.connect(finished)
        worker.start()

    def audio_prepared(self, source, error):
        if self._closing:
            return  # closeEvent releases capture and restores after the worker exits.
        if error:
            self.audio_start_failed(error)
            return
        self.selected_source = source
        self.configure(microphone=source, recording_setup=True)
        if not self.configuration_valid:
            self.audio_start_failed(self.status.text())
            return
        if source:
            self.busy = self.preparing_audio = True
            self.record_button.setEnabled(False)
            self.restore_capture_window()
            self.engine_notice('Checking microphone; say a few words… Esc cancels.')
            self._audio_deadline = time.monotonic() + 8
            self.poll_microphone(self._audio_generation)
        else:
            self.begin_recording()

    def audio_start_failed(self, error):
        emit(self, 'preparation.aborted', level='warning', reason='preparation_failed_or_cancelled')
        self._audio_generation += 1
        self.busy = self.preparing_audio = False
        self.release_audio()
        self.lock_controls(False)
        self.record_button.setEnabled(self.configuration_valid)
        self.record_button.setText('●  Start recording')
        self.notice(f'Could not prepare microphone: {error}')
        self.restore_capture_window()

    def poll_microphone(self, generation):
        if self._closing or generation != self._audio_generation or not self.preparing_audio:
            return
        status = self.engine.audio_status()
        trace = getattr(self, 'audio_trace', None)
        if isinstance(trace, AudioTrace):
            trace.telemetry('readiness', status)
        if self.microphone_ready(status):
            if self.audio_worker and self.audio_worker.isRunning():
                QTimer.singleShot(100, lambda: self.poll_microphone(generation))
                return
            source = self.selected_source
            self.run_audio(lambda: self.engine.verify_audio_route(timeout=2),
                lambda result, error: self.microphone_verified(generation, result, error))
        elif time.monotonic() >= self._audio_deadline:
            if isinstance(trace, AudioTrace):
                trace.telemetry('readiness', status, outcome='timeout')
                trace.event('readiness.failed', level='warning', exception_type='TimeoutError',
                            reason='no_fresh_nonzero_packets')
            detail = ('No microphone samples arrived.' if not status.get('packets') or
                status.get('packet_age') is None or status['packet_age'] >= 1.5 else
                'Microphone samples contain only silence.')
            self.audio_start_failed(detail + ' Say a few words and try again, or use Check microphone. '
                'If the room is quiet, try turning Clean microphone off. Recording has not started.')
        else:
            QTimer.singleShot(100, lambda: self.poll_microphone(generation))

    def microphone_ready(self, status):
        return (isinstance(status, dict) and status.get('source') == self.selected_source
            and status.get('packets', 0) > 0 and status.get('nonzero_packets', 0) > 0
            and status.get('packet_age') is not None and status['packet_age'] < 1.5)

    def microphone_verified(self, generation, source, error):
        if self._closing or generation != self._audio_generation or not self.preparing_audio:
            return
        if error or source != self.selected_source:
            self.audio_start_failed(error or 'The selected microphone changed during preparation.')
        elif not self.microphone_ready(self.engine.audio_status()):
            self.poll_microphone(generation)
        elif self.mode == 'screen':
            emit(self, 'readiness.ready', source=source)
            self._capture_window_state = self.windowState() & ~Qt.WindowMinimized
            self.hide()
            QTimer.singleShot(250, lambda: self.begin_recording(generation))
        else:
            self.begin_recording(generation)

    def begin_recording(self, generation=None):
        if self._closing or (generation is not None and generation != self._audio_generation):
            return
        if self.selected_source and not self.microphone_ready(self.engine.audio_status()):
            self.poll_microphone(self._audio_generation)
            return
        self.busy = self.preparing_audio = False
        emit(self, 'readiness.accepted', source=self.selected_source)
        self.record_button.setEnabled(True)
        source = self.selected_source
        try:
            if not self.configuration_valid:
                raise RuntimeError(self.status.text())
            if self.mode == 'screen' and self.capture_kind.currentData() == 'window' and not self.window_catalog.geometry(self.capture_window.currentData()):
                raise RuntimeError('The selected window is no longer available. Choose an open window and try again.')
            if shutil.disk_usage(VIDEOS).free < 1024 ** 3:
                raise RuntimeError('Less than 1 GB free. Make some room before recording.')
            window_title = self.capture_window.currentText() if self.mode == 'screen' and self.capture_kind.currentData() == 'window' else ''
            self.record_path = next_recording_path(VIDEOS, self.mode, window_title)
            self.recording_error = ''
            self.recording_error_baseline = len(self.engine.errors)
            self.engine.start(self.record_path)
            encoder = self.engine.stats().get('encoder', '')
            self.encoder_label.setText('Intel hardware · H.264' if encoder == 'ffmpeg_vaapi' else 'CPU encoding · H.264')
            self.started = time.monotonic()
            self.paused_duration = 0
            self.paused = False
            self.recording = True
            self._audio_warning_since = None
            self.bubble.recording = True
            self.zoom_button.setEnabled(self.mode == 'screen')
            self.tray_zoom.setEnabled(self.mode == 'screen')
            self.record_button.setText('■  Stop and save')
            self.pause_button.setVisible(True)
            self.pause_button.setText('Pause')
            self.tray_pause.setEnabled(True)
            self.tray_record.setText('Stop and save')
            self.tray.setIcon(self.record_icon())
            self.engine_notice('Recording. Ctrl + Shift + F9 stops and saves.\n'
                + (f'Microphone: {source}' if source else 'Microphone off'))
            if self.mode == 'screen':
                self.tray.setToolTip('Untangle · Recording\nF9 stop · F10 pause · F8 zoom\nHold Ctrl + Shift with each key')
        except Exception as exc:
            emit(self, 'record_start.failed', level='warning', exception_type=type(exc).__name__)
            self.release_audio()
            self.lock_controls(False)
            self.record_button.setText('●  Start recording')
            self.notice(f'Could not start recording: {exc}')
            self.restore_capture_window()

    def stop(self):
        if not self.recording or self.busy:
            return
        self.busy = True
        self.zoom_timer.stop()
        self.zoom_button.setEnabled(False)
        self.tray_zoom.setEnabled(False)
        self.record_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.tray_record.setEnabled(False)
        self.tray_pause.setEnabled(False)
        self.notice('Saving your recording…')
        self.worker = FinishWorker(self.engine, self.record_path)
        self.worker.finished_file.connect(self.stopped)
        self.worker.start()

    def stopped(self, path, error):
        if error and self.engine.recording:
            self.busy = False
            self.record_button.setEnabled(True)
            self.pause_button.setEnabled(True)
            self.tray_record.setEnabled(True)
            self.tray_pause.setEnabled(True)
            self.zoom_button.setEnabled(self.mode == 'screen')
            self.tray_zoom.setEnabled(self.mode == 'screen')
            if self.mode == 'screen' and (self.zoom_motion.enabled or self.zoom_motion.factor != 1.):
                self.zoom_motion.last_time = time.monotonic()
                self.zoom_timer.start()
            self.notice(f'OBS is still stopping: {error}. Try Stop again; your recording is retained.')
            self.restore_capture_window()
            return
        engine_errors = self.engine.errors[self.recording_error_baseline:]
        if engine_errors:
            self.recording_error = (self.recording_error + ' ' if self.recording_error else '') + 'Recording ended with an error. Review the saved video before sharing. ' + '; '.join(engine_errors)
        self.recording = False
        self.release_audio()
        self.paused = False
        self.bubble.recording = False
        self.bubble.paused = False
        self.reset_zoom()
        self.tray.setIcon(QIcon(str(ICON)))
        self.tray.setToolTip('Untangle · Saving recording')
        self.restore_capture_window()
        self.pause_button.setVisible(False)
        if error:
            self.finish_save(Path(path), f'Recording stopped with an error: {error}. The original file is preserved.')
            return
        source = Path(path)
        if not source.exists() or source.stat().st_size == 0:
            self.finish_save(None, 'The engine did not produce a recording. Check the camera and recording log.')
            return
        self.remux(source)

    def remux(self, source):
        self.notice('Preparing your MP4. The original recording is safe.')
        self.record_button.setText('Preparing video…')
        target = source.with_suffix('.mp4')
        self.process = QProcess(self)
        self.process.setProgram('ffmpeg')
        self.process.setArguments(['-hide_banner', '-loglevel', 'error', '-n', '-i', str(source), '-map', '0', '-c', 'copy', '-movflags', '+faststart', str(target)])
        self.process.finished.connect(lambda code, status: self.remux_done(source, target, code))
        self.process.errorOccurred.connect(lambda error: self.remux_error(source, error))
        self.process.start()

    def remux_error(self, source, error):
        if error == QProcess.FailedToStart:
            self.finish_save(source, 'FFmpeg could not start. Your MKV recording is safe and can be played.')

    def remux_done(self, source, target, code):
        if code == 0 and target.exists() and target.stat().st_size:
            source.unlink()
            self.finish_save(target, self.recording_error)
        else:
            details = bytes(self.process.readAllStandardError()).decode(errors='replace')[-600:]
            # Never offer a partial MP4 or remove the recoverable original.
            if target.exists():
                target.unlink()
            self.finish_save(source, f'MP4 preparation failed. Your MKV is safe. {details}')

    def finish_save(self, path, error):
        emit(self, 'save.result', outcome='warning' if error else 'saved')
        self.busy = False
        self.record_button.setText('●  Start recording')
        self.record_button.setEnabled(self.configuration_valid)
        self.pause_button.setEnabled(True)
        self.tray_record.setEnabled(True)
        self.tray_record.setText('Start recording')
        self.tray.setToolTip('Untangle · Ready to record')
        self.lock_controls(False)
        if path and path.exists():
            self.set_last(path)
            if (not error and not self.quit_after_save and not self._closing
                    and self.auto_titles.isChecked() and local_title_capability()[0]):
                self.start_automatic_title(path)
                return
        self.complete_saved_video(path, error)

    def start_automatic_title(self, path):
        self.busy = True
        self.lock_controls(True)
        self.record_button.setEnabled(False)
        self.cancel_title_button.show()
        self.notice('Saved. Generating a name from the transcript…')
        identity = self.upload_store.file_identity(path)
        job = self._title_job = LocalTitleJob(self)
        def finished(title, error):
            if self._title_job is not job:
                return
            self._title_job = None
            job.deleteLater()
            self.cancel_title_button.hide()
            self.busy = False
            self.lock_controls(False)
            self.record_button.setEnabled(self.configuration_valid)
            if self._closing:
                return
            if identity is None or self.upload_store.file_identity(path) != identity:
                self.complete_saved_video(path, 'The saved file changed while naming. Its name was left unchanged. Check it before sharing.', prompt=False)
                return
            if title:
                try:
                    renamed = rename_recording(path, title)
                except (OSError, ValueError):
                    error = 'The generated name could not be saved. Choose a name manually.'
                else:
                    self.set_last(renamed)
                    self.complete_saved_video(renamed, '', prompt=False)
                    return
            self.title_capability.setText(error or 'Automatic naming did not return a title.')
            self.complete_saved_video(path, '', prompt=True)
        job.finished.connect(finished)
        job.start(path)

    def cancel_automatic_title(self):
        if self._title_job is not None:
            self.cancel_title_button.setEnabled(False)
            self._title_job.cancel()

    def complete_saved_video(self, path, error, *, prompt=True):
        self.cancel_title_button.setEnabled(True)
        if path and path.exists():
            if not error and not self.quit_after_save and not self._closing:
                if prompt:
                    self.busy = True
                    self.lock_controls(True)
                    self.notice('Saved safely. Give your recording a name.')
                    try:
                        renamed = prompt_recording_name(self, path,
                            lambda title: rename_recording(path, title), new_recording=True)
                        if renamed is not None:
                            self.set_last(renamed)
                    finally:
                        self.busy = False
                        self.lock_controls(False)
        self.notice(error or 'Saved. Play it back, or upload to Loom when you are ready.')
        if not error and self.prefs.value('auto_upload', False, type=bool):
            self.upload()
        if self.quit_after_save and not self.busy:
            self.close()

    def toggle_pause(self):
        if not self.recording or self.busy:
            return
        try:
            self.engine.pause(not self.paused)
            self.paused = not self.paused
            self.bubble.paused = self.paused
            if self.paused:
                self.pause_started = time.monotonic()
            else:
                self.paused_duration += time.monotonic() - self.pause_started
            self.pause_button.setText('Resume' if self.paused else 'Pause')
            self.tray_pause.setText('Resume' if self.paused else 'Pause')
        except Exception as exc:
            self.notice(f'Could not change pause state: {exc}')
            self.restore_capture_window()

    def open_audio_check(self):
        if (not self.engine or self.recording or self.counting or self.busy or
                self.preparing_audio or self.in_library() or self._closing or
                (self.audio_worker and self.audio_worker.isRunning())):
            return
        from .audio_check import AudioCheck
        self.configure_timer.stop()
        self.start_timer.stop()
        self.idle_audio.stop()
        self.focus_button.setChecked(False)
        self.busy = True
        self.lock_controls(True)
        self.record_button.setEnabled(False)
        dialog = self.audio_check_dialog = AudioCheck(self.engine, self.audio_devices,
            self.microphone.currentData(), self.clean_microphone.isChecked(),
            self.microphone.currentText(), self, inline=True)
        previous_status = self.status.text()
        def finished():
            self.preview_column.removeWidget(dialog)
            self.microphone_meter.show()
            self.shortcuts.show()
            self.zoom_button.setVisible(self.mode == 'screen')
            self.zoom_amount.setVisible(self.mode == 'screen')
            self.status.setText(previous_status)
            self.audio_check_dialog = None
            self.busy = False
            self.lock_controls(False)
            self.record_button.setEnabled(self.configuration_valid)
            if getattr(dialog, 'change_input_requested', False):
                self.microphone.setFocus(Qt.OtherFocusReason)
            dialog.deleteLater()
            self.retry_audio_restore()
            if self._configure_pending:
                self.configure_timer.start(0)
        dialog.finished.connect(finished)
        # Keep the native preview in its original parent. The check is a compact
        # child below it; setup stays visible and a safe return unlocks inputs.
        dialog.setWindowFlags(Qt.Widget)
        dialog.setModal(False)
        dialog.setFixedHeight(230)
        self.microphone_meter.hide()
        self.shortcuts.hide()
        self.zoom_button.hide()
        self.zoom_amount.hide()
        self.status.setText('Audio check open. Close it to change the recording setup.')
        self.preview_column.insertWidget(3, dialog)
        dialog.show()

    def release_audio(self):
        self.idle_audio.stop()
        if self.engine:
            self.engine.release_audio()
        owner = getattr(self, '_capture_owner', None)
        if owner is not None:
            self.audio_devices.release_capture(owner)
            self._capture_owner = None
        self.selected_source = None
        self.retry_audio_restore()

    def retry_audio_restore(self):
        if (self.idle_audio.owner is not None or getattr(self, 'audio_check_dialog', None) or self._closing or self.recording or self.preparing_audio or
                (self.audio_worker and self.audio_worker.isRunning())):
            return
        self._audio_retry_at = time.monotonic() + 3
        if self.audio_devices.lease:
            self.run_audio(self.audio_devices.restore, lambda result, error: None)

    def audio_checked(self, source, error):
        if error:
            emit(self, 'health.source_unavailable', level='warning', source=self.selected_source)
        if error and self.recording and not self.busy:
            self.recording_error = self.recording_error or f'Microphone disconnected or became unavailable. The recording was saved. {error}'
            self.stop()

    def microphone_warning(self):
        if self.paused or not self.selected_source:
            self._audio_warning_since = None
            return ''
        status = self.engine.audio_status()
        problem = status.get('state') if isinstance(status, dict) else None
        if problem not in ('no_packets', 'silent', 'off'):
            self._audio_warning_since = None
            return ''
        now = time.monotonic()
        previous = self._audio_warning_since
        if previous is None or previous[0] != problem:
            self._audio_warning_since = (problem, now)
            return ''
        if now - previous[1] < (15 if problem == 'silent' else 5):
            return ''
        emit(self, 'health.warning', every=5, level='warning', reason=problem, source=self.selected_source)
        warning = ('Microphone is sending only silence. Say a few words and check the meter.'
            if problem == 'silent' else 'Microphone samples stopped arriving. Check your microphone connection.')
        self.recording_error = self.recording_error or (warning + ' Review the audio before sharing.')
        return warning

    def update_microphone_meter(self):
        status = self.engine.audio_status() if self.engine else None
        source = status.get('source') if isinstance(status, dict) else None
        if self.idle_audio.source and not self.idle_audio.verified:
            status = None
            source = None
        index = self.microphone.findData(source) if source else -1
        name = self.microphone.itemText(index) if index >= 0 else source or 'Automatic microphone · preparing…'
        friendly = getattr(self.audio_devices, 'source_label', None)
        if source and isinstance(friendly, str) and friendly:
            name = friendly
        if self.microphone.currentData() is None or (not source and self.microphone.currentData() != 'default'):
            name = self.microphone.currentText()
        self.microphone_meter.show_status(status, name, self.microphone.currentData() is not None)
        if not self.recording and not self.preparing_audio and not getattr(self, 'audio_check_dialog', None):
            if self.microphone.currentData() is None:
                pass  # The explicit off state takes precedence over old monitor data.
            elif not self.live_microphone.isChecked():
                self.microphone_meter.show_status(None, self.microphone.currentText())
                self.microphone_meter.message.setText('Live monitoring off')
            elif self.idle_audio.error:
                self.microphone_meter.message.setText('Monitor unavailable: ' + self.idle_audio.error)
            elif self.idle_audio.pending or (self.idle_audio.source and not self.idle_audio.verified):
                self.microphone_meter.message.setText('Preparing live microphone…')
            elif self.idle_audio.source:
                self.microphone_meter.message.setText('Live · ' + self.microphone_meter.message.text())
        trace = getattr(self, 'audio_trace', None)
        if isinstance(trace, AudioTrace) and self.recording:
            trace.telemetry('health', status)

    def tick(self):
        self.idle_audio.reconcile()
        self.update_microphone_meter()
        audio_idle = not self.audio_worker or not self.audio_worker.isRunning()
        if (self.recording and not self.busy and self.selected_source and audio_idle
                and time.monotonic() >= getattr(self, '_recording_route_at', 0)):
            self._recording_route_at = time.monotonic() + .5
            source = self.selected_source
            generation = self._audio_generation
            self.run_audio(self.engine.verify_audio_route,
                lambda result, error: self.audio_checked(result, error)
                if generation == self._audio_generation and self.selected_source == source else None)
        elif not self.recording and audio_idle and time.monotonic() >= self._audio_retry_at:
            self.retry_audio_restore()
        if self.recording and not self.busy:
            if self.mode == 'screen' and self.capture_kind.currentData() == 'window' and not self.window_catalog.geometry(self.capture_window.currentData()):
                self.recording_error = self.recording_error or 'The selected window closed or was minimized. The recording was saved; review it before sharing.'
                self.stop()
                return
            if self.mode == 'screen' and self.capture_kind.currentData() == 'window':
                # Refit after a target-window resize, even while zoom is off.
                self.engine.set_screen_zoom(self.zoom_motion.factor, self.zoom_motion.x, self.zoom_motion.y)
            stats = self.engine.stats()
            if not stats.get('recording', True):
                self.notice('The recording engine stopped. Saving the recoverable recording…')
                self.stop()
                return
            elapsed = int((self.pause_started if self.paused else time.monotonic()) - self.started - self.paused_duration)
            duration = f'{elapsed // 60:02d}:{elapsed % 60:02d}'
            state = 'Paused' if self.paused else 'Recording'
            warning = self.microphone_warning()
            self.engine_notice(f'{state} · {duration}   |   Ctrl + Shift + F9 to stop and save\n'
                + (f'Microphone: {self.selected_source}' if self.selected_source else 'Microphone off')
                + ('\n' + (self.recording_error or warning) if self.recording_error or warning else ''))
            self.record_button.setText('■  Stop and save')
            self.tray.setToolTip(f'Untangle · {state} {duration}\nCtrl + Shift + F9 to stop')
            if elapsed % 10 == 0 and shutil.disk_usage(VIDEOS).free < 256 * 1024 ** 2:
                self.notice('Storage almost full. Stopping to save your recording.')
                self.stop()

    def lock_controls(self, locked):
        self.settings_button.setEnabled(not locked)
        self.focus_button.setEnabled(not locked)
        self.live_microphone.setEnabled(not locked)
        self.audio_check_button.setEnabled(not locked)
        self.sharing_button.setEnabled(not locked)
        self.library_button.setEnabled(not locked)
        if locked and self.recordings:
            self.recordings.release()
            self.pages.setCurrentWidget(self.recorder_page)
        if locked and self.camera_adjustments is not None and self.pages.currentWidget() is self.camera_adjustments:
            self.back_to_recorder()
        for widget in self.config_controls:
            widget.setEnabled(not locked)
        if not locked:
            self.screen.setEnabled(self.mode == 'screen')
            self.capture_kind.setEnabled(self.mode == 'screen')
            self.capture_window.setEnabled(self.mode == 'screen')
            self.refresh_button.setEnabled(self.mode == 'screen')
            self.update_camera_controls()
        if self.recordings:
            self.recordings.update_actions()

    def set_last(self, path):
        path = Path(path)
        self.last_file = path if path.is_file() else None
        if path != getattr(self, '_upload_file', None) and not self._upload_active:
            self.upload_panel.hide()

    def in_library(self):
        return self.pages.currentWidget() != self.recorder_page

    def camera_image_settings(self):
        try:
            saved = json.loads(self.prefs.value('camera_image', '{}') or '{}')
        except (TypeError, ValueError):
            saved = {}
        return saved if isinstance(saved, dict) else {}

    def save_camera_image(self, camera_name, values):
        saved = self.camera_image_settings()
        if values:
            saved[camera_name] = values
        else:
            saved.pop(camera_name, None)
        self.prefs.setValue('camera_image', json.dumps(saved, sort_keys=True))
        self._camera_image_applied = (self.camera.currentData(), camera_name)

    def restore_camera_image(self, device):
        """Reapply remembered picture settings, keyed by camera name: /dev/videoN moves on replug."""
        name = self.camera.currentText()
        if not device or self._camera_image_applied == (device, name):
            self._camera_image_applied = (device, name) if device else None
            return
        self._camera_image_applied = (device, name)
        saved = self.camera_image_settings().get(name)
        if not isinstance(saved, dict):
            return
        try:
            restore_saved(device, saved)
        except CameraControlError as exc:
            self.notice(f'Could not restore camera picture settings: {exc}')

    def open_camera_adjustments(self):
        device = self.camera.currentData()
        if self.recording or self.counting or self.busy or not device:
            return
        if self.camera_adjustments is None:
            self.camera_adjustments = CameraAdjustments(Preview(), self)
            self.camera_adjustments.back_requested.connect(self.back_to_recorder)
            self.camera_adjustments.saved_changed.connect(self.save_camera_image)
            self.camera_adjustments.preview_resized.connect(self.resize_camera_adjustment_preview)
            self.pages.addWidget(self.camera_adjustments)
        self.configure_timer.stop()
        self.start_timer.stop()
        generation = self._preview_generation = getattr(self, '_preview_generation', 0) + 1
        self.hide_bubble()
        if self.engine:
            self.engine.detach_preview()
        self.preview.hide()
        name = self.camera.currentText()
        self.camera_adjustments.load(device, name, self.camera_image_settings().get(name))
        self.pages.setCurrentWidget(self.camera_adjustments)
        self.tray_record.setEnabled(False)
        QTimer.singleShot(0, lambda: self.attach_camera_adjustment_preview(generation))

    def attach_camera_adjustment_preview(self, generation):
        page = self.camera_adjustments
        if (self._closing or generation != getattr(self, '_preview_generation', 0)
                or page is None or self.pages.currentWidget() is not page or not self.engine):
            return
        preview = page.preview
        ratio = preview.devicePixelRatioF()
        try:
            self.engine.attach_camera_preview(int(preview.winId()),
                max(1, round(preview.width() * ratio)), max(1, round(preview.height() * ratio)))
        except Exception as exc:
            page.message.setText(f'Live preview unavailable: {exc}')

    def resize_camera_adjustment_preview(self, width, height):
        page = self.camera_adjustments
        if self.engine and page is not None and self.pages.currentWidget() is page:
            ratio = page.preview.devicePixelRatioF()
            try:
                self.engine.resize_camera_preview(max(1, round(width * ratio)), max(1, round(height * ratio)))
            except Exception:
                pass

    def back_to_recorder(self):
        if self.recordings:
            self.recordings.release()
        page = getattr(self, 'camera_adjustments', None)
        if page is not None and self.pages.currentWidget() is page:
            page.leave()
            # Destroy the GLX child before Qt hides the page's native preview.
            self.hide_bubble()
        self.pages.setCurrentWidget(self.recorder_page)
        self.refresh_upload_link()
        self.preview.show()
        self.tray_record.setEnabled(True)
        if self.engine and (not self.configuration_valid or self._configure_pending):
            self.configure_timer.start(0)
        # Qt must finish showing/resizing the native parent before GLX creates
        # its child. A later navigation invalidates this queued restoration.
        generation = self._preview_generation = getattr(self, '_preview_generation', 0) + 1
        QTimer.singleShot(0, lambda: self.restore_preview(generation))

    def restore_preview(self, generation):
        if (self._closing or generation != getattr(self, '_preview_generation', 0) or
                self.in_library()):
            return
        if not self.engine:
            self.initialize()
            return
        try:
            ratio = self.preview.devicePixelRatioF()
            self.engine.attach_preview(int(self.preview.winId()),
                round(self.preview.width() * ratio), round(self.preview.height() * ratio))
            if self.mode == 'screen' and self.camera.currentData() and self.configuration_valid:
                if self.uses_floating_camera() or self.capture_kind.currentData() == 'window':
                    self.show_bubble()
        except Exception as exc:
            self.notice(f'Could not restore the preview: {exc}')

    def open_recordings(self, path=None):
        if self.recording or self.counting or self.busy:
            return
        if self.recordings is None:
            self.recordings = Recordings(VIDEOS, self,
                deletion_blocked=lambda path: self.recording or self.counting or self.busy,
                upload_store=self.upload_store)
            self.recordings.recording_deleted.connect(self.recording_deleted)
            self.recordings.recording_renamed.connect(self.recording_renamed)
            self.recordings.upload_requested.connect(self.upload_recording)
            self.recordings.check_remote_requested.connect(self.check_loom_video)
            self.recordings.back_requested.connect(self.back_to_recorder)
            self.recordings.theme_requested.connect(self.set_theme)
            self.recordings.settings_requested.connect(self.open_settings)
            self.pages.addWidget(self.recordings)
        self.configure_timer.stop()
        self.start_timer.stop()
        self._preview_generation = getattr(self, '_preview_generation', 0) + 1
        self.hide_bubble()
        self.release_audio()
        if self.engine:
            self.engine.detach_preview()
        self.preview.hide()
        self.pages.setCurrentWidget(self.recordings)
        self.tray_record.setEnabled(False)
        self.recordings.search.clear()
        self.recordings.refresh(path)

    def recording_renamed(self, old_path, new_path):
        if self.last_file is not None and Path(old_path) == self.last_file:
            self.set_last(new_path)

    def recording_deleted(self, path):
        if self.last_file is None or Path(path) != self.last_file:
            return
        paths = recording_files(VIDEOS)
        if paths:
            self.set_last(paths[0])
            return
        self.last_file = None

    def upload_recording(self, path):
        if self.busy or self.recording or self.counting or self._closing:
            return
        self.set_last(path)
        if self.last_file is None:
            self.recordings.update_actions()
            self.recordings.message.setText('This recording is missing. Refresh the list.')
            return
        self.back_to_recorder()
        self.upload(confirmed=True)

    def loom_probe(self, args, callback, timeout=15000):
        """Read CLI state asynchronously. Never show raw OAuth diagnostics."""
        cli = self.find_cli()
        if not cli:
            callback('', 127, '')
            return None
        process = QProcess(self)
        process._stdout = bytearray()
        process._stderr = bytearray()
        process._reported = False
        timer = QTimer(process)
        timer.setSingleShot(True)
        self.loom_probes.add(process)
        def drain(channel, target):
            target.extend(bytes(channel()))
            if len(target) > 1024 * 1024:
                del target[:-1024 * 1024]
        process.readyReadStandardOutput.connect(lambda: drain(process.readAllStandardOutput, process._stdout))
        process.readyReadStandardError.connect(lambda: drain(process.readAllStandardError, process._stderr))
        def done(code, *_):
            if process._reported:
                return
            process._reported = True
            timer.stop()
            drain(process.readAllStandardOutput, process._stdout)
            drain(process.readAllStandardError, process._stderr)
            self.loom_probes.discard(process)
            if not self._closing:
                callback(process._stdout.decode(errors='replace'), code,
                         process._stderr.decode(errors='replace'))
            process.deleteLater()
        process.finished.connect(done)
        process.errorOccurred.connect(lambda error: done(-1) if error == QProcess.FailedToStart else None)
        def expired():
            process.kill()
            done(-1)
        timer.timeout.connect(expired)
        process.setProgram(cli)
        process.setArguments(args)
        process.start()
        timer.start(timeout)
        return process

    def sharing_settings(self):
        if self.busy or self.recording or self.counting:
            return
        dialog = QDialog(self)
        self._sharing_dialog = dialog
        dialog.setWindowTitle('Untangle · Sharing')
        dialog.setMinimumWidth(540)
        dialog.resize(580, 740)
        outer = QVBoxLayout(dialog)
        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(label('LOOM', 'eyebrow'))
        text = label('Recordings save locally first. Connect through browser OAuth using Atlassian’s official Teamwork Graph CLI.')
        text.setWordWrap(True)
        layout.addWidget(text)
        self.cli_status = label('Checking Loom connection…', 'muted')
        self.cli_status.setTextFormat(Qt.PlainText)
        self.cli_status.setWordWrap(True)
        layout.addWidget(self.cli_status)
        cli = self.find_cli()
        connect = QPushButton('Connect Loom account ↗')
        connect.clicked.connect(self.connect_loom)
        layout.addWidget(connect)
        check = QPushButton('Check connection')
        layout.addWidget(check)
        disconnect = QPushButton('Disconnect TWG account…')
        layout.addWidget(disconnect)
        def show_account():
            state = self.loom_account
            status = state.get('status')
            connected = status == 'connected'
            connect.setVisible(not connected)
            connect.setEnabled(bool(cli) and self._account_operation is None)
            connect.setText('Connect Loom account ↗' if status == 'disconnected' else 'Reconnect Loom account ↗')
            disconnect.setVisible(connected)
            disconnect.setEnabled(connected and self._account_operation is None)
            check.setEnabled(bool(cli) and self._account_operation is None)
            if connected:
                name = state.get('name') or state.get('email') or state.get('account_id') or 'Signed-in account'
                email = state.get('email')
                detail = f' · {email}' if email and email != name else ''
                self.cli_status.setText(f'Connected as {name}{detail}. Loom uploads still require an eligible workspace plan.')
            elif not cli:
                self.cli_status.setText('Install Atlassian’s TWG CLI, then connect your account.')
            elif status == 'disconnected':
                self.cli_status.setText('Loom account is disconnected. Connect using browser OAuth.')
            else:
                self.cli_status.setText('Connection has not been verified. Check your connection, or reconnect using browser OAuth.')
        def probe():
            if (self._closing or self._account_operation is not None
                    or getattr(self, '_sharing_dialog', None) is not dialog):
                return
            self._account_operation = 'check'
            check.setEnabled(False)
            connect.hide()
            disconnect.setEnabled(False)
            self.cli_status.setText('Checking Loom connection…')
            def result(out, code, err):
                self._account_operation = None
                self.loom_account = parse_account_status(out, code, err)
                if getattr(self, '_sharing_dialog', None) is not None:
                    self._show_loom_account()
            self.loom_probe(['whoami', '-o', 'json', '--output-summary', 'none'], result)
        check.clicked.connect(probe)
        def logout():
            if self._account_operation is not None:
                return
            answer = QMessageBox.question(dialog, 'Disconnect TWG account?',
                'This signs out the selected TWG CLI profile for all Atlassian products, including Loom. Local recordings and saved links stay on this computer.',
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if answer != QMessageBox.Yes:
                return
            self._account_operation = 'logout'
            show_account()
            def result(out, code, err):
                self._account_operation = None
                self.loom_account = {'status': 'disconnected' if code == 0 else 'unknown'}
                if getattr(self, '_sharing_dialog', None) is not None:
                    self._show_loom_account()
            self.loom_probe(['logout', '-o', 'json', '--output-summary', 'none'], result)
        disconnect.clicked.connect(logout)
        self._show_loom_account = show_account
        show_account()
        layout.addWidget(label('Who can watch uploaded videos?', 'section'))
        visibility = QComboBox()
        for title, value in [('Only me', 'owner'), ('My Loom workspace', 'workspace'), ('Anyone with the link', 'public')]:
            visibility.addItem(title, value)
        visibility.setCurrentIndex(max(0, visibility.findData(self.prefs.value('visibility', 'owner'))))
        layout.addWidget(visibility)
        auto = QCheckBox('Upload automatically after I stop recording')
        auto.setChecked(self.prefs.value('auto_upload', False, type=bool))
        auto.setEnabled(bool(cli))
        layout.addWidget(auto)
        titles = QCheckBox('Let Loom generate titles when available')
        titles.setChecked(self.prefs.value('loom_auto_titles', True, type=bool))
        layout.addWidget(titles)
        title_status = label('Enabled here: Untangle sends no title override. Loom controls AI titles and requires a transcript of at least 30 seconds. Automatic titles for imported videos are not confirmed; the CLI cannot read or enable this Loom setting.', 'muted')
        title_status.setWordWrap(True)
        layout.addWidget(title_status)
        def describe_titles(enabled):
            title_status.setText(
                'Enabled here: no title override is sent. The CLI cannot read or enable Loom’s AI setting. Automatic titles for imported videos are not confirmed. Loom requires a transcript of at least 30 seconds.' if enabled else
                'Untangle will request your local recording title when the installed CLI supports it.')
        titles.toggled.connect(describe_titles)
        describe_titles(titles.isChecked())
        title_help = QPushButton('Loom automatic-title settings ↗')
        title_help.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('https://support.atlassian.com/loom/docs/how-auto-titles-summaries-and-chapters-work/')))
        layout.addWidget(title_help)
        workspace = QPushButton('Open Loom workspace settings ↗')
        workspace.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('https://www.loom.com/settings/workspace')))
        layout.addWidget(workspace)
        docs = QPushButton('Open Loom connection instructions ↗')
        docs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('https://developer.atlassian.com/cloud/twg-cli/')))
        layout.addWidget(docs)
        privacy = label('Your Loom defaults apply during upload. Untangle then applies the selected sharing setting. Uploads require Business, Business + AI, or Enterprise, excluding trials.', 'muted')
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        done = QPushButton('Done')
        done.clicked.connect(dialog.accept)
        layout.addWidget(done)
        if cli:
            QTimer.singleShot(0, probe)
        if dialog.exec():
            self.prefs.setValue('auto_upload', auto.isChecked())
            self.prefs.setValue('visibility', visibility.currentData())
            self.prefs.setValue('loom_auto_titles', titles.isChecked())
        self._sharing_dialog = None
        dialog.deleteLater()

    def check_loom_video(self, path):
        path = Path(path)
        if self.busy or self.recording or self.counting or self._closing or path in self._loom_check_paths:
            return
        entry = self.upload_store.get(path)
        identifier = video_id(entry.get('remote_id') or entry.get('url', ''))
        if not identifier or not self.find_cli():
            if self.recordings:
                self.recordings.message.setText('Connect Loom in Sharing to check this saved link.')
            return
        if self.recordings:
            self.recordings.message.setText('Checking the saved Loom link…')
        self._loom_check_paths.add(path)
        def checked(out, code, err):
            self._loom_check_paths.discard(path)
            # Ignore a stale result after a local rename, deletion or new upload.
            current = self.upload_store.get(path)
            if current != entry or not current:
                return
            result = parse_video_info(out, code, err)
            if result.get('status') == 'deleted':
                if not self.save_upload_metadata(path, status='deleted', url='', error=''):
                    if self.recordings:
                        self.recordings.message.setText('Loom reports deletion, but the saved link could not be cleared. The local metadata file is unchanged.')
                    return
                if path == getattr(self, '_upload_file', None):
                    self._upload_url = None
                    self.upload_panel.hide()
                message = 'Loom reports this video was deleted. Your local recording is preserved.'
            elif result.get('status') == 'available':
                changes = {key: result[key] for key in ('title', 'remote_id') if result.get(key)}
                if result.get('url'):
                    changes['url'] = result['url']
                if result.get('is_complete') is True:
                    changes['status'] = 'uploaded'
                if self.save_upload_metadata(path, **changes):
                    message = 'Loom link verified. The upstream title is refreshed. This CLI may not report processing completion.'
                else:
                    message = 'Loom link verified, but its title could not be saved locally. The previous saved link and title are unchanged.'
            else:
                message = 'Loom could not verify this link. It may be unavailable, private, or deleted. The saved link is unchanged; use Forget Loom link to remove it locally.'
            if self.recordings:
                self.recordings.update_actions()
                self.recordings.message.setText(message)
        self.loom_probe(['loom', 'video', 'get', identifier, '-o', 'json', '--output-summary', 'none'], checked)

    def connect_loom(self):
        cli = self.find_cli()
        if not cli:
            self.notice('Install the official TWG CLI using Sharing instructions, then connect Loom.')
            return
        terminal = shutil.which('gnome-terminal')
        command = [terminal, '--', 'bash', str(ROOT / 'scripts/connect-loom.sh'), cli] if terminal else ['x-terminal-emulator', '-e', 'bash', str(ROOT / 'scripts/connect-loom.sh'), cli]
        try:
            subprocess.Popen(command, start_new_session=True)
            self.notice('Complete consent and browser OAuth sign-in in the terminal, then return here. No video is uploaded by connecting.')
        except OSError as exc:
            self.notice(f'Could not open the sign-in terminal: {exc}')

    @staticmethod
    def find_cli():
        for path in [shutil.which('twg'), str(Path.home() / '.local/bin/twg'), str(Path.home() / '.local/share/glint/twg')]:
            if path and Path(path).is_file() and os.access(path, os.X_OK):
                return path
        return None

    def save_upload_metadata(self, path, *, expected_identity=None, **fields):
        try:
            self.upload_store.update(path, expected_identity=expected_identity, **fields)
        except (OSError, ValueError):
            if expected_identity is not None:
                self._upload_fallback_state = self.upload_store.get(path)
            self._upload_metadata_warning = 'The Loom status could not be saved locally. Copy the link before closing.'
            return False
        if self.recordings:
            self.recordings.update_actions()
        return True

    def update_upload_panel(self, heading, detail, *, active=False, percent=None, retry=False):
        self.upload_panel.show()
        self.upload_heading.setText(heading)
        self._upload_detail = detail
        self.upload_detail.setText(detail)
        self.upload_progress.setVisible(active)
        self.upload_progress.setRange(0, 0 if percent is None else 100)
        if percent is not None:
            self.upload_progress.setValue(round(percent))
        url = valid_share_url(getattr(self, '_upload_url', ''))
        self.upload_link.setText(url)
        self.upload_link.setVisible(bool(url))
        for button in (self.upload_open, self.upload_copy):
            button.setVisible(bool(url))
            button.setEnabled(bool(url) and not active)
        self.upload_retry.setVisible(active or retry)
        self.upload_retry.setText('Cancel upload…' if active else 'Retry upload…')
        self.upload_library.setEnabled(not active and not self.busy)

    def update_upload_elapsed(self):
        if not self._upload_active:
            return
        seconds = max(0, round(time.monotonic() - self._upload_started))
        elapsed = f'{seconds // 60}:{seconds % 60:02d}'
        self.upload_detail.setText(f'{self._upload_detail} · Elapsed {elapsed}')

    def open_uploaded_video(self):
        self.refresh_upload_link()
        url = valid_share_url(getattr(self, '_upload_url', ''))
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def copy_uploaded_link(self):
        self.refresh_upload_link()
        url = valid_share_url(getattr(self, '_upload_url', ''))
        if url:
            QApplication.clipboard().setText(url)
            self.upload_detail.setText('Loom link copied. Review its sharing permissions before sending.')

    def refresh_upload_link(self):
        path = getattr(self, '_upload_file', None)
        if self._upload_active or not path:
            return
        if (not path.is_file() or (getattr(self, '_upload_identity', None) is not None
                and self.upload_store.file_identity(path) != self._upload_identity)):
            self._upload_url = None
            self.upload_panel.hide()
            return
        state = self.upload_store.get(path)
        if (getattr(self, '_upload_metadata_warning', '')
                and getattr(self, '_upload_fallback_state', None) == state):
            return
        self._upload_fallback_state = None
        self._upload_metadata_warning = ''
        if not state or state.get('status') == 'deleted':
            self._upload_url = None
            self.upload_panel.hide()
        else:
            self._upload_url = valid_share_url(state.get('url')) or None

    def retry_upload(self):
        if self._upload_active:
            answer = QMessageBox.question(self, 'Cancel Loom upload?',
                'Your local recording will stay safe. Loom may already have received the video. Check your Loom library before uploading again.',
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if answer != QMessageBox.Yes or not self._upload_active:
                return
            self.process.kill()
            self.process.waitForFinished(1000)
            if self._upload_active:
                self.upload_end('Upload canceled. Check Loom before retrying; your local recording is safe.', state='uncertain')
            return
        path = getattr(self, '_upload_file', None)
        if path:
            self.set_last(path)
            self.upload()

    def upload(self, confirmed=False):
        if not self.last_file or self.busy or self.recording or self.counting or self._closing:
            return
        try:
            size = self.last_file.stat().st_size
            if not self.last_file.is_file() or not os.access(self.last_file, os.R_OK):
                raise OSError('unreadable file')
        except OSError:
            self.notice('The local recording is missing or unreadable. Choose an existing video before uploading.')
            return
        if size == 0:
            self.notice('This recording is empty. Nothing was uploaded.')
            return
        if self.last_file.suffix == '.mkv':
            if self.last_file.with_suffix('.mp4').exists():
                self.notice('An MP4 with this name already exists. Review it in Recordings before preparing this MKV. Both files are preserved.')
                return
            self.busy = True
            self.lock_controls(True)
            self.record_button.setEnabled(False)
            self.recording_error = 'Recovered the original recording. Play it back before uploading to Loom.'
            self.remux(self.last_file)
            return
        cli = self.find_cli()
        if not cli:
            self.sharing_settings()
            return
        if size >= 4 * 1024 ** 3:
            self.notice('This video exceeds Loom’s 4 GB upload limit. The local file is saved.')
            return
        previous = self.upload_store.get(self.last_file)
        if not confirmed and previous.get('status') in ('uploaded', 'processing', 'uncertain', 'uploading'):
            answer = QMessageBox.question(self, 'Upload this recording again?',
                'This recording may already exist in Loom. Uploading again can create a duplicate. Check your Loom library before continuing.',
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if answer != QMessageBox.Yes:
                return
        identity = self.upload_store.file_identity(self.last_file)
        if identity is None:
            self.notice('The local recording is missing or unreadable.')
            return
        self._upload_identity = identity
        self._upload_fallback_state = None
        self.busy = True
        self.lock_controls(True)
        self.record_button.setEnabled(False)
        self._upload_cli = cli
        self._upload_file = self.last_file.absolute()
        self._upload_visibility = self.prefs.value('visibility', 'owner')
        if self._upload_visibility not in ('owner', 'workspace', 'public'):
            self._upload_visibility = 'owner'
        self._upload_auto_title = self.prefs.value('loom_auto_titles', True, type=bool)
        self._upload_url = None
        self._upload_metadata_warning = ''
        self._upload_active = True
        self._upload_transfer_started = False
        self._upload_started = time.monotonic()
        self._upload_output = self._upload_errors = ''
        self._upload_result = {}
        self.save_upload_metadata(self._upload_file, expected_identity=self._upload_identity, status='uploading', error='',
                                  visibility_warning='', visibility=self._upload_visibility)
        self.update_upload_panel('Preparing Loom upload', 'Checking the installed CLI. Your local recording stays safe.', active=True)
        self.upload_timer.start()
        self.notice('Preparing Loom upload…')
        self.start_upload_process(['loom', 'video', 'upload', '--help'], self.upload_help)

    def start_upload_process(self, args, finished, *, stream=False):
        previous = self.process
        self.process = QProcess(self)
        if previous is not None:
            previous.deleteLater()
        process = self.process
        process.setProgram(self._upload_cli)
        process.setArguments(args)
        process.finished.connect(lambda code, status: finished(code, status)
            if self.process is process and self._upload_active else None)
        process.errorOccurred.connect(lambda error: self.upload_process_error(error)
            if self.process is process and self._upload_active else None)
        if not stream:
            timer = QTimer(self)
            timer.setSingleShot(True)
            def expired():
                if self.process is process and self._upload_active:
                    process.kill()
                    if getattr(self, '_upload_url', None):
                        self.upload_end('Uploaded, but the sharing check timed out. Review permissions in Loom before sharing.', state=self._upload_result.get('status', 'uploaded'), visibility_warning='Sharing permissions were not confirmed.')
                    else:
                        self.upload_end('The Loom CLI check timed out. Your local recording is safe.', state='failed')
            timer.timeout.connect(expired)
            process.finished.connect(timer.stop)
            process.finished.connect(timer.deleteLater)
            def process_error(error):
                if error == QProcess.FailedToStart:
                    timer.stop()
                    timer.deleteLater()
            process.errorOccurred.connect(process_error)
            timer.timeout.connect(timer.deleteLater)
            timer.start(20000)
        if stream:
            process.readyReadStandardOutput.connect(lambda: self.read_upload_output(False))
            process.readyReadStandardError.connect(lambda: self.read_upload_output(True))
        process.start()

    def upload_process_error(self, error):
        if error == QProcess.FailedToStart:
            if getattr(self, '_upload_url', None):
                self.upload_end('Uploaded, but the sharing command could not start. Review permissions in Loom before sharing. Your local file is saved.', state=getattr(self, '_upload_result', {}).get('status', 'uploaded'), visibility_warning='Sharing permissions were not confirmed.')
            else:
                self.upload_end('Could not start the Loom CLI. Your local file is saved.', state='failed')

    def upload_help(self, code, status):
        help_text = bytes(self.process.readAllStandardOutput()).decode(errors='replace') + bytes(self.process.readAllStandardError()).decode(errors='replace')
        if code != 0 or status != QProcess.NormalExit:
            self.upload_end('This TWG CLI does not support video uploads. Update it and connect your Loom account.', state='failed')
            return
        from .loom import upload_args, supports_option
        try:
            args = upload_args(self._upload_file, help_text, self._upload_visibility,
                               title=recording_title(self._upload_file),
                               prefer_loom_titles=self._upload_auto_title)
        except ValueError:
            self.upload_end('Upload syntax could not be verified. Open Sharing for connection instructions.', state='failed')
            return
        self._upload_sets_visibility = supports_option(help_text, '--visibility')
        self._upload_transfer_started = True
        self.update_upload_panel('Uploading to Loom', 'The CLI does not report byte progress. Your local recording stays safe.', active=True)
        self.notice('Uploading to Loom…')
        self.start_upload_process(args, self.upload_done, stream=True)

    def read_upload_output(self, errors=False):
        channel = self.process.readAllStandardError if errors else self.process.readAllStandardOutput
        chunk = bytes(channel()).decode(errors='replace')
        field = '_upload_errors' if errors else '_upload_output'
        setattr(self, field, (getattr(self, field, '') + chunk)[-1024 * 1024:])
        if not self._upload_active:
            return
        progress = parse_upload_progress(getattr(self, field))
        if progress:
            processing = progress['stage'] == 'processing'
            percent = progress.get('percent')
            # A transfer percentage never implies processing is complete.
            heading = 'Loom is processing your video' if processing else 'Uploading to Loom'
            if percent is not None:
                heading += f' · {percent:g}%'
            detail = 'Loom has not confirmed completion.' if processing else 'Your local recording stays safe.'
            self.update_upload_panel(heading, detail, active=True, percent=percent)

    def upload_source_matches(self):
        return self.upload_store.file_identity(self._upload_file) == self._upload_identity

    def upload_done(self, code, status):
        if not self.upload_source_matches():
            self.upload_end('', state='uncertain')
            return
        self.read_upload_output(False)
        self.read_upload_output(True)
        output, errors = self._upload_output, self._upload_errors
        result = parse_upload_result(output, code if status == QProcess.NormalExit else -1, errors)
        self._upload_result = result
        self._upload_url = result.get('url') or None
        if self._upload_url or result.get('remote_id'):
            self.save_upload_metadata(self._upload_file, expected_identity=self._upload_identity, **result)
        if code == 0 and status == QProcess.NormalExit and self._upload_url:
            if not self._upload_sets_visibility:
                self.update_upload_panel('Applying Loom sharing permissions', 'The video was received. Confirming who can watch it…', active=True)
                self.notice('Uploaded. Applying your Loom sharing setting…')
                self.start_upload_process(['loom', 'video', 'visibility', 'set', self._upload_url,
                    '--visibility', self._upload_visibility, '-o', 'json', '--output-summary', 'none'], self.visibility_done)
                return
            QApplication.clipboard().setText(self._upload_url)
            self.upload_end('Uploaded to Loom. Link copied. Loom may still be processing the video.', state=result['status'])
        elif code == 0 and status == QProcess.NormalExit:
            self.upload_end('The upload command finished without a Loom link. Check your Loom library before retrying.', state='uncertain')
        else:
            detail = (errors or output).lower()
            account = parse_account_status(output, code, errors)
            if account['status'] == 'disconnected' or any(word in detail for word in ('oauth', 'login', 'unauthorized', 'authentication', 'token')):
                self.loom_account = {'status': 'disconnected'}
                advice = 'Open Sharing and connect your Loom account again.'
            elif any(word in detail for word in ('plan', 'upgrade', 'subscription', 'trial')):
                advice = 'Uploads require Business, Business + AI, or Enterprise, excluding trials.'
            else:
                advice = 'Check your connection and Loom library before retrying. A failed command may leave a remote video.'
            self.upload_end('Loom upload failed. Your local recording is safe. ' + advice, state=result['status'])

    def visibility_done(self, code, status):
        if not self.upload_source_matches():
            self.upload_end('', state='uncertain')
            return
        if code == 0 and status == QProcess.NormalExit:
            QApplication.clipboard().setText(self._upload_url)
            self.upload_end('Uploaded to Loom. Sharing setting applied. Link copied.', state=getattr(self, '_upload_result', {}).get('status', 'uploaded'))
        else:
            self.upload_end('Uploaded, but Loom could not apply the sharing setting. Review permissions in Loom before sharing the link.', state=getattr(self, '_upload_result', {}).get('status', 'uploaded'), visibility_warning='Sharing permissions were not confirmed.')

    def upload_end(self, text, state='failed', visibility_warning=''):
        self._upload_active = False
        self.upload_timer.stop()
        self.busy = False
        self.lock_controls(False)
        self.record_button.setEnabled(bool(self.engine) and self.configuration_valid)
        source_matches = self.upload_source_matches()
        if not source_matches:
            self._upload_url = None
            self._upload_metadata_warning = ''
            self._upload_fallback_state = None
            text = 'The local recording changed during upload. Check Loom for the original video; no link was attached to this file.'
            state = 'uncertain'
        if getattr(self, '_upload_file', None) and source_matches:
            fields = dict(status=state, error=text if state in ('failed', 'uncertain') else '',
                          visibility_warning=visibility_warning)
            if getattr(self, '_upload_url', None):
                fields['url'] = self._upload_url
            self.save_upload_metadata(self._upload_file, expected_identity=self._upload_identity, **fields)
        headings = {'uploaded': 'Uploaded to Loom', 'processing': 'Received by Loom · processing',
                    'uncertain': 'Check Loom before retrying', 'failed': 'Upload could not finish'}
        detail = text
        if state == 'processing':
            detail += ' Processing has no measurable progress. Use Check Loom link in Recordings to refresh the title.'
        if getattr(self, '_upload_metadata_warning', ''):
            detail += ' ' + self._upload_metadata_warning
        self.update_upload_panel(headings.get(state, 'Loom upload'), detail,
                                 retry=state in ('failed', 'uncertain') and not getattr(self, '_upload_url', None))
        self.notice(text)
        if self.quit_after_save:
            self.close()

    def engine_notice(self, text):
        warnings = getattr(self.engine, 'warnings', [])
        if isinstance(warnings, (list, tuple)):
            messages = [warning for warning in warnings if isinstance(warning, str) and warning.strip()]
            if messages:
                text += '\n' + '\n'.join(messages)
        self.notice(text)

    def notice(self, text):
        self.status.setText(text)

    def restore_capture_window(self):
        # Only undo our screen-capture hide. Camera callbacks must leave the
        # user's current visibility/state alone and must not request focus.
        state = self._capture_window_state
        self._capture_window_state = None
        if state is not None and not self._closing:
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
            try:
                self.setWindowState(state)
                self.show()
            finally:
                self.setAttribute(Qt.WA_ShowWithoutActivating, False)

    def reveal(self):
        # Explicit tray/bubble/launcher requests may unminimize, but must keep
        # maximization. They also supersede a pending capture restoration.
        self._capture_window_state = None
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    @staticmethod
    def record_icon():
        pix = QPixmap(64, 64)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor('#f8957e'))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(8, 8, 48, 48)
        painter.end()
        return QIcon(pix)

    def hideEvent(self, event):
        if not (self.recording or self.counting or self.preparing_audio):
            self.idle_audio.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        if getattr(self, 'audio_check_dialog', None):
            self.audio_check_dialog.reject()
            event.ignore()
            return
        if self.counting:
            self.cancel_countdown()
        if self.recording:
            answer = QMessageBox.question(self, 'Save your recording?', 'Stop recording, save the video, and quit Untangle?', QMessageBox.Save | QMessageBox.Cancel, QMessageBox.Cancel)
            event.ignore()
            if answer == QMessageBox.Save:
                self.quit_after_save = True
                self.stop()
            return
        if self._title_job is not None:
            self._closing = True
            job, self._title_job = self._title_job, None
            job.cancel()
            job.deleteLater()
            self.busy = False
        if self.busy and not self.preparing_audio:
            self.notice('Finishing your video. Untangle will stay open until it is safe to close.')
            event.ignore()
            return
        self._closing = True
        if self._title_job is not None:
            job, self._title_job = self._title_job, None
            job.cancel()
            job.deleteLater()
        for process in tuple(self.loom_probes):
            process.kill()
            process.waitForFinished(1000)
        self.loom_probes.clear()
        self.upload_timer.stop()
        self._audio_generation += 1
        if self.audio_worker:
            self.audio_worker.wait()
            self.audio_worker = None
        self.busy = self.preparing_audio = False
        self.idle_audio.stop()
        self.idle_audio.release_owner()
        if self.recordings:
            self.recordings.stop_thumbnails()
            self.recordings.release()
        if self.camera_adjustments is not None:
            self.camera_adjustments.leave()
        self._preview_generation = getattr(self, '_preview_generation', 0) + 1
        self.configure_timer.stop()
        self.start_timer.stop()
        self.zoom_timer.stop()
        self.hide_bubble()
        self.bubble.close()
        self.window_catalog.close()
        self.save_preferences()
        self.hotkeys.requestInterruption()
        self.hotkeys.wait(1500)
        self.tray.hide()
        if self.engine:
            self.engine.close()
            self.engine = None
        owner = getattr(self, '_capture_owner', None)
        if owner is not None:
            self.audio_devices.release_capture(owner)
            self._capture_owner = None
        try:
            self.audio_devices.restore()
        except AudioDeviceError:
            pass  # Never force restoration while another client owns streams.
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Untangle')
    app.setDesktopFileName('tech.truedevs.Untangle')
    app.setWindowIcon(QIcon(str(ICON)))
    app.setStyle('Fusion')
    load_fonts(app)
    apply_theme(app, QSettings('TrueDevs', 'Glint').value('theme', 'light'))
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtCore import QLockFile, QStandardPaths
    runtime = Path(QStandardPaths.writableLocation(QStandardPaths.RuntimeLocation))
    runtime.mkdir(parents=True, exist_ok=True)
    instance_lock = QLockFile(str(runtime / 'truedevs-glint.lock'))
    owns_lock = instance_lock.tryLock(0)
    socket = QLocalSocket()
    if not owns_lock:
        for attempt in range(10):
            socket.abort()
            socket.connectToServer('truedevs-glint-' + str(os.getuid()))
            if socket.waitForConnected(300):
                socket.write(b'open')
                socket.waitForBytesWritten(300)
                break
            time.sleep(.1)
        return 0
    QLocalServer.removeServer('truedevs-glint-' + str(os.getuid()))
    server = QLocalServer()
    if not server.listen('truedevs-glint-' + str(os.getuid())):
        raise RuntimeError('Could not open Untangle’s local activation socket: ' + server.errorString())
    window = Window()
    def activate():
        client = server.nextPendingConnection()
        if client:
            client.disconnectFromServer()
            client.deleteLater()
        window.reveal()
    server.newConnection.connect(activate)
    window.show()
    signal.signal(signal.SIGINT, lambda *_: window.close())
    signal.signal(signal.SIGTERM, lambda *_: window.close())
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
