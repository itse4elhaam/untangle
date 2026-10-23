"""Canvas dimensions and source framing shared by recording and safe UI renders."""

import math


def canvas_dimensions(quality_tuple, preset="landscape"):
    """Keep the quality's short edge, with even dimensions for video encoding.

    1080p presets are 1920x1080, 1080x1920, 1080x1080 and 1080x1350.
    The existing 4K quality doubles both dimensions for every preset.
    """
    width, height = quality_tuple
    if any(type(value) is not int or value < 16 or value % 2
           for value in (width, height)) or width < height:
        raise ValueError("Quality must contain even landscape dimensions of at least 16.")
    if preset == "landscape":
        return width, height
    if preset == "portrait":
        return height, width
    if preset == "square":
        return height, height
    if preset == "portrait45":
        return height, round(height * 5 / 8) * 2
    raise ValueError(f"Unknown canvas preset: {preset}")


def camera_composition(width, height, source_width, source_height, *, mode='camera',
                       camera_zoom=1.0, framing='fit', size=.22, position='bottom-right'):
    """Return a centered source crop and uniform scene placement, without IO."""
    if not all(math.isfinite(value) and value > 0
               for value in (width, height, source_width, source_height, camera_zoom)):
        raise ValueError('Camera and canvas dimensions and zoom must be positive and finite.')
    if mode not in ('camera', 'screen') or framing not in ('fit', 'fill'):
        raise ValueError('Unknown camera mode or framing.')
    if not math.isfinite(size) or not .05 <= size <= 1:
        raise ValueError('Camera size must be 0.05–1.0.')
    if position not in ('top-left', 'top-right', 'bottom-left', 'bottom-right', 'center'):
        raise ValueError('Unknown camera position.')
    zoom = max(1.0, min(3.0, camera_zoom))
    crop_w, crop_h = source_width, source_height
    if mode == 'screen':
        crop_w = crop_h = min(source_width, source_height)
    elif framing == 'fill':
        aspect = width / height
        crop_w, crop_h = min(crop_w, crop_h * aspect), min(crop_h, crop_w / aspect)
    crop_w = max(1, min(source_width, round(crop_w / zoom)))
    crop_h = max(1, min(source_height, round(crop_h / zoom)))
    crop = ((source_width - crop_w) // 2, (source_height - crop_h) // 2, crop_w, crop_h)
    if mode == 'camera':
        scale_for = min if framing == 'fit' else max
        scale = scale_for(width / crop_w, height / crop_h)
        dw, dh = crop_w * scale, crop_h * scale
        return crop, ((width - dw) / 2, (height - dh) / 2, scale)
    side = round(min(width, height) * size)
    margin = round(min(width, height) * .025)
    x = margin if 'left' in position else width - side - margin
    y = margin if 'top' in position else height - side - margin
    if position == 'center':
        x, y = (width - side) / 2, (height - side) / 2
    return crop, (max(0, min(width - side, x)), max(0, min(height - side, y)), side / crop_w)
