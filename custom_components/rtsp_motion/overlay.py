"""Draw the ignored areas (and a percent grid) on a camera picture."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

GRID_STEP = 10  # percent
_OUTLINE = (255, 214, 0)
_DIM = 0.45  # ignored areas are darkened to this brightness


def draw_areas(rgb: np.ndarray, areas, grid: bool = False) -> np.ndarray:
    """Return a copy of rgb with the ignored areas darkened and outlined in yellow.

    areas are (x, y, width, height) fractions of the picture, as parse_areas gives.
    grid adds lines every 10% with percent labels, to read coordinates off.
    """
    h, w = rgb.shape[:2]
    out = rgb.astype(np.float32)
    boxes = []
    for x, y, aw, ah in areas:
        x0, y0 = int(x * w), int(y * h)
        x1, y1 = min(w, int((x + aw) * w)), min(h, int((y + ah) * h))
        if x1 > x0 and y1 > y0:
            out[y0:y1, x0:x1] *= _DIM
            boxes.append((x0, y0, x1, y1))
    img = Image.fromarray(out.astype(np.uint8))
    draw = ImageDraw.Draw(img, "RGBA")
    for x0, y0, x1, y1 in boxes:
        # Diagonal hatching, so the area reads as "off" even in a dark picture. Drawn
        # on a layer the size of the box, which clips the lines.
        bw, bh = x1 - x0, y1 - y0
        hatch = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        hd = ImageDraw.Draw(hatch)
        for k in range(-bh, bw, 12):
            hd.line([(k, bh), (k + bh, 0)], fill=(*_OUTLINE, 80), width=1)
        img.paste(hatch, (x0, y0), hatch)
        draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=_OUTLINE, width=2)
    if grid:
        _draw_grid(draw, w, h)
    return np.asarray(img)


def _draw_grid(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    font = ImageFont.load_default(size=max(11, w // 55))
    for p in range(GRID_STEP, 100, GRID_STEP):
        x, y = round(w * p / 100), round(h * p / 100)
        strong = p == 50
        color = (255, 255, 255, 140 if strong else 70)
        draw.line([(x, 0), (x, h)], fill=color, width=1)
        draw.line([(0, y), (w, y)], fill=color, width=1)
        for pos, anchor in (((x, 2), "mt"), ((2, y), "lm")):
            box = draw.textbbox(pos, str(p), font=font, anchor=anchor)
            draw.rectangle([box[0] - 2, box[1] - 1, box[2] + 2, box[3] + 1], fill=(0, 0, 0, 160))
            draw.text(pos, str(p), font=font, anchor=anchor, fill=(255, 255, 255, 255))
