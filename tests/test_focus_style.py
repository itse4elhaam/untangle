"""Clearline focus cues on isolated, offscreen Qt widgets. No app or devices."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit,
    QListWidget, QPlainTextEdit, QPushButton, QRadioButton, QSlider,
    QSpinBox, QTableWidget, QTextEdit, QToolButton, QTreeWidget,
    QVBoxLayout, QWidget,
)
from untangle.theme import apply_theme, stylesheet, tokens


class FocusStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        palette, font = self.qt.palette(), self.qt.font()
        style, theme = self.qt.styleSheet(), self.qt.property('untangleTheme')

        def restore_theme():
            self.qt.setPalette(palette)
            self.qt.setFont(font)
            self.qt.setStyleSheet(style)
            self.qt.setProperty('untangleTheme', theme)

        self.addCleanup(restore_theme)

    def test_focus_palette_contrast_and_no_patterned_borders(self):
        def luminance(color):
            channels = QColor(color).getRgbF()[:3]
            linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
                      for v in channels]
            return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))

        for theme in ('light', 'dark'):
            c = tokens(theme)
            self.assertNotRegex(stylesheet(theme), r'\b(?:dashed|dotted)\s+[#%]')
            for foreground, background in (
                ('focus', 'panel'), ('focus', 'canvas'), ('focus', 'selection'),
                ('focus', 'error_bg'), ('on_action', 'action'),
                ('on_action', 'action_hover'),
            ):
                with self.subTest(theme=theme, colors=(foreground, background)):
                    values = sorted((luminance(c[foreground]), luminance(c[background])))
                    self.assertGreaterEqual((values[1] + .05) / (values[0] + .05), 3)

    def test_keyboard_focus_is_solid_and_does_not_resize_controls(self):
        for theme in ('light', 'dark'):
            apply_theme(self.qt, theme)
            c = tokens(theme)
            host = QWidget()
            layout = QVBoxLayout(host)
            anchor = QPushButton('Before')
            layout.addWidget(anchor)
            controls = [QPushButton('Expand camera'), QToolButton(), QComboBox(),
                        QLineEdit(), QTextEdit(), QPlainTextEdit(), QSpinBox(),
                        QDoubleSpinBox(), QCheckBox('Enabled'), QRadioButton('Mode'),
                        QSlider(Qt.Horizontal), QListWidget(), QTreeWidget(), QTableWidget()]
            controls[2].addItem('Canvas')
            controls[11].addItem('Synthetic recording')
            for name in ('record', 'playRecording', 'primary', 'quiet', 'setupHeading'):
                button = QPushButton(name)
                button.setObjectName(name)
                controls.append(button)
            recordings = QListWidget()
            recordings.setObjectName('recordingFiles')
            recordings.addItem('Synthetic recording')
            controls.append(recordings)
            stopping = QPushButton('Saving')
            stopping.setObjectName('record')
            stopping.setProperty('stopping', True)
            controls.append(stopping)
            for widget in controls:
                layout.addWidget(widget)
            host.resize(360, 1800)
            host.show()
            host.activateWindow()
            self.qt.processEvents()
            try:
                for widget in controls:
                    with self.subTest(theme=theme, widget=type(widget).__name__,
                                      name=widget.objectName()):
                        anchor.setFocus()
                        self.qt.processEvents()
                        before = (widget.sizeHint(), widget.minimumSizeHint(),
                                  widget.geometry(), widget.contentsRect())
                        QWidget.setTabOrder(anchor, widget)
                        QTest.keyClick(anchor, Qt.Key_Tab)
                        self.qt.processEvents()
                        self.assertTrue(widget.hasFocus())
                        self.assertEqual(before, (widget.sizeHint(), widget.minimumSizeHint(),
                                                  widget.geometry(), widget.contentsRect()))
                        image = widget.grab().toImage()
                        token = 'on_action' if widget.objectName() in (
                            'record', 'playRecording', 'primary') and widget is not stopping else 'focus'
                        expected = QColor(c[token])
                        # Straight center section must be uninterrupted, unlike a dashed ring.
                        x = image.width() // 2
                        self.assertTrue(any(all(image.pixelColor(px, y) == expected
                                                for px in range(x - 8, x + 8))
                                            for y in range(3)))
                for view in (controls[11], recordings):
                    with self.subTest(theme=theme, item_view=view.objectName()):
                        view.setCurrentRow(0)
                        view.setFocus(Qt.TabFocusReason)
                        self.qt.processEvents()
                        rect = view.visualItemRect(view.item(0))
                        image = view.viewport().grab().toImage()
                        x = rect.center().x()
                        # One view-level focus cue; selected rows use a quiet fill,
                        # without a second rectangle around their text.
                        self.assertTrue(all(image.pixelColor(px, rect.top() + 2) == QColor(c['selection'])
                                            for px in range(x - 8, x + 8)))
                for widget in (controls[0], controls[8], controls[10]):
                    anchor.setFocus()
                    QTest.mouseClick(widget, Qt.LeftButton)
                    self.qt.processEvents()
                    self.assertTrue(widget.hasFocus())
            finally:
                host.close()
                host.deleteLater()
                self.qt.processEvents()
