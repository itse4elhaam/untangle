"""Native camera window and the small state machine for pointer-follow zoom."""
from __future__ import annotations

import math
from pathlib import Path
import re
import time

from PySide6.QtCore import QEvent, Qt, Signal, QRect, QRectF, QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget, QMenu, QApplication
from .diagnostics import event as diagnostic_event, failure as diagnostic_failure


def release_window_input(widget):
    """Release this Qt client's native pointer grab before hiding a window.

    Qt's QWidget grabber bookkeeping and the XCB native grab are separate.
    A bounded ShapeInput region does not constrain an active pointer grab.
    Use Qt's own connection, not a fresh python-xlib connection, so the ungrab
    belongs to the client that can own the grab. Other applications' grabs
    are unaffected by this request.
    """
    popup = QApplication.activePopupWidget()
    if popup is not None:
        popup.close()
    grabber = QWidget.mouseGrabber()
    if grabber is not None:
        grabber.releaseMouse()
    handle = widget.windowHandle()
    if handle is not None:
        handle.setMouseGrabEnabled(False)


def camera_mask(shape, width, height, custom=None, mirror=False):
    """An alpha image, never a one-bit window region, in physical pixels."""
    if shape == 'custom':
        image = custom.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return image.flipped(Qt.Horizontal) if mirror else image
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(Qt.white)
    rect = QRectF(0, 0, width, height)
    if shape == 'circle':
        painter.drawEllipse(rect)
    elif shape == 'rounded':
        radius = min(width, height) * .16
        painter.drawRoundedRect(rect, radius, radius)
    else:
        painter.drawRect(rect)
    painter.end()
    return image


def camera_input_rectangles(image):
    """Only X11 input is binary; include every pixel with nonzero coverage."""
    alpha = image.convertToFormat(QImage.Format_Alpha8)
    pixels, stride = alpha.constBits(), alpha.bytesPerLine()
    rectangles = []
    for y in range(alpha.height()):
        row = pixels[y * stride:y * stride + alpha.width()]
        rectangles.extend((run.start(), y, run.end() - run.start(), 1)
                          for run in re.finditer(rb'[^\x00]+', row))
    return rectangles


