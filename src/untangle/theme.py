"""Shared Clearline colors, bundled fonts and Qt styling. No device access."""
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette


THEMES = {
    'light': dict(
        canvas='#F6F7F9', panel='#FFFFFF', text='#202936', muted='#586373',
        action='#C33C0A', action_hover='#A93208', on_action='#FFFFFF',
        selection='#FFF0E8', border='#D5DAE1', control_border='#858E9A', hover='#ECEFF3',
        disabled='#657080', disabled_bg='#E9ECF0', focus='#C33C0A',
        warning='#805000', warning_bg='#FFF1CF', error='#B42332', error_bg='#FFF0F1',
        success='#24704B', recording='#B42332', meter_track='#D5DAE1',
    ),
    'dark': dict(
        canvas='#191B1F', panel='#23262B', text='#F1F2F4', muted='#B6BDC7',
        action='#FF995F', action_hover='#FFB080', on_action='#281A12',
        selection='#473026', border='#41464F', control_border='#78818E', hover='#30343B',
        disabled='#9DA5B0', disabled_bg='#2D3138', focus='#FF995F',
        warning='#F6CE80', warning_bg='#42351E', error='#FFA6AE', error_bg='#46262D',
        success='#8CD4AB', recording='#FFA6AE', meter_track='#41464F',
    ),
}


def tokens(name='light'):
    """Return a copy of the named palette; unknown names fall back to light."""
    return THEMES.get(name, THEMES['light']).copy()


def load_fonts(application):
    """Register bundled, unmodified OFL fonts once per QApplication."""
    if not application.property('untangleFontsLoaded'):
        directory = Path(__file__).resolve().parents[2] / 'assets' / 'fonts'
        loaded = []
        for path in sorted(directory.glob('*.ttf')):
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id >= 0:
                loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
        application.setProperty('untangleFontsLoaded', loaded)
    font = QFont('Inter')
    font.setPixelSize(14)
    application.setFont(font)


