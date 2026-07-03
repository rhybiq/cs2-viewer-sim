"""Small custom icon set -- drawn directly into tk.PhotoImage pixel buffers.

No Pillow (not a guaranteed dependency -- see requirements.txt/requirements-ocr.txt,
neither pulls it in for the base install) and no Canvas-to-image conversion
(unreliable on Windows without Ghostscript). Icons are rendered on a fixed
white background matching every place they're placed (default button/label
surface in this theme), so no alpha/transparency handling is needed.

Conceptual design grid is 24x24 at ~1.75px stroke weight; rendered at a small
fixed raster size appropriate for buttons/labels (not meant to scale up).
"""

import tkinter as tk

SIZE = 18
BG = "#ffffff"

_cache = {}


def _blank_rows():
    return [[BG] * SIZE for _ in range(SIZE)]


def _set(rows, x, y, color):
    if 0 <= x < SIZE and 0 <= y < SIZE:
        rows[y][x] = color


def _line(rows, x0, y0, x1, y1, color, weight=2):
    """Bresenham, thickened by plotting a small block per point."""
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    x, y = x0, y0
    half = weight // 2
    while True:
        for ox in range(-half, weight - half):
            for oy in range(-half, weight - half):
                _set(rows, x + ox, y + oy, color)
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy


def _polyline(rows, points, color, weight=2):
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        _line(rows, x0, y0, x1, y1, color, weight)


def _rows_to_photoimage(rows):
    img = tk.PhotoImage(width=SIZE, height=SIZE)
    img.put(" ".join("{" + " ".join(row) + "}" for row in rows))
    return img


def _draw(name, color):
    rows = _blank_rows()
    if name == "video":
        _polyline(rows, [(2, 4), (2, 14), (11, 14), (11, 4), (2, 4)], color, 2)
        _polyline(rows, [(11, 7), (16, 4), (16, 14), (11, 11)], color, 2)
    elif name == "folder":
        _polyline(rows, [(2, 6), (2, 15), (16, 15), (16, 7), (9, 7), (7, 5), (2, 5), (2, 6)], color, 2)
    elif name == "download":
        _line(rows, 9, 2, 9, 11, color, 2)
        _polyline(rows, [(5, 8), (9, 12), (13, 8)], color, 2)
        _line(rows, 3, 16, 15, 16, color, 2)
    elif name == "check":
        _polyline(rows, [(3, 9), (7, 13), (15, 4)], color, 2)
    else:
        raise ValueError(f"unknown icon {name!r}")
    return _rows_to_photoimage(rows)


def get(name, color):
    """Cached tk.PhotoImage for (name, color); built once and kept alive."""
    key = (name, color)
    if key not in _cache:
        _cache[key] = _draw(name, color)
    return _cache[key]
