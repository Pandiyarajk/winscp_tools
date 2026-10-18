"""Regenerate the SFTP Pilot icon assets.

Draws a blue rounded square with two white transfer arrows (up on the left,
down on the right) at 1024 px, then downsamples with LANCZOS to
sftp_pilot/assets/icon.png (256x256 RGBA) and icon.ico (multi-size).

Pillow is only needed to run this script, not by the app itself.

Usage: python packaging/make_icon.py

Author: Pandiyaraj Karuppasamy
Date: Oct-18-2026
"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw

BLUE = (37, 99, 235, 255)
WHITE = (255, 255, 255, 255)
BIG = 1024
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _arrow(draw: ImageDraw.ImageDraw, cx: int, up: bool) -> None:
    """Draw one vertical arrow centred on x=cx, pointing up or down."""
    top, bottom = 250, 774
    head_h, head_w, shaft_w = 250, 300, 110
    if up:
        tip, base = top, top + head_h
        draw.polygon([(cx, tip), (cx - head_w // 2, base), (cx + head_w // 2, base)], fill=WHITE)
        draw.rectangle([cx - shaft_w // 2, base - 5, cx + shaft_w // 2, bottom], fill=WHITE)
    else:
        tip, base = bottom, bottom - head_h
        draw.polygon([(cx, tip), (cx - head_w // 2, base), (cx + head_w // 2, base)], fill=WHITE)
        draw.rectangle([cx - shaft_w // 2, top, cx + shaft_w // 2, base + 5], fill=WHITE)


def build() -> Image.Image:
    img = Image.new("RGBA", (BIG, BIG), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, BIG - 1, BIG - 1], radius=230, fill=BLUE)
    _arrow(d, 335, up=True)
    _arrow(d, 689, up=False)
    return img


def main() -> None:
    out = pathlib.Path(__file__).resolve().parents[1] / "sftp_pilot" / "assets"
    out.mkdir(parents=True, exist_ok=True)
    big = build()
    big.resize((256, 256), Image.LANCZOS).save(out / "icon.png")
    big.resize((256, 256), Image.LANCZOS).save(out / "icon.ico", sizes=ICO_SIZES)


if __name__ == "__main__":
    main()