def stylesheet(name='light'):
    """Style semantic surfaces rather than painting every child widget."""
    c = tokens(name)
    assets = Path(__file__).resolve().parents[2] / 'assets'
    variant = 'dark' if name == 'dark' else 'light'
    for icon in ('chevron', 'check', 'radio'):
        c[icon] = (assets / f'clearline-{icon}-{variant}.svg').as_posix()
    return """
QWidget { color: %(text)s; font-family: 'Inter', 'DejaVu Sans'; font-size: 14px; }
QMainWindow, QDialog, QMessageBox, QFileDialog, QWidget#recordingsPage { background: %(canvas)s; }
QLabel { background: transparent; font-size: 14px; }
QLabel#muted { color: %(muted)s; font-size: 13px; }
QLabel#eyebrow { color: %(action)s; font-size: 13px; font-weight: 600; }
QLabel#title { font-family: 'Inter'; font-size: 24px; font-weight: 600; }
QLabel#section { color: %(muted)s; font-size: 13px; font-weight: 600; }
QFrame#panel, QWidget#panel { background: %(panel)s; border: 1px solid %(border)s; border-radius: 8px; }
QFrame#previewWorkspace { background: %(hover)s; border: 1px solid %(border)s; border-radius: 8px; }
QPushButton#cameraZoomStep { min-height: 20px; padding: 1px 4px; }
QPushButton#cameraZoomReset { min-height: 18px; padding: 2px 6px; }
QScrollArea, QScrollArea#sidebar, QStackedWidget { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollArea#sidebar { background: transparent; border: none; border-right: 1px solid %(border)s; border-radius: 0; }
QScrollArea#sidebar > QWidget, QScrollArea#sidebar > QWidget > QWidget { background: transparent; border: none; }
QWidget#setupColumn { background: transparent; border: none; border-right: 1px solid %(border)s; }
QFrame#setupSection { background: transparent; border: none; border-bottom: 1px solid %(border)s; }
QWidget#setupDetails { background: transparent; }
QFrame#libraryBrowser, QFrame#libraryReview { background: %(panel)s; border: 1px solid %(border)s; border-radius: 8px; }
QWidget#libraryStage, QLabel#libraryPoster, QLabel#libraryPlaceholder { background: %(canvas)s; color: %(muted)s; border-radius: 8px; }
QLabel#librarySelectedTitle { font-family: 'Inter'; font-size: 18px; font-weight: 500; }
QLabel#libraryMetadata, QLabel#libraryMessage, QLabel#libraryCount { color: %(muted)s; font-size: 13px; }
QListWidget#recordingFiles { background: %(panel)s; border: none; qproperty-iconSize: 112px 64px; }
QListWidget#recordingFiles::item { min-height: 76px; padding: 8px; margin: 0 0 2px 0; }
QSplitter#librarySplitter::handle { background: transparent; }
QDialog#audioCheck { background: %(panel)s; border: 1px solid %(border)s; border-radius: 10px; }
QLabel#checkTitle { font-family: 'Inter'; font-size: 18px; font-weight: 700; }
QLabel#checkStatus { font-size: 13px; color: %(muted)s; }
QLabel#summaryValue { font-size: 14px; color: %(text)s; }
QPushButton, QToolButton { background: %(panel)s; border: 1px solid %(control_border)s; min-height: 22px; padding: 6px 10px; border-radius: 6px; font-weight: 600; }
QPushButton:hover, QToolButton:hover { background: %(hover)s; border-color: %(action)s; }
QPushButton:checked, QToolButton:checked { background: %(selection)s; border: 1px solid %(action)s; color: %(action)s; font-weight: 700; }
QPushButton#mode, QPushButton[mode="true"] { min-height: 28px; }
QPushButton:pressed, QToolButton:pressed { background: %(selection)s; }
QPushButton#record, QPushButton#playRecording, QPushButton#primary { background: %(action)s; color: %(on_action)s; border-color: %(action)s; }
QPushButton#record { min-height: 28px; font-size: 15px; }
QPushButton#record:hover, QPushButton#playRecording:hover, QPushButton#primary:hover { background: %(action_hover)s; }
QPushButton#record[stopping="true"] { background: %(error_bg)s; color: %(error)s; border-color: %(error)s; }
QPushButton#deleteRecording { color: %(error)s; }
QPushButton#deleteRecording:hover { background: %(error_bg)s; border-color: %(error)s; }
QPushButton#quiet { background: transparent; border-color: transparent; color: %(muted)s; padding: 5px; }
QPushButton#setupHeading { text-align: left; background: transparent; color: %(text)s; border: 1px solid transparent; padding: 6px; font-size: 14px; }
QPushButton#setupHeading:hover, QPushButton#setupHeading:checked { background: %(selection)s; }
QPushButton#footerNavigation { padding: 6px 8px; font-size: 13px; }
QComboBox, QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox { background: %(panel)s; color: %(text)s; border: 1px solid %(control_border)s; border-radius: 6px; min-height: 22px; padding: 6px 8px; selection-background-color: %(selection)s; selection-color: %(text)s; }
QLineEdit { placeholder-text-color: %(muted)s; }
QComboBox { padding-right: 30px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 28px; border: none; background: transparent; }
QComboBox::down-arrow { image: url("%(chevron)s"); width: 12px; height: 12px; }
QComboBox QAbstractItemView::item { min-height: 30px; padding: 3px 8px; }
QComboBox QAbstractItemView { background: %(panel)s; color: %(text)s; border: 1px solid %(border)s; selection-background-color: %(selection)s; selection-color: %(text)s; }
QAbstractItemView { background: %(panel)s; alternate-background-color: %(canvas)s; color: %(text)s; border: 1px solid %(border)s; border-radius: 8px; selection-background-color: %(selection)s; selection-color: %(text)s; }
QListWidget { background: %(canvas)s; border: none; }
QListWidget::item { background: %(panel)s; border: 1px solid %(border)s; border-radius: 8px; margin: 0 4px 7px 0; padding: 10px; }
QListWidget::item:hover { background: %(hover)s; }
QListWidget::item:selected { background: %(selection)s; color: %(text)s; border-color: %(action)s; }
QCheckBox, QRadioButton { spacing: 8px; min-height: 36px; background: transparent; border: 1px solid transparent; border-radius: 3px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; border: 1px solid %(control_border)s; border-radius: 3px; background: %(panel)s; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:checked { background: %(action)s; border-color: %(action)s; image: url("%(check)s"); }
QRadioButton::indicator:checked { background: %(action)s; border-color: %(action)s; image: url("%(radio)s"); }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { background-color: %(disabled_bg)s; border-color: %(disabled)s; }
QCheckBox::indicator:checked:disabled, QRadioButton::indicator:checked:disabled { background-color: %(disabled)s; }
QSlider { border: 1px solid transparent; border-radius: 3px; }
QSlider::groove:horizontal { height: 4px; background: %(border)s; border-radius: 2px; }
QSlider::sub-page:horizontal { background: %(action)s; border-radius: 2px; }
QSlider::handle:horizontal { background: %(action)s; border: 1px solid %(panel)s; width: 14px; margin: -6px 0; border-radius: 7px; }
QSlider::groove:vertical { width: 4px; background: %(border)s; }
QSlider::handle:vertical { background: %(action)s; height: 14px; margin: 0 -6px; border-radius: 7px; }
QProgressBar { background: %(meter_track)s; color: %(text)s; border: 1px solid %(border)s; border-radius: 3px; text-align: center; }
QProgressBar::chunk { background: %(selection)s; border-radius: 2px; }
QMenu, QMenuBar { background: %(panel)s; color: %(text)s; border: 1px solid %(border)s; padding: 4px; }
QMenu::item { padding: 7px 16px; }
QMenu::item:selected, QMenuBar::item:selected { background: %(selection)s; color: %(text)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 4px; }
QToolTip { background: %(panel)s; color: %(text)s; border: 1px solid %(border)s; padding: 6px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 0; }
QScrollBar::handle { background: %(border)s; border-radius: 4px; min-height: 24px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSplitter::handle { background: %(border)s; }
QGroupBox { border: 1px solid %(border)s; border-radius: 8px; margin-top: 12px; padding-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; color: %(muted)s; }
QTabWidget::pane { border: 1px solid %(border)s; background: %(panel)s; }
QTabBar::tab { background: %(canvas)s; padding: 7px 12px; }
QTabBar::tab:selected { background: %(selection)s; }
QLabel#warning, QLabel[status="warning"] { color: %(warning)s; background: %(warning_bg)s; padding: 6px; border-radius: 5px; }
QLabel#error, QLabel[status="error"] { color: %(error)s; background: %(error_bg)s; padding: 6px; border-radius: 5px; }
QLabel#success, QLabel[status="success"] { color: %(success)s; }
QLabel#recording, QLabel[status="recording"] { color: %(recording)s; }
/* Suppress native dotted focus rectangles; the solid cues below replace them.
   Outline on item views preserves the geometry of borderless library lists. */
QPushButton, QToolButton, QComboBox, QCheckBox, QRadioButton, QSlider, QAbstractItemView, QAbstractItemView::item { outline: none; }
QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QAbstractSpinBox:focus { border: 1px solid %(focus)s; }
QListWidget::item:focus { border: 1px solid %(focus)s; }
QPushButton#record:focus, QPushButton#playRecording:focus, QPushButton#primary:focus { border: 1px solid %(on_action)s; }
QCheckBox:focus, QRadioButton:focus, QSlider:focus { border: 1px solid %(focus)s; background: %(selection)s; }
QAbstractItemView:focus { border-color: %(focus)s; outline: 1px solid %(focus)s; }
QPushButton#quiet:focus, QPushButton#setupHeading:focus { border-color: %(focus)s; }
QPushButton#record[stopping="true"]:focus { border-color: %(focus)s; }
QWidget:disabled { color: %(disabled)s; }
QPushButton:disabled, QPushButton#record:disabled, QPushButton#playRecording:disabled, QPushButton#primary:disabled, QToolButton:disabled, QComboBox:disabled, QLineEdit:disabled { background: %(disabled_bg)s; color: %(disabled)s; border-color: %(border)s; }
QSlider::handle:disabled, QSlider::sub-page:disabled, QProgressBar::chunk:disabled { background: %(disabled)s; }
""" % c


