"""Per-setup crop preferences and a device-free drag control."""
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


from .composition import bounded_offset


def load_framing(prefs, mode):
    """Seed both setups from legacy zoom, without overwriting newer choices."""
    def zoom(value):
        try:
            number = float(value)
            return max(100, min(300, round(number))) if math.isfinite(number) else 100
        except (TypeError, ValueError, OverflowError):
            return 100
    legacy = zoom(prefs.value('camera_zoom', 100))
    for setup in ('screen', 'camera'):
        key = 'camera_zoom_' + setup
        if not prefs.contains(key):
            prefs.setValue(key, legacy)
    try:
        offset = bounded_offset(prefs.value('camera_offset_' + mode, [0., 0.]))
    except ValueError:
        offset = (0., 0.)
    return zoom(prefs.value('camera_zoom_' + mode, legacy)), offset


class CropPosition(QWidget):
    """A drag pad representing the fixed crop; live results use the recorder preview."""
    changed = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.offset = (0., 0.)
        self._drag = None
        self.setFixedHeight(100)
        self.setMinimumWidth(160)
        self.setCursor(Qt.OpenHandCursor)
        self.setAccessibleName('Drag camera image within crop')
        self.setToolTip('Drag to move the image. Watch the recorder preview. Zoom in if an axis has no crop space.')

    def set_offset(self, x, y):
        self.offset = bounded_offset((x, y))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = (event.position(), self.offset)
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()

    def hideEvent(self, event):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)
        super().hideEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None and not event.buttons() & Qt.LeftButton:
            self._drag = None
            self.setCursor(Qt.OpenHandCursor)
        if self._drag is not None:
            start, offset = self._drag
            delta = event.position() - start
            x, y = bounded_offset((offset[0] + delta.x() * 4 / self.width(),
                                    offset[1] + delta.y() * 4 / self.height()))
            self.changed.emit(x, y)

    def mouseReleaseEvent(self, event):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        bounds = self.rect().adjusted(4, 4, -5, -5)
        painter.fillRect(bounds, QColor('#20262d'))
        painter.setClipRect(bounds)
        # The larger image outline moves behind a fixed crop boundary.
        image = bounds.adjusted(-bounds.width() // 4, -bounds.height() // 4,
                                 bounds.width() // 4, bounds.height() // 4)
        image.translate(round(self.offset[0] * bounds.width() / 4),
                        round(self.offset[1] * bounds.height() / 4))
        painter.setPen(QPen(QColor('#8294aa'), 2))
        painter.drawRect(image)
        painter.drawLine(image.center().x(), image.top(), image.center().x(), image.bottom())
        painter.drawLine(image.left(), image.center().y(), image.right(), image.center().y())
        painter.setClipping(False)
        painter.setPen(QPen(QColor('#69c8bd'), 2))
        painter.drawRect(bounds)
