"""V4L2 picture controls (contrast, exposure, focus…) and the page that edits them."""
from .diagnostics import observed, failure as diagnostic_failure
from dataclasses import dataclass, field
import re
import subprocess

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget)


GROUPS = (
    ('Device framing', ('zoom_absolute', 'pan_absolute', 'tilt_absolute')),
    ('Picture', ('brightness', 'contrast', 'saturation', 'hue', 'gamma', 'sharpness')),
    ('Light', ('auto_exposure', 'exposure_time_absolute', 'gain', 'backlight_compensation',
               'exposure_dynamic_framerate', 'power_line_frequency')),
    ('Colour', ('white_balance_automatic', 'white_balance_temperature')),
    ('Focus', ('focus_automatic_continuous', 'focus_absolute')),
    ('Camera light', ('led1_mode', 'led1_frequency')),
)
GROUP_NOTES = {
    'Device framing': 'The camera zooms on its sensor, which stays sharper than the sidebar Zoom. '
                      'The sidebar Zoom crops afterwards, so the two multiply. Pan and tilt move a zoomed view.',
}
LABELS = {
    'brightness': 'Brightness', 'contrast': 'Contrast', 'saturation': 'Saturation', 'hue': 'Hue',
    'gamma': 'Gamma', 'sharpness': 'Sharpness', 'auto_exposure': 'Exposure',
    'exposure_time_absolute': 'Exposure time', 'gain': 'Gain',
    'backlight_compensation': 'Backlight compensation',
    'exposure_dynamic_framerate': 'Lower frame rate in low light',
    'power_line_frequency': 'Anti-flicker', 'white_balance_automatic': 'Automatic white balance',
    'white_balance_temperature': 'Temperature', 'focus_automatic_continuous': 'Autofocus',
    'focus_absolute': 'Focus', 'zoom_absolute': 'Zoom', 'pan_absolute': 'Pan', 'tilt_absolute': 'Tilt',
    'led1_mode': 'Camera light', 'led1_frequency': 'Blink speed',
}
MENU_LABELS = {'auto_exposure': {1: 'Manual', 3: 'Automatic'},
               'led1_mode': {0: 'Off', 1: 'On', 2: 'Blink', 3: 'When camera is in use'}}
# UVC zoom is a percentage on the Brio; pan and tilt are arc-seconds.
DISPLAY = {'zoom_absolute': lambda value: f'{value}%',
           'pan_absolute': lambda value: f'{value / 3600:g}°',
           'tilt_absolute': lambda value: f'{value / 3600:g}°'}
SUPPORTED = tuple(name for _, names in GROUPS for name in names)
# Manual control -> (automatic partner, partner values that let the manual control work).
MANUAL = {
    'white_balance_temperature': ('white_balance_automatic', (0,)),
    'exposure_time_absolute': ('auto_exposure', (1,)),
    'focus_absolute': ('focus_automatic_continuous', (0,)),
    'led1_frequency': ('led1_mode', (2,)),
}
MANUAL_HINTS = {
    'white_balance_temperature': 'Turn off automatic white balance to adjust this.',
    'exposure_time_absolute': 'Set Exposure to Manual to adjust this.',
    'focus_absolute': 'Turn off autofocus to adjust this.',
    'led1_frequency': 'Set Camera light to Blink to adjust this.',
}
# Mains frequency is regional; a camera's 60 Hz default would make 50 Hz lights flicker.
RESET_SKIP = ('power_line_frequency',)
AUTOMATIC = tuple(partner for partner, _ in MANUAL.values())

_CONTROL = re.compile(r'^\s*(\w+)\s+0x[0-9a-f]+\s+\((\w+)\)\s*:\s*(.*)$')
_MENU = re.compile(r'^\s+(\d+):\s+(.+?)\s*$')


class CameraControlError(RuntimeError):
    """v4l2-ctl is missing, timed out, or rejected a value."""


