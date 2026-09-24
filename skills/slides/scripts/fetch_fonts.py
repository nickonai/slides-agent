#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Кэш шрифтов для самодостаточного дека.

Скачивает с Google Fonts woff2-файлы (кириллица и латиница) и пишет
fonts.json — по нему build_deck.py вшивает шрифты в HTML как base64, и дек
открывается без интернета. Шрифты Универус (Unbounded, Onest, JetBrains Mono)
уже лежат в assets/fonts/ — запускать нужно только для своего набора.

  python scripts/fetch_fonts.py                       # обновить шрифты по умолчанию
  python scripts/fetch_fonts.py --dir my-brand/fonts \\
      --css "https://fonts.googleapis.com/css2?family=Manrope:wght@400..800&display=swap"

Потом укажите папку и имена семейств в brand.yaml (fonts.dir, display, sans, mono).
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DIR = SKILL_DIR / "assets" / "fonts"
DEFAULT_CSS = (
    "https://fonts.googleapis.com/css2?family=Unbounded:wght@300..900"
    "&family=Onest:wght@300..800&family=JetBrains+Mono:wght@400..700&display=swap"
)
# Без Chrome-подобного UA Google отдаёт устаревшие форматы вместо woff2.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
SUBSETS = ("cyrillic", "latin")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def slug(family: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", family.lower()).strip("-")


def main() -> None:
    ap = argparse.ArgumentParser(description="Скачать woff2 с Google Fonts и записать fonts.json")
    ap.add_argument("--dir", default=str(DEFAULT_DIR), help="куда положить шрифты")
    ap.add_argument("--css", default=DEFAULT_CSS, help="ссылка css2 Google Fonts")
    args = ap.parse_args()

    fonts_dir = Path(args.dir).resolve()
    css = fetch(args.css).decode("utf-8")
    blocks = re.findall(r"/\* ([\w-]+) \*/\s*@font-face\s*\{(.*?)\}", css, re.S)
    manifest = []
    for subset, body in blocks:
        if subset not in SUBSETS:
            continue
        family = re.search(r"font-family: '([^']+)'", body).group(1)
        weight = re.search(r"font-weight: ([^;]+);", body).group(1).strip()
        url = re.search(r"url\(([^)]+)\)", body).group(1)
        unicode_range = re.search(r"unicode-range: ([^;]+);", body).group(1).strip()
        rel = f"{slug(family)}/{slug(family)}-{subset}.woff2"
        (fonts_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (fonts_dir / rel).write_bytes(fetch(url))
        manifest.append({"family": family, "weight": weight, "subset": subset,
                         "unicode_range": unicode_range, "file": rel})
        print(f"[font] {rel} · {family} {weight}")
    (fonts_dir / "fonts.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum((fonts_dir / m["file"]).stat().st_size for m in manifest)
    print(f"[done] {len(manifest)} файлов, {total // 1024} КБ → {fonts_dir}")
    print("Не забудьте положить рядом лицензию шрифта (OFL.txt) — её требует OFL.")


if __name__ == "__main__":
    main()
