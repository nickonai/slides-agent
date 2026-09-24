#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow"]
# ///
"""Коллаж 2×2 из четырёх PNG-слайдов — превью для README или поста.

    python scripts/preview.py build/png/01-title.png build/png/05-comparison.png \
        build/png/07-steps.png build/png/08-feature.png -o preview.png
"""
from __future__ import annotations

import argparse

from PIL import Image, ImageDraw, ImageFilter


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slides", nargs=4)
    ap.add_argument("-o", "--out", default="preview.png")
    ap.add_argument("--width", type=int, default=2400, help="ширина коллажа")
    ap.add_argument("--bg", default="#eef1f5")
    args = ap.parse_args()

    gap = args.width // 40
    tile_w = (args.width - gap * 3) // 2
    tile_h = tile_w * 9 // 16
    height = gap * 3 + tile_h * 2
    canvas = Image.new("RGB", (args.width, height), args.bg)
    for i, path in enumerate(args.slides):
        x = gap + (i % 2) * (tile_w + gap)
        y = gap + (i // 2) * (tile_h + gap)
        # мягкая тень под слайдом
        shadow = Image.new("L", (args.width, height), 0)
        ImageDraw.Draw(shadow).rounded_rectangle(
            (x, y + gap // 4, x + tile_w, y + tile_h + gap // 4), radius=18, fill=70)
        shadow = shadow.filter(ImageFilter.GaussianBlur(gap // 3))
        canvas.paste(Image.new("RGB", canvas.size, "#9aa3b2"), (0, 0), shadow)
        tile = Image.open(path).convert("RGB").resize((tile_w, tile_h), Image.LANCZOS)
        mask = Image.new("L", (tile_w, tile_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, tile_w, tile_h), radius=18, fill=255)
        canvas.paste(tile, (x, y), mask)
    canvas.save(args.out, optimize=True)
    print(f"[prev] {args.out} · {canvas.size[0]}×{canvas.size[1]}")


if __name__ == "__main__":
    main()
