"""Rank advertised colour camera modes without opening capture streams."""
import re

COLOUR_FORMATS = frozenset(('MJPG', 'YUYV', 'NV12', 'RGB3', 'H264'))


def camera_quality(formats):
    """Prefer resolution usable at 30 fps, then frame rate for equal resolutions.

    If no mode reaches 30 fps, prefer the largest advertised colour mode.
    Unknown capabilities tie last; discovery order breaks otherwise equal ties.
    """
    modes = []
    colour = False
    area = 0
    for line in formats.splitlines():
        match = re.search(r"\[\d+\]: '(.{4})'", line)
        if match:
            colour = match[1] in COLOUR_FORMATS
            area = 0
            continue
        if not colour:
            continue
        size = re.search(r'Size: Discrete (\d+)x(\d+)', line)
        if size:
            area = int(size[1]) * int(size[2])
            modes.append((0, area, 0.0))
        rate = re.search(r'\(([\d.]+) fps\)', line)
        if rate and area:
            fps = float(rate[1])
            modes.append((int(fps >= 29.9), area, fps))
    return max(modes, default=(0, 0, 0.0))