@dataclass
class Control:
    name: str
    kind: str
    value: int
    default: int
    minimum: int = 0
    maximum: int = 1
    step: int = 1
    flags: tuple = ()
    menu: dict = field(default_factory=dict)

    @property
    def label(self):
        return LABELS.get(self.name, self.name.replace('_', ' ').capitalize())

    def display(self, value):
        return DISPLAY.get(self.name, str)(value)

    def clamp(self, value):
        if self.kind == 'menu':
            return value if value in self.menu else self.default
        value = max(self.minimum, min(self.maximum, int(value)))
        step = max(1, self.step)
        return min(self.maximum, self.minimum + round((value - self.minimum) / step) * step)


def parse_controls(text):
    """Supported, writable controls from `v4l2-ctl --list-ctrls-menus`, in display order."""
    found, current = {}, None
    for line in text.splitlines():
        match = _CONTROL.match(line)
        if match:
            name, kind, rest = match.groups()
            fields = dict(re.findall(r'(\w+)=(\S+)', rest))
            flag_text = re.search(r'flags=(.*)$', rest)
            flags = tuple(flag.strip() for flag in flag_text[1].split(',')
                          if not flag.strip().startswith('0x')) if flag_text else ()
            current = None
            if (name not in SUPPORTED or kind not in ('int', 'bool', 'menu')
                    or 'read-only' in flags or 'disabled' in flags):
                continue
            try:
                number = lambda key, fallback=0: int(fields.get(key, fallback))
                current = found[name] = Control(name, kind, number('value'), number('default'),
                    number('min'), number('max', 1), number('step', 1), flags)
            except ValueError:
                continue
            continue
        match = _MENU.match(line)
        if match and current is not None and current.kind == 'menu':
            index = int(match[1])
            current.menu[index] = MENU_LABELS.get(current.name, {}).get(index, match[2])
    return [found[name] for name in SUPPORTED if name in found]