class ZoomMotion:
    """Elapsed-time smoothing keeps zoom speed independent of the timer rate."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.factor = 1.0
        self.x = self.y = .5
        self.enabled = False
        self.last_time = time.monotonic()

    def step(self, target_factor, x, y, now=None):
        now = time.monotonic() if now is None else now
        dt = min(.1, max(0.0, now - self.last_time))
        self.last_time = now
        target = min(3.0, max(1.0, target_factor)) if self.enabled else 1.0
        alpha = 1.0 - math.exp(-dt / .12)
        if self.enabled and self.factor == 1.0:
            self.x, self.y = x, y
        self.factor += (target - self.factor) * alpha
        # Start the first zoom at the pointer, avoiding a distracting pan from centre.
        if self.factor < 1.02:
            self.x, self.y = x, y
        else:
            self.x += (x - self.x) * alpha
            self.y += (y - self.y) * alpha
        if abs(target - self.factor) < .002:
            self.factor = target
        self.x, self.y = min(1., max(0., self.x)), min(1., max(0., self.y))
        return self.factor, self.x, self.y


class CameraBubble(QWidget):
    presentation_requested = Signal()
    stop_requested = Signal()
    pause_requested = Signal()
    zoom_requested = Signal()
    open_requested = Signal()
    resized = Signal(float)
    moved = Signal()
    pixel_size_changed = Signal(int, int)

    def __init__(self):
        # An X11 overlay has no WM frame or task-switcher entry. Qt.Popup
        # would grab desktop input; a managed Tool can acquire a WM frame.
        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        if QApplication.platformName() == 'xcb':
            flags |= Qt.X11BypassWindowManagerHint
        super().__init__(None, flags)
        self.setWindowTitle('Untangle · Camera widget')
        # OBS's native swapchain and QRegion both discard fractional alpha.
        # Qt must own this translucent window's backing store and final pixels.
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NativeWindow)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.OpenHandCursor)
        self.setMouseTracking(True)
        self.setToolTip('Drag boundary to resize · Drag inside to move · Right-click for recording controls\nCtrl + Shift + F8 toggles pointer zoom')
        self._drag_offset = None
        self._resize_start = None
        self.resize_enabled = True
        self.size_limits = (.12, .42)
        self._bounds = None
        self.setFocusPolicy(Qt.NoFocus)
        self._screen = None
        self._placement_key = None
        self._drag_position = None
        self.recording = False
        self.paused = False
        self.zoomed = False
        self._shape = 'square'
        self._input_passthrough = False
        self._custom_mask = None
        self._mirror_mask = False
        self._alpha_mask = None
        self._frame = QImage()
        self._frame_masked = False
        self._frame_provider = None
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(33)
        self._frame_timer.timeout.connect(self._pull_frame)

    def set_frame_provider(self, provider, *, masked=False):
        """Called on Qt's thread; provider returns at most one copied frame."""
        self._frame_timer.stop()
        self._frame_provider = provider
        self._frame_masked = masked
        self._frame = QImage()
        if provider is not None:
            self._frame_timer.start()
        self.update()

    def _pull_frame(self):
        if self._frame_provider is not None and self.isVisible():
            image = self._frame_provider()
            if image is not None:
                self.set_frame(image)

    def set_frame(self, image):
        self._frame = image
        self.update()

    def frame_image(self, ratio=None):
        """Compose at the actual device scale, also used by synthetic checks."""
        ratio = self.devicePixelRatioF() if ratio is None else ratio
        width, height = max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio))
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        if not self._frame.isNull():
            painter = QPainter(image)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage(QRectF(0, 0, width, height), self._frame)
            # A composited OBS source already contains its mask. Applying it
            # twice would square edge alpha and darken translucent custom masks.
            if not self._frame_masked:
                if self._alpha_mask is None or self._alpha_mask.size() != image.size():
                    self._alpha_mask = camera_mask(self._shape, width, height,
                                                   self._custom_mask, self._mirror_mask)
                painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
                painter.drawImage(0, 0, self._alpha_mask)
            painter.end()
        image.setDevicePixelRatio(ratio)
        return image

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.drawImage(QRectF(self.rect()), self.frame_image())
        painter.end()

    def hideEvent(self, event):
        self._resize_start = None
        self._drag_offset = None
        self.setCursor(Qt.OpenHandCursor)
        release_window_input(self)
        if QApplication.platformName() == 'xcb':
            self._update_input_shape(empty=True)
        super().hideEvent(event)

    def closeEvent(self, event):
        self.set_frame_provider(None)
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if QApplication.platformName() == 'xcb':
            self._update_input_shape()
            QTimer.singleShot(0, self.pin_to_workspaces)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._size_changed()

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.DevicePixelRatioChange:
            self._size_changed()
        return result

    def _size_changed(self):
        ratio = self.devicePixelRatioF()
        self.pixel_size_changed.emit(round(self.width() * ratio), round(self.height() * ratio))
        if self.isVisible() and QApplication.platformName() == 'xcb':
            self._update_input_shape()

    def _update_input_shape(self, *, empty=False):
        from Xlib import X, display, error
        from Xlib.ext import shape
        ratio = self.devicePixelRatioF()
        rectangles = []
        if not empty and not self._input_passthrough:
            mask = camera_mask(self._shape, max(1, round(self.width() * ratio)),
                               max(1, round(self.height() * ratio)), self._custom_mask, self._mirror_mask)
            rectangles = camera_input_rectangles(mask)
        connection = None
        try:
            connection = display.Display()
            window = connection.create_resource_object('window', int(self.winId()))
            catcher = error.CatchError()
            # ShapeInput leaves the compositor's fractional visual alpha intact.
            for start in range(0, max(1, len(rectangles)), 1024):
                # python-xlib's Window.shape_rectangles wrapper does not
                # accept onerror. The protocol request does, and lets us
                # detect asynchronous failures before trusting the region.
                shape.Rectangles(display=window.display, onerror=catcher,
                    opcode=window.display.get_extension_major(shape.extname),
                    destination_window=window, destination_kind=shape.SK.Input,
                    operation=shape.SO.Set if start == 0 else shape.SO.Union,
                    ordering=X.YXBanded, x_offset=0, y_offset=0,
                    rectangles=rectangles[start:start + 1024])
            connection.sync()
            problem = catcher.get_error()
            if problem:
                raise problem
            diagnostic_event('camera.input_shape.applied', input_rectangles=len(rectangles),
                             visible=self.isVisible(), window_id=int(self.winId()),
                             outcome='click_through' if self._input_passthrough or empty else 'bounded')
        except Exception as exc:
            diagnostic_failure('camera.input_shape.failed', exc)
            # A failed native mask must not leave an opaque input window.
            # Tray controls remain usable when this window passes clicks through.
            self._input_passthrough = True
            handle = self.windowHandle()
            if handle is not None:
                handle.setFlag(Qt.WindowTransparentForInput, True)
        finally:
            if connection is not None:
                connection.close()

    def pin_to_workspaces(self):
        if not self.isVisible():
            return
        # EWMH's all-desktops value keeps the camera visible when changing workspaces.
        from Xlib import X, Xatom, display, protocol
        connection = display.Display()
        try:
            window = connection.create_resource_object('window', int(self.winId()))
            desktop_atom = connection.intern_atom('_NET_WM_DESKTOP')
            window.change_property(connection.intern_atom('_NET_WM_BYPASS_COMPOSITOR'),
                                   Xatom.CARDINAL, 32, [2])
            window.change_property(desktop_atom, Xatom.CARDINAL, 32, [0xFFFFFFFF])
            connection.screen().root.send_event(protocol.event.ClientMessage(
                window=window, client_type=desktop_atom, data=(32, [0xFFFFFFFF, 2, 0, 0, 0])),
                event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
            connection.flush()
        finally:
            connection.close()
        self._update_input_shape()

    def arrange(self, screen, fraction, position, shape, mask_path=None, mirror_mask=False, bounds=None):
        key = screen, position, bounds
        if key != self._placement_key:
            self._drag_position = None
        self._placement_key = key
        self._screen = screen
        self._bounds = QRect(bounds) if bounds is not None else None
        full = screen.availableGeometry()
        bounds = self._placement_bounds()
        if bounds.isEmpty():
            raise ValueError('Camera placement bounds are empty')
        side = round(min(full.width(), full.height()) * fraction)
        minimum, maximum = self._side_limits()
        side = max(minimum, min(side, maximum))
        self.setFixedSize(side, side)
        margin = 20
        x = bounds.left() + margin if 'left' in position else bounds.right() - side - margin + 1
        y = bounds.top() + margin if 'top' in position else bounds.bottom() - side - margin + 1
        if self._drag_position is not None:
            x = bounds.left() + round(self._drag_position[0] * (bounds.width() - side))
            y = bounds.top() + round(self._drag_position[1] * (bounds.height() - side))
        x = max(bounds.left(), min(bounds.right() - side + 1, x))
        y = max(bounds.top(), min(bounds.bottom() - side + 1, y))
        self.move(x, y)
        self.apply_shape(shape, mask_path, mirror_mask)

    def apply_shape(self, shape, mask_path=None, mirror_mask=False):
        custom = None
        if shape == 'custom':
            custom = QImage(str(Path(mask_path).expanduser()) if mask_path else '')
            if custom.isNull():
                raise ValueError('The custom camera shape image cannot be opened.')
            alpha = custom.convertToFormat(QImage.Format_Alpha8)
            pixels, stride = alpha.constBits(), alpha.bytesPerLine()
            if not any(any(pixels[y * stride:y * stride + alpha.width()]) for y in range(alpha.height())):
                raise ValueError('The custom camera shape is completely transparent.')
        self._shape, self._custom_mask, self._mirror_mask = shape, custom, mirror_mask
        self._alpha_mask = None
        self.clearMask()
        self.update()
        if self.isVisible() and QApplication.platformName() == 'xcb':
            self._update_input_shape()

    def _placement_bounds(self):
        return QRect(self._bounds) if self._bounds is not None else self._screen.availableGeometry()

    def _side_limits(self):
        bounds = self._screen.availableGeometry()
        short = min(bounds.width(), bounds.height())
        maximum = max(1, round(short * self.size_limits[1]))
        placement = self._placement_bounds()
        maximum = min(maximum, placement.width(), placement.height())
        return min(maximum, max(100, round(short * self.size_limits[0]))), maximum

    def _resize_direction(self, point):
        if not self.resize_enabled or self.recording or self._screen is None:
            return None
        # Hit-test the visible silhouette, including curved and custom edges.
        mask = camera_mask(self._shape, self.width(), self.height(),
                           self._custom_mask, self._mirror_mask)
        x, y = point.x(), point.y()
        def covered(px, py):
            return (0 <= px < mask.width() and 0 <= py < mask.height()
                    and mask.pixelColor(px, py).alpha() > 0)
        if not covered(x, y) or all(covered(x + dx, y + dy)
                for dx, dy in ((-8, 0), (8, 0), (0, -8), (0, 8))):
            return None
        nx, ny = 2 * x / self.width() - 1, 2 * y / self.height() - 1
        direction = (0 if abs(nx) < .45 else (1 if nx > 0 else -1),
                0 if abs(ny) < .45 else (1 if ny > 0 else -1))
        return direction if any(direction) else None

    def _resize_cursor(self, direction):
        if not direction:
            return Qt.OpenHandCursor
        x, y = direction
        return (Qt.SizeVerCursor if not x else Qt.SizeHorCursor if not y
                else Qt.SizeFDiagCursor if x == y else Qt.SizeBDiagCursor)

    def _remember_position(self):
        if self._screen is not None:
            bounds = self._placement_bounds()
            self._drag_position = (
                min(1., max(0., (self.x() - bounds.left()) / max(1, bounds.width() - self.width()))),
                min(1., max(0., (self.y() - bounds.top()) / max(1, bounds.height() - self.height()))))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            direction = self._resize_direction(event.position().toPoint())
            if direction:
                self._resize_start = (event.globalPosition().toPoint(), self.geometry(), direction)
                self.setCursor(self._resize_cursor(direction))
            else:
                self._drag_offset = event.globalPosition().toPoint() - self.pos()
                self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Lost releases and a recording transition must end a resize immediately.
        if self._resize_start is not None and (
                not event.buttons() & Qt.LeftButton or not self.resize_enabled or self.recording):
            self._resize_start = None
            self.setCursor(Qt.OpenHandCursor)
            if QWidget.mouseGrabber() is self:
                self.releaseMouse()
        if self._resize_start is not None:
            start, rect, (sx, sy) = self._resize_start
            delta = event.globalPosition().toPoint() - start
            change = (delta.x() * sx + delta.y() * sy) / (abs(sx) + abs(sy))
            minimum, maximum = self._side_limits()
            side = max(minimum, min(maximum, round(rect.width() + change)))
            bounds = self._placement_bounds()
            # Keep the opposite edge/corner fixed, centering the unused axis.
            x = rect.x() + round((rect.width() - side) * (1 - sx) / 2)
            y = rect.y() + round((rect.height() - side) * (1 - sy) / 2)
            x = max(bounds.left(), min(bounds.right() - side + 1, x))
            y = max(bounds.top(), min(bounds.bottom() - side + 1, y))
            self.setFixedSize(side, side)
            self.move(x, y)
            self._remember_position()
            self.resized.emit(side / min(self._screen.availableGeometry().width(),
                                         self._screen.availableGeometry().height()))
            event.accept()
            return
        # A release can be lost when a menu or another window takes the grab.
        if self._drag_offset is not None and not event.buttons() & Qt.LeftButton:
            self._drag_offset = None
            self.setCursor(Qt.OpenHandCursor)
            if QWidget.mouseGrabber() is self:
                self.releaseMouse()
        if self._drag_offset is not None:
            point = event.globalPosition().toPoint() - self._drag_offset
            if self._screen:
                bounds = self._placement_bounds()
                point.setX(max(bounds.left(), min(bounds.right() - self.width() + 1, point.x())))
                point.setY(max(bounds.top(), min(bounds.bottom() - self.height() + 1, point.y())))
            self.move(point)
            event.accept()
        else:
            self.setCursor(self._resize_cursor(self._resize_direction(event.position().toPoint())))
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._remember_position()
            self._resize_start = None
            self._drag_offset = None
            self.setCursor(Qt.OpenHandCursor)
            self.moved.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction('Open Untangle', self.open_requested.emit)
        if self.recording:
            menu.addAction('Switch camera presentation', self.presentation_requested.emit)
            menu.addAction('Stop and save · Ctrl+Shift+F9', self.stop_requested.emit)
            menu.addAction('Resume' if self.paused else 'Pause', self.pause_requested.emit)
        action = menu.addAction('Zoom out' if self.zoomed else 'Zoom to pointer · Ctrl+Shift+F8', self.zoom_requested.emit)
        action.setEnabled(self.recording)
        menu.exec(event.globalPos())
