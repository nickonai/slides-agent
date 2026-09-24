#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow"]
# ///
"""PNG слайдов → одна HTML-страница для телефона.

Все слайды идут лентой сверху вниз, каждый — JPEG 1440×810, вшитый как
data:URI: файл один, открывается в любом мессенджере и браузере без
интернета. Счётчик «N / всего» в шапке следует за прокруткой.

    python scripts/build_mobile.py build/png build/tema-mobile.html "Заголовок" "Подпись в шапке"

build_deck.py вызывает это сам после рендера PNG.
"""
from __future__ import annotations

import base64
import html
import io
import sys
from pathlib import Path

from PIL import Image


def build_mobile(png_dir: Path, out: Path, title: str, sub: str) -> Path:
    files = sorted(Path(png_dir).glob("*.png"))
    if not files:
        raise SystemExit(f"❌ В {png_dir} нет PNG — сначала соберите дек")
    n = len(files)
    items = []
    for i, f in enumerate(files, 1):
        im = Image.open(f).convert("RGB").resize((1440, 810), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=70, optimize=True, progressive=True)
        uri = base64.b64encode(buf.getvalue()).decode()
        items.append(
            f'<figure id="s{i}"><img src="data:image/jpeg;base64,{uri}" alt="Слайд {i}" '
            f'loading="lazy" width="1440" height="810"><figcaption>{i:02d} / {n:02d}</figcaption></figure>'
        )
    page = f'''<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{html.escape(title)}</title>
<style>
:root{{--ground:#0b0f17;--panel:#131a26;--ink:#e8ecf3;--muted:#8a95a8;color-scheme:dark}}
body{{margin:0;background:var(--ground);color:var(--ink);font:15px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding-inline:12px}}
header{{position:sticky;top:env(safe-area-inset-top,0px);z-index:2;background:var(--ground);padding-block:12px 10px;display:flex;justify-content:space-between;align-items:baseline;gap:12px;border-bottom:1px solid var(--panel)}}
h1{{font-size:15px;margin:0;font-weight:650;text-wrap:balance}}
header span{{color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums;white-space:nowrap}}
main{{max-width:1100px;margin-inline:auto;display:grid;gap:18px;padding-block:16px 40px}}
figure{{margin:0}}
img{{display:block;width:100%;height:auto;border-radius:8px;background:var(--panel)}}
figcaption{{color:var(--muted);font-size:12px;margin-top:6px;font-variant-numeric:tabular-nums;letter-spacing:.04em}}
</style></head><body>
<header><h1>{html.escape(sub)}</h1><span id="c">{n} слайдов</span></header>
<main>{"".join(items)}</main>
<script>
(function(){{var c=document.getElementById('c'),n={n};if(!('IntersectionObserver' in window))return;
var o=new IntersectionObserver(function(es){{es.forEach(function(e){{if(e.isIntersecting)c.textContent=e.target.id.slice(1)+' / '+n}})}},{{rootMargin:'-45% 0px -50% 0px'}});
document.querySelectorAll('figure').forEach(function(f){{o.observe(f)}})}})();
</script>
</body></html>'''
    out = Path(out)
    out.write_text(page, encoding="utf-8")
    print(f"[mob ] {out} · {out.stat().st_size / 1e6:.2f} МБ · слайдов: {n}")
    return out


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: build_mobile.py <png_dir> <out.html> [title] [subtitle]")
    title = sys.argv[3] if len(sys.argv) > 3 else "Презентация"
    sub = sys.argv[4] if len(sys.argv) > 4 else title
    build_mobile(Path(sys.argv[1]), Path(sys.argv[2]), title, sub)


if __name__ == "__main__":
    main()