def apply_theme(application, name='light'):
    """Apply a theme on the Qt UI thread, including already-created meters."""
    name = name if name in THEMES else 'light'
    style = stylesheet(name)
    # Qt repolishes every existing widget here, including closed windows. New
    # widgets inherit this stylesheet; meters read the active tokens on creation.
    if application.property('untangleTheme') == name and application.styleSheet() == style:
        return
    c = tokens(name)
    load_fonts(application)
    application.setProperty('untangleTheme', name)
    palette = QPalette()
    roles = {
        'Window': 'canvas', 'WindowText': 'text', 'Base': 'panel',
        'AlternateBase': 'canvas', 'Text': 'text', 'Button': 'panel',
        'ButtonText': 'text', 'Highlight': 'selection', 'HighlightedText': 'text',
        'ToolTipBase': 'panel', 'ToolTipText': 'text', 'PlaceholderText': 'muted',
        'Link': 'action', 'LinkVisited': 'action', 'Light': 'panel',
        'Midlight': 'hover', 'Mid': 'border', 'Dark': 'muted', 'Shadow': 'text',
    }
    for role, token in roles.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(c[token]))
    for role in ('WindowText', 'Text', 'ButtonText', 'PlaceholderText'):
        palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role),
                         QColor(c['disabled']))
    application.setPalette(palette)
    application.setStyleSheet(style)
