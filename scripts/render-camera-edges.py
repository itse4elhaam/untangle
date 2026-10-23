#!/usr/bin/env python3
"""Render production camera alpha with synthetic pixels, without opening the app.

Run with .venv/bin/python scripts/render-camera-edges.py --output /tmp/camera-edges.png
No libobs startup, display server, camera, microphone, or playback is used.
"""
import argparse
import os
from pathlib import Path
import sys
import tempfile

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ.pop('DISPLAY', None)
os.environ.pop('WAYLAND_DISPLAY', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication
from untangle.floating import CameraBubble


def synthetic_camera():
    image = QImage(640, 640, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor('#ede6da'))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    for x in range(0, 640, 40):
        painter.fillRect(x, 0, 20, 640, QColor('#e4dccd'))
    painter.setBrush(QColor('#3c4647'))
    painter.drawRoundedRect(QRectF(80, 195, 480, 460), 60, 60)
    painter.setBrush(QColor('#c7845d'))
    painter.drawEllipse(QRectF(205, 160, 230, 290))
    painter.setBrush(QColor('#282a2e'))
    painter.drawEllipse(QRectF(190, 130, 260, 140))
    gradient = QLinearGradient(0, 430, 640, 640)
    gradient.setColorAt(0, QColor('#426d7a'))
    gradient.setColorAt(1, QColor('#153b47'))
    painter.setBrush(gradient)
    painter.drawEllipse(QRectF(85, 425, 470, 460))
    painter.end()
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/untangle-camera-edges.png'))
    args = parser.parse_args()
    qt = QApplication.instance() or QApplication([])
    sheet = QImage(1140, 930, QImage.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#11161b'))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.setPen(QColor('#f6f3ed'))
    painter.setFont(QFont('Sans Serif', 22))
    painter.drawText(30, 42, 'Camera edges · synthetic pixels')
    painter.setFont(QFont('Sans Serif', 11))
    painter.setPen(QColor('#acb7bf'))
    painter.drawText(30, 68, 'Production alpha compositor · 1× / 1.25× / 2× device scale · enlarged edge details')
    source = synthetic_camera()
    with tempfile.TemporaryDirectory(prefix='untangle-camera-fixture-') as folder:
        mask = QImage(640, 640, QImage.Format_ARGB32_Premultiplied)
        mask.fill(Qt.transparent)
        mask_painter = QPainter(mask)
        mask_painter.setRenderHint(QPainter.Antialiasing)
        mask_painter.setPen(Qt.NoPen)
        path = QPainterPath()
        path.moveTo(20, 140)
        path.cubicTo(110, -60, 560, 10, 620, 190)
        path.cubicTo(700, 560, 430, 700, 150, 590)
        path.cubicTo(-30, 520, 50, 340, 20, 140)
        mask_painter.setBrush(Qt.white)
        mask_painter.drawPath(path)
        mask_painter.end()
        mask_path = Path(folder) / 'custom.png'
        mask.save(str(mask_path))
        for row, background in enumerate(('#1e272e', '#f4efe6')):
            for column, (shape, ratio) in enumerate((('rounded', 1), ('circle', 1.25), ('custom', 2))):
                x, y = 30 + column * 370, 95 + row * 410
                painter.fillRect(x, y, 340, 380, QColor(background))
                bubble = CameraBubble()
                bubble.resize(260, 260)
                bubble.apply_shape(shape, str(mask_path) if shape == 'custom' else None)
                bubble.set_frame(source)
                frame = bubble.frame_image(ratio)
                painter.drawImage(QRectF(x + 40, y + 20, 260, 260), frame)
                # Keep physical pixels for the detail instead of resampling by DPR.
                frame.setDevicePixelRatio(1)
                crop = frame.copy(0, 0, round(60 * ratio), round(60 * ratio))
                painter.drawImage(QRectF(x + 22, y + 290, 70, 70), crop)
                painter.setPen(QColor('#a8b8c3') if row == 0 else QColor('#52616d'))
                painter.drawText(x + 110, y + 317, f'{shape.capitalize()} · {ratio:g}×')
                painter.drawText(x + 110, y + 342, 'Alpha edge detail at left')
                bubble.close()
    painter.end()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not sheet.save(str(args.output)):
        raise SystemExit('Could not save the synthetic camera render.')
    print(args.output.resolve())


if __name__ == '__main__':
    main()