@observed("camera_image.read_controls")
def read_controls(device):
    try:
        result = subprocess.run(['v4l2-ctl', '-d', device, '--list-ctrls-menus'],
                                capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CameraControlError(f'Could not read camera controls: {exc}') from exc
    if result.returncode:
        raise CameraControlError((result.stderr or 'Could not read camera controls.').strip())
    return parse_controls(result.stdout)


@observed("camera_image.write_controls")
def write_controls(device, values, current=None):
    """Write automatic modes, then picture values, then manual partners, each separately.

    A manual value is dropped while its automatic mode stays on: some drivers
    reject it, and a rejected batch must not take brightness or contrast with it.
    """
    merged = {**(current or {}), **values}
    values = {name: value for name, value in values.items() if manual_allowed(name, merged)}
    batches = ([item for item in values.items() if item[0] in AUTOMATIC],
               [item for item in values.items() if item[0] not in AUTOMATIC and item[0] not in MANUAL],
               [item for item in values.items() if item[0] in MANUAL])
    errors = []
    for batch in batches:
        if not batch:
            continue
        setting = ','.join(f'{name}={int(value)}' for name, value in batch)
        try:
            result = subprocess.run(['v4l2-ctl', '-d', device, '--set-ctrl', setting],
                                    capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f'Could not change camera settings: {exc}')
            continue
        if result.returncode:
            errors.append((result.stderr or 'The camera rejected a setting.').strip())
    if errors:
        raise CameraControlError(' '.join(errors))


def manual_allowed(name, values):
    if name not in MANUAL:
        return True
    partner, allowed = MANUAL[name]
    return partner not in values or values[partner] in allowed


@observed("camera_image.restore_saved")
def restore_saved(device, saved):
    """Reapply saved values, clamped to this camera's current ranges. Returns applied values."""
    if not saved:
        return {}
    controls = {control.name: control for control in read_controls(device)}
    values = {name: controls[name].clamp(value) for name, value in saved.items()
              if name in controls and isinstance(value, int) and not isinstance(value, bool)}
    current = {name: control.value for name, control in controls.items()}
    merged = {**current, **values}
    values = {name: value for name, value in values.items() if manual_allowed(name, merged)}
    if values:
        write_controls(device, values, current)
    return values


class CameraAdjustments(QWidget):
    """Full-page editor. The window owns the engine and attaches the live preview."""
    back_requested = Signal()
    saved_changed = Signal(str, dict)  # camera name, values the user changed
    preview_resized = Signal(int, int)

    def __init__(self, preview, parent=None):
        super().__init__(parent)
        self.setObjectName('cameraAdjustmentsPage')
        self.device = None
        self.camera_name = ''
        self.controls = {}
        self.saved = {}
        self.pending = {}
        self.widgets = {}
        self.apply_timer = QTimer(self)
        self.apply_timer.setSingleShot(True)
        self.apply_timer.setInterval(120)
        self.apply_timer.timeout.connect(self.apply_pending)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)
        header = QHBoxLayout()
        self.back = QPushButton('←  Back to recorder')
        self.back.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back)
        header.addStretch()
        self.reset_button = QPushButton('Reset to defaults')
        self.reset_button.setAccessibleName('Reset camera settings to defaults')
        self.reset_button.clicked.connect(self.reset_defaults)
        header.addWidget(self.reset_button)
        layout.addLayout(header)
        title = QLabel('Camera settings')
        title.setObjectName('title')
        layout.addWidget(title)
        self.subtitle = QLabel('')
        self.subtitle.setObjectName('muted')
        layout.addWidget(self.subtitle)
        body = QHBoxLayout()
        body.setSpacing(20)
        stage = QFrame()
        stage.setObjectName('previewWorkspace')
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(12, 12, 12, 12)
        self.preview = preview
        self.preview.resized.connect(self.preview_resized.emit)
        stage_layout.addWidget(self.preview, 1)
        body.addWidget(stage, 1)
        self.scroll = QScrollArea()
        self.scroll.setObjectName('cameraControls')
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedWidth(340)
        self.panel = QWidget()
        self.panel_layout = QVBoxLayout(self.panel)
        self.panel_layout.setContentsMargins(0, 0, 12, 0)
        self.panel_layout.setSpacing(10)
        self.scroll.setWidget(self.panel)
        body.addWidget(self.scroll)
        layout.addLayout(body, 1)
        self.message = QLabel('')
        self.message.setObjectName('muted')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

    def load(self, device, camera_name, saved=None):
        self.apply_timer.stop()
        self.pending.clear()
        self.device, self.camera_name = device, camera_name
        self.saved = dict(saved or {})
        self.subtitle.setText(f'{camera_name} · changes apply live and are remembered for this camera.')
        self.message.clear()
        try:
            controls = read_controls(device)
        except CameraControlError as exc:
            diagnostic_failure("camera.control.failed", exc)
            controls = []
            self.message.setText(str(exc))
        self.controls = {control.name: control for control in controls}
        self.rebuild()
        if not controls and not self.message.text():
            self.message.setText('This camera has no adjustable picture settings.')
        self.reset_button.setEnabled(bool(controls))

    def rebuild(self):
        while self.panel_layout.count():
            item = self.panel_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.widgets = {}
        for title, names in GROUPS:
            present = [self.controls[name] for name in names if name in self.controls]
            if not present:
                continue
            heading = QLabel(title)
            heading.setObjectName('section')
            self.panel_layout.addWidget(heading)
            if title in GROUP_NOTES:
                note = QLabel(GROUP_NOTES[title])
                note.setObjectName('muted')
                note.setWordWrap(True)
                self.panel_layout.addWidget(note)
            grid = QGridLayout()
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(4)
            row = 0
            for control in present:
                row = self.add_control(grid, row, control)
            holder = QWidget()
            holder.setLayout(grid)
            self.panel_layout.addWidget(holder)
        self.panel_layout.addStretch()
        self.update_dependencies()

    def add_control(self, grid, row, control):
        if control.kind == 'bool' or (control.minimum, control.maximum) == (0, 1):
            box = QCheckBox(control.label)
            box.setChecked(bool(control.value))
            box.toggled.connect(lambda checked, name=control.name: self.changed(name, int(checked)))
            grid.addWidget(box, row, 0, 1, 2)
            self.widgets[control.name] = (box, None)
            return row + 1
        grid.addWidget(QLabel(control.label), row, 0)
        if control.kind == 'menu':
            combo = QComboBox()
            combo.setAccessibleName(control.label)
            for index, text in control.menu.items():
                combo.addItem(text, index)
            combo.setCurrentIndex(max(0, combo.findData(control.value)))
            combo.currentIndexChanged.connect(
                lambda _index, name=control.name, widget=combo: self.changed(name, widget.currentData()))
            grid.addWidget(combo, row + 1, 0, 1, 2)
            self.widgets[control.name] = (combo, None)
            return row + 2
        value = QLabel(control.display(control.value))
        value.setObjectName('muted')
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(value, row, 1)
        slider = QSlider(Qt.Horizontal)
        slider.setAccessibleName(control.label)
        slider.setRange(control.minimum, control.maximum)
        slider.setSingleStep(max(1, control.step))
        slider.setPageStep(max(control.step, (control.maximum - control.minimum) // 10))
        slider.setValue(control.value)
        slider.setToolTip(f'{control.label}: {control.minimum}–{control.maximum}, default {control.default}')
        slider.valueChanged.connect(lambda number, name=control.name: self.changed(name, number))
        grid.addWidget(slider, row + 1, 0, 1, 2)
        self.widgets[control.name] = (slider, value)
        return row + 2

    def current_values(self):
        values = {name: control.value for name, control in self.controls.items()}
        values.update(self.pending)
        return values

    def update_dependencies(self):
        values = self.current_values()
        for name, (widget, value_label) in self.widgets.items():
            allowed = manual_allowed(name, values)
            widget.setEnabled(allowed)
            if value_label is not None:
                value_label.setEnabled(allowed)
            if name in MANUAL:
                widget.setToolTip('' if allowed else MANUAL_HINTS[name])

    def changed(self, name, value):
        control = self.controls.get(name)
        if control is None or value is None:
            return
        value = control.clamp(value)
        widget, value_label = self.widgets[name]
        if isinstance(widget, QSlider) and widget.value() != value:
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        if value_label is not None:
            value_label.setText(control.display(value))
        self.pending[name] = value
        self.saved[name] = value
        self.update_dependencies()
        self.apply_timer.start()

    def apply_pending(self):
        if not self.pending or not self.device:
            return
        values, self.pending = self.pending, {}
        try:
            write_controls(self.device, values, self.current_values())
        except CameraControlError as exc:
            diagnostic_failure("camera.control.failed", exc)
            self.message.setText(str(exc))
            self.refresh_values()
            return
        self.message.clear()
        self.saved_changed.emit(self.camera_name, dict(self.saved))
        if any(name in AUTOMATIC for name in values):
            # Turning auto off exposes the camera's own current manual value.
            self.refresh_values()

    def refresh_values(self):
        try:
            controls = read_controls(self.device)
        except CameraControlError as exc:
            diagnostic_failure("camera.control.failed", exc)
            self.message.setText(str(exc))
            return
        for control in controls:
            self.controls[control.name] = control
            if control.name in self.pending or control.name not in self.widgets:
                continue
            widget, value_label = self.widgets[control.name]
            widget.blockSignals(True)
            if isinstance(widget, QSlider):
                widget.setValue(control.value)
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(control.value))
            else:
                widget.setCurrentIndex(max(0, widget.findData(control.value)))
            widget.blockSignals(False)
            if value_label is not None:
                value_label.setText(control.display(control.value))
        self.update_dependencies()

    def reset_defaults(self):
        if not self.controls:
            return
        self.apply_timer.stop()
        self.pending.clear()
        self.saved.clear()
        try:
            write_controls(self.device, {name: control.default for name, control in self.controls.items()
                                         if name not in RESET_SKIP}, self.current_values())
        except CameraControlError as exc:
            diagnostic_failure("camera.control.failed", exc)
            self.message.setText(str(exc))
        else:
            self.message.setText('Camera settings reset to defaults.')
        self.saved_changed.emit(self.camera_name, {})
        self.refresh_values()

    def leave(self):
        """Flush a pending change so leaving never drops the last slider move."""
        if self.apply_timer.isActive():
            self.apply_timer.stop()
            self.apply_pending()
