#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""HTML-дек → PDF печатью через Chrome/Chromium: текст остаётся векторным.

    python scripts/print_pdf.py build/tema-deck.html [build/tema.pdf]

build_deck.py вызывает это сам; отдельно — когда дек правили руками.
"""
from __future__ import annotations

import sys
from pathlib import Path


def launch(p):
    """Системный Chrome, если есть; иначе Chromium, поставленный playwright."""
    try:
        return p.chromium.launch(channel="chrome")
    except Exception:
        return p.chromium.launch()


def print_pdf(deck: Path, out: Path) -> Path:
    from playwright.sync_api import sync_playwright

    deck, out = Path(deck).resolve(), Path(out).resolve()
    with sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(deck.as_uri())
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(1500)  # вёрстка миниатюр и шрифты из сети, если не вшиты
        page.pdf(path=str(out), width="1280px", height="720px", print_background=True,
                 margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        browser.close()
    print(f"[pdf ] {out}")
    return out


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: print_pdf.py <name>-deck.html [out.pdf]")
    deck = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else deck.with_name(
        deck.name.replace("-deck.html", ".pdf"))
    print_pdf(deck, out)


if __name__ == "__main__":
    main()
