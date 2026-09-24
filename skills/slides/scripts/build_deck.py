#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["python-pptx", "pyyaml", "playwright", "pillow"]
# ///
"""
Сборка презентации из YAML-сценария слайдов.

YAML (title / subtitle / body / presenter_notes / slide_type …)
  → HTML поверх дизайн-системы (assets/design)
  → PNG 2560×1440 (playwright + Chrome или Chromium)
  → <name>-deck.html · <name>.pptx (заметки докладчика) · <name>.pdf · <name>-mobile.html

Запуск:
  python scripts/build_deck.py presentations/tema/slides.yaml \
      --out presentations/tema/build --name tema

Фирменный стиль (название, знак, палитра, шрифты, плашка финала) берётся из
brand.yaml — порядок поиска описан в scripts/brand.py. Картинки из YAML
(photo, image, documents[].file) — пути относительно файла YAML или абсолютные.
Шрифты вшиваются из assets/fonts/ (кэш создаёт fetch_fonts.py); без кэша дек
тянет их из Google Fonts.
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
from base64 import b64encode
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from brand import add_brand_argument, load_brand, mark_svg_parts, resolve_asset  # noqa: E402

DS = SKILL_DIR / "assets" / "design"

# Заполняются в main(): бренд и папка YAML-сценария (от неё считаются пути картинок).
BRAND: dict = {}
YAML_DIR: Path = Path.cwd()

W, H = 1280, 720
PAD_X, PAD_Y = 88, 76
FOOT_H = 84  # колонтитул и зазор над ним: ниже этой линии контент не заходит

# В трансляции правый верхний угол занимает окно спикера. С флагом --speaker-zone
# туда не попадает ничего, кроме фоновой графики; размеры — --safe-w/--safe-h.
# Без флага зона выключена (SAFE_W = 0) и контент занимает всю ширину.
SPEAKER_W, SPEAKER_H = 340, 200
SAFE_W, SAFE_H = 0, 0
SAFE_GAP = 24
NBSP = " "


def top_w() -> int:
    """Ширина, доступная контенту слева от окна спикера (без зоны — вся ширина поля)."""
    if not SAFE_W:
        return W - 2 * PAD_X
    return W - PAD_X - SAFE_W - SAFE_GAP


def safe_top() -> int:
    """Первая безопасная координата по вертикали для правой колонки."""
    if not SAFE_W:
        return PAD_Y
    return SAFE_H + 12


def panel_offset() -> int:
    """Отступ правой колонки от верха slide-pad, чтобы она начиналась под окном спикера."""
    return safe_top() - PAD_Y


def panel_max_h() -> int:
    """Сколько высоты остаётся правой колонке между окном спикера и колонтитулом."""
    return H - FOOT_H - safe_top() - 16


# ────────────────────────────── текст ──────────────────────────────

def nb(text: str) -> str:
    """Числа и единицы не рвутся по строкам: «49 900 ₽», «12 месяцев», «15 минут»."""
    t = str(text or "")
    t = re.sub(r" — ", NBSP + "— ", t)
    t = re.sub(r"(?<=\d) (?=\d{3}(?!\d))", NBSP, t)
    t = re.sub(r"(?<=[\d%]) (?=[₽%€$])", NBSP, t)
    t = re.sub(r"(?<=\d) (?=(?:тыс|млн|дн|день|дня|дней|месяц|месяца|месяцев|мин|минут|"
               r"час|часа|часов|евро|руб|клиент|клиента|клиентов|предложени)\S*)", NBSP, t)
    return t


def esc(text: str) -> str:
    return html_mod.escape(nb(str(text or "").strip()))


def keep(text: str) -> str:
    """Не даём рвать по дефису составные слова вроде «ИИ-агенты», «16:9»."""
    out = []
    for word in text.split(" "):
        if "-" in word and len(word) > 1:
            out.append(f'<span style="white-space:nowrap">{word}</span>')
        else:
            out.append(word)
    return " ".join(out)


CAPS_EM = 0.86  # ширина заглавной буквы Unbounded 700 в долях кегля, с запасом


def title_of(s: dict, steps: list[tuple[int, int]], width: int | None = None) -> tuple[str, int]:
    """Заголовок с защитой переносов и кегль по чистой длине (без разметки).

    width — ширина колонки: самое длинное слово (его нельзя перенести) должно в неё поместиться.
    """
    plain = str(s.get("title") or "").strip()
    size = fit(plain, steps)
    if width:
        longest = max((len(w) for w in plain.split()), default=1)
        size = max(min(size, int((width - 16) / (CAPS_EM * longest))), 30)
    return keep(esc(plain)), size


def fit(text: str, steps: list[tuple[int, int]]) -> int:
    """Размер шрифта по длине строки: [(макс_длина, размер), ...] по возрастанию длины."""
    n = len(text or "")
    for limit, size in steps:
        if n <= limit:
            return size
    return steps[-1][1]


def lines_of(slide: dict) -> list[str]:
    return list_of(slide.get("body"))


def list_of(value) -> list[str]:
    """Список строк из YAML-списка или блочного текста."""
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [ln.strip() for ln in str(value).splitlines() if ln.strip()]


# Маркеры в начале строки: ❌/✕ — «плохо», ✅/✓ — «хорошо», 🎯/→ — результат.
MARKS = (("❌", "bad"), ("✕", "bad"), ("✗", "bad"), ("✅", "good"), ("✓", "good"),
         ("🎯", "result"), ("→", "result"))


def split_mark(line: str) -> tuple[str | None, str]:
    line = line.strip()
    for m, kind in MARKS:
        if line.startswith(m):
            return kind, line[len(m):].strip()
    return None, line


def glyph(kind: str, dark: bool) -> str:
    """Свой значок дизайн-системы вместо цветных эмодзи."""
    good = "var(--citron-400)" if dark else "var(--blue-500)"
    if kind == "bad":
        return '<span style="color:var(--danger);flex:none;line-height:1.2">✕</span>'
    if kind == "result":
        return f'<span style="color:{good};flex:none;line-height:1.2">→</span>'
    if kind == "good":
        return f'<span style="color:{good};flex:none;line-height:1.2">✓</span>'
    return ('<span style="width:9px;height:9px;border-radius:999px;background:var(--blue-500);'
            'flex:none;margin-top:.55em"></span>')


def rows_html(lines: list[str], *, dark: bool, size: int = 25, gap: int = 16,
              default: str = "good", color: str | None = None) -> str:
    """Список строк со значками. default — вид значка для строк без маркера."""
    tcol = color or ("#dfe6f2" if dark else "var(--fg-2)")
    out = []
    for ln in lines:
        kind, text = split_mark(ln)
        kind = kind or default
        weight = "600" if kind == "result" else "400"
        out.append(
            f'<div style="display:flex;gap:13px;align-items:flex-start;font-size:{size}px;'
            f'line-height:1.35;color:{tcol}">{glyph(kind, dark)}'
            f'<span style="font-weight:{weight}">{keep(esc(text))}</span></div>'
        )
    return f'<div style="display:flex;flex-direction:column;gap:{gap}px">{"".join(out)}</div>'


def note_html(text: str | None, *, dark: bool = False, mt: int = 16) -> str:
    """Сноска: источник, оговорка, подпись к демонстрационным данным."""
    if not text:
        return ""
    col = "rgba(223,230,242,.62)" if dark else "var(--fg-4)"
    return (f'<div style="margin-top:{mt}px;font-size:17px;line-height:1.35;color:{col};'
            f'max-width:{top_w()}px">{esc(text)}</div>')


def eyebrow_html(text: str | None, mb: int = 16) -> str:
    return f'<div class="s-eyebrow" style="margin-bottom:{mb}px">{esc(text)}</div>' if text else ""


def badge_html(text: str | None, mb: int = 14) -> str:
    if not text:
        return ""
    return (f'<span style="display:inline-block;margin-bottom:{mb}px;background:var(--citron-400);'
            f'color:var(--ink-900);font-weight:600;font-size:17px;letter-spacing:.02em;'
            f'padding:6px 14px;border-radius:999px">{esc(text)}</span>')


# ────────────────────────────── графика ──────────────────────────────

def mark(size: int, color: str) -> str:
    """Знак бренда из brand.yaml (logo.mark). Пусто, если знак не задан."""
    parts = mark_svg_parts(BRAND)
    if not parts:
        return ""
    vb, inner = parts
    return (f'<svg viewBox="{vb}" width="{size}" height="{size}" fill="currentColor" '
            f'style="color:{color};flex:none">{inner}</svg>')


def arc_bg(color: str, style: str) -> str:
    """Фоновый мотив: знак крупно, почти прозрачно, уведён за край. Выключается motif: false."""
    parts = mark_svg_parts(BRAND) if BRAND.get("motif", True) else None
    if not parts:
        return ""
    vb, inner = parts
    return (f'<svg class="arc-bg" viewBox="{vb}" fill="currentColor" '
            f'style="color:{color};{style}">{inner}</svg>')


def wordmark() -> str:
    return esc(BRAND.get("wordmark") or "")


def foot(page: int, light_text: bool = False) -> str:
    color = "#fff" if light_text else "inherit"
    pg_color = "rgba(255,255,255,.7)" if light_text else ""
    glyph_fill = "#ffffff" if light_text else "var(--blue-400)"
    pg_style = f' style="color:{pg_color}"' if pg_color else ""
    return (
        '<div class="slide-foot">'
        f'<span class="brand" style="color:{color}">{mark(22, glyph_fill)}{wordmark()}</span>'
        f'<span class="pg"{pg_style}>{page:02d}</span></div>'
    )


def resolve_image(rel_path: str) -> Path:
    """Путь картинки из YAML: абсолютный или относительно файла YAML."""
    path = Path(str(rel_path)).expanduser()
    if not path.is_absolute():
        path = YAML_DIR / path
    path = path.resolve()
    if not path.exists():
        raise SystemExit(f"❌ Картинка не найдена: {rel_path} (искали {path})")
    return path


def img_uri(rel_path: str, max_h: int = 900, crop: list | None = None) -> str:
    """Картинка из YAML → data:URI. Большие портреты ужимаем по высоте."""
    from io import BytesIO

    from PIL import Image

    src = resolve_image(rel_path)
    im = Image.open(src)
    if crop:
        l, t, r, b = crop
        im = im.crop((round(l * im.width), round(t * im.height),
                      round(r * im.width), round(b * im.height)))
    if im.height > max_h:
        im = im.resize((round(im.width * max_h / im.height), max_h), Image.LANCZOS)
    fmt = "PNG" if im.mode in ("RGBA", "LA", "P") else "JPEG"
    buf = BytesIO()
    im.save(buf, fmt, quality=88)
    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{b64encode(buf.getvalue()).decode()}"


def browser_frame(url: str, inner: str) -> str:
    """Макет окна браузера для реального скриншота продукта."""
    return (
        '<div style="background:var(--ink-700);border:1px solid rgba(255,255,255,.08);'
        'border-radius:20px;overflow:hidden;box-shadow:var(--shadow-xl)">'
        '<div style="display:flex;align-items:center;gap:9px;padding:14px 18px;background:var(--ink-600)">'
        '<span style="width:11px;height:11px;border-radius:999px;background:#ff5f57"></span>'
        '<span style="width:11px;height:11px;border-radius:999px;background:#febc2e"></span>'
        '<span style="width:11px;height:11px;border-radius:999px;background:#28c840"></span>'
        '<span style="margin-left:12px;flex:1;background:var(--ink-900);border-radius:999px;'
        f'padding:7px 14px;font-family:var(--font-mono);font-size:13px;color:#8f9bb3">{esc(url)}</span>'
        f'</div>{inner}</div>'
    )


def figure_card(s: dict) -> str:
    """Карточка с одной крупной величиной: цена тарифа, ценность бонуса, срок."""
    fig = str(s.get("figure") or "").strip()
    size = fit(fig, [(7, 64), (11, 52), (999, 42)])
    parts = ['<div style="background:var(--ink-700);border:1px solid rgba(255,255,255,.08);'
             'border-radius:20px;padding:30px 32px;box-shadow:var(--shadow-xl)">']
    parts.append(eyebrow_html(s.get("figure_label"), 14))
    parts.append(f'<div style="font-family:var(--font-display);font-weight:700;font-size:{size}px;'
                 f'line-height:1;letter-spacing:-.03em;color:#fff">{esc(fig)}</div>')
    if s.get("figure_note"):
        parts.append(f'<div style="margin-top:16px;font-size:20px;line-height:1.35;color:#dfe6f2">'
                     f'{esc(s["figure_note"])}</div>')
    parts.append("</div>")
    return "".join(parts)


def chain_panel(s: dict) -> str:
    """Цепочка ролей или модулей с подсветкой текущего шага."""
    items = list_of(s.get("chain"))
    active = int(s.get("active") or 0)
    compact = len(items) > 5
    fs = 20 if compact else 22
    pad = "8px 14px" if compact else "11px 16px"
    rows = []
    for i, name in enumerate(items, 1):
        on = i == active
        bg = "var(--citron-400)" if on else "rgba(255,255,255,.06)"
        col = "var(--ink-900)" if on else "#dfe6f2"
        numcol = "var(--ink-900)" if on else "var(--citron-400)"
        rows.append(
            f'<div style="display:flex;align-items:center;gap:14px;background:{bg};border-radius:14px;padding:{pad}">'
            f'<span style="font-family:var(--font-display);font-weight:700;font-size:{fs}px;'
            f'color:{numcol};min-width:26px;line-height:1">{i}</span>'
            f'<span style="font-size:{fs}px;line-height:1.25;color:{col};font-weight:{"600" if on else "400"}">'
            f'{esc(name)}</span></div>'
        )
    return ('<div style="background:var(--ink-700);border:1px solid rgba(255,255,255,.08);border-radius:20px;'
            'padding:20px 20px;box-shadow:var(--shadow-xl);display:flex;flex-direction:column;gap:6px">'
            + eyebrow_html(s.get("chain_title"), 10) + "".join(rows) + "</div>")


def feature_panel(s: dict, cfg: dict) -> str:
    """Правая колонка слайда feature: скриншот, крупная величина или цепочка. Иначе пусто."""
    if s.get("image"):
        uri = img_uri(s["image"], max_h=760, crop=s.get("crop"))
        url = s.get("url") or BRAND.get("site") or "example.com"
        return browser_frame(url, f'<img src="{uri}" alt="" style="display:block;width:100%;'
                                  f'max-height:{panel_max_h() - 48}px;object-fit:contain;background:#fff">')
    if s.get("figure"):
        return figure_card(s)
    if s.get("chain"):
        return chain_panel(s)
    return ""


# ────────────────────────────── типы слайдов ──────────────────────────────

def t_title(s: dict, page: int, cfg: dict) -> str:
    title, size = title_of(s, [(18, 76), (26, 62), (38, 50), (999, 42)], top_w())
    sub = esc(s.get("subtitle"))
    chips = "".join(
        '<span style="display:inline-flex;align-items:center;gap:10px;border:1px solid rgba(255,255,255,.16);'
        'border-radius:999px;padding:13px 24px;font-size:23px;color:#dfe6f2">'
        '<span style="width:7px;height:7px;border-radius:999px;background:var(--citron-400)"></span>'
        f"{esc(ln)}</span>"
        for ln in lines_of(s)
    )
    return f"""
<div class="slide ink">
  {arc_bg("var(--blue-400)", "right:-130px;top:-120px;width:620px;height:620px;opacity:.1")}
  <div class="slide-pad" style="justify-content:center">
    <div style="display:flex;align-items:center;gap:13px;margin-bottom:38px">
      {mark(38, "var(--blue-400)")}
      <span style="font-family:var(--font-display);font-weight:700;font-size:28px;color:#fff;letter-spacing:-.02em">{wordmark()}</span>
    </div>
    {eyebrow_html(s.get("eyebrow") or cfg.get("eyebrow"), 22)}
    <h1 class="s-display" style="font-size:{size}px;max-width:{top_w()}px;margin:0">{title}</h1>
    {f'<p class="s-lead" style="margin-top:26px;max-width:{top_w()}px;font-size:30px">{sub}</p>' if sub else ''}
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:38px">{chips}</div>
  </div>
  {foot(page, light_text=True)}
</div>"""


def t_agenda(s: dict, page: int, cfg: dict) -> str:
    items = lines_of(s)
    cols = 3 if len(items) <= 3 else 2
    title, size = title_of(s, [(18, 62), (28, 52), (999, 44)], top_w())
    cells = "".join(
        '<div style="display:flex;gap:18px;align-items:baseline;border-top:2px solid var(--ink-900);padding-top:18px">'
        f'<span style="font-family:var(--font-display);font-weight:700;font-size:29px;color:var(--blue-500)">{i:02d}</span>'
        f'<div style="font-family:var(--font-display);font-weight:600;font-size:27px;line-height:1.25">{keep(esc(ln))}</div></div>'
        for i, ln in enumerate(items, 1)
    )
    return f"""
<div class="slide">
  <div class="slide-pad" style="justify-content:center">
    {eyebrow_html(s.get("subtitle"), 18)}
    <h2 class="s-display" style="font-size:{size}px;margin:0 0 {56 if len(items) <= 4 else 36}px;max-width:{top_w()}px">{title}</h2>
    <div style="display:grid;grid-template-columns:repeat({cols},1fr);gap:{30 if len(items) <= 4 else 18}px 44px;max-width:1104px">{cells}</div>
    {note_html(s.get("footnote"), mt=36)}
  </div>
  {foot(page)}
</div>"""


def t_stat(s: dict, page: int, cfg: dict) -> str:
    plain = str(s.get("title") or "").strip()
    m = re.match(r"^([\d\s]+[%₽]?)\s+(.+)$", plain)
    figure, rest = (m.group(1).strip(), m.group(2).strip()) if m else (plain, "")
    fig_size = fit(figure, [(3, 200), (6, 158), (10, 110), (999, 80)])
    rest_html = keep(esc(rest))
    cards = "".join(
        f'<div class="s-card" style="padding:24px 28px;min-width:325px;font-size:24px;color:var(--fg-2)">{keep(esc(ln))}</div>'
        for ln in lines_of(s)
    )
    return f"""
<div class="slide">
  {arc_bg("var(--blue-400)", "left:-200px;bottom:-250px;width:540px;height:540px;opacity:.05")}
  <div class="slide-pad" style="justify-content:{'flex-start' if SAFE_W else 'center'}">
    <div style="display:flex;align-items:{'flex-start' if SAFE_W else 'center'};gap:56px">
      <div style="max-width:620px;margin-top:{44 if SAFE_W else 0}px">
        {eyebrow_html(s.get("subtitle"), 14)}
        <div style="font-family:var(--font-display);font-weight:700;font-size:{fig_size}px;line-height:.86;letter-spacing:-.04em;color:var(--fg-1)">{esc(figure)}</div>
        {f'<div class="s-lead" style="margin-top:20px;font-size:34px;font-family:var(--font-display);font-weight:600;color:var(--fg-1);line-height:1.15;letter-spacing:-.02em">{rest_html}</div>' if rest else ''}
      </div>
      <div style="display:flex;flex-direction:column;gap:16px;margin-top:{panel_offset() if SAFE_W else 0}px">{cards}</div>
    </div>
    {note_html(s.get("footnote"), mt=28)}
  </div>
  {foot(page)}
</div>"""


LABEL_RE = re.compile(r"^([А-ЯЁA-Z0-9][А-ЯЁA-Z0-9\s]{1,})\s*[—–-]\s*(.+)$")


def _split_comparison(s: dict) -> tuple[str, list[str], str, list[str]]:
    """Колонки сравнения.

    Приоритет: явные списки left/right → маркеры ❌/✅ в строках → метки «ЛЕЙБЛ — текст»
    (первая метка — левая колонка, вторая — правая) → старая раскладка через строку.
    """
    left_label = s.get("left_label") or "Старый путь"
    right_label = s.get("right_label") or "Новый путь"
    left, right = list_of(s.get("left")), list_of(s.get("right"))
    if left or right:
        return left_label, left, right_label, right

    items = lines_of(s)
    marked = any(split_mark(ln)[0] in ("bad", "good") for ln in items)
    labels: list[str] = []
    last = left
    for ln in items:
        kind, text = split_mark(ln)
        if kind == "bad":
            left.append(text)
            last = left
            continue
        if kind == "good":
            right.append(text)
            last = right
            continue
        m = LABEL_RE.match(ln)
        if m and not marked:
            label, text = m.group(1).strip(), m.group(2).strip()
            if label not in labels:
                labels.append(label)
            side = left if labels.index(label) == 0 else right
            side.append(text[0].upper() + text[1:] if text else text)
            last = side
            continue
        if marked:
            last.append(text)
        else:
            (left if len(left) <= len(right) else right).append(ln)
    if labels:
        left_label = s.get("left_label") or labels[0].capitalize()
        if len(labels) > 1:
            right_label = s.get("right_label") or labels[1].capitalize()
    return left_label, left, right_label, right


def t_comparison(s: dict, page: int, cfg: dict) -> str:
    left_label, left, right_label, right = _split_comparison(s)
    title, size = title_of(s, [(20, 56), (30, 48), (999, 40)], top_w())
    fs = 26 if max(len(left), len(right)) <= 4 else 23

    def rows(items, mark_char, color, text_color):
        return "".join(
            '<div style="display:flex;gap:13px;align-items:flex-start">'
            f'<span style="color:{color};font-size:{fs + 1}px;line-height:1.2;flex:none">{mark_char}</span>'
            f'<span style="color:{text_color}">{keep(esc(t))}</span></div>'
            for t in items
        )

    return f"""
<div class="slide">
  <div class="slide-pad" style="justify-content:center">
    {eyebrow_html(s.get("subtitle"), 16)}
    <h2 class="s-display" style="font-size:{size}px;margin:0 0 36px;max-width:{top_w()}px">{title}</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:start">
      <div class="s-card" style="display:flex;flex-direction:column;gap:20px;background:var(--bone)">
        <div style="font-family:var(--font-mono);font-size:16px;letter-spacing:.1em;text-transform:uppercase;color:var(--fg-3)">{esc(left_label)}</div>
        <div style="display:flex;flex-direction:column;gap:18px;font-size:{fs}px;line-height:1.35;color:var(--fg-2)">{rows(left, '✕', 'var(--danger)', 'var(--fg-2)')}</div>
      </div>
      <div class="s-card" style="display:flex;flex-direction:column;gap:20px;background:var(--ink-900);border:0">
        <div style="font-family:var(--font-mono);font-size:16px;letter-spacing:.1em;text-transform:uppercase;color:var(--citron-400)">{esc(right_label)}</div>
        <div style="display:flex;flex-direction:column;gap:18px;font-size:{fs}px;line-height:1.35">{rows(right, '✓', 'var(--citron-400)', '#dfe6f2')}</div>
      </div>
    </div>
    {note_html(s.get("footnote"), mt=22)}
  </div>
  {foot(page)}
</div>"""


def t_feature(s: dict, page: int, cfg: dict) -> str:
    """Тёмный слайд продукта: текст слева, справа — скриншот, величина или цепочка шагов."""
    panel = feature_panel(s, cfg)
    if panel:
        title, size = title_of(s, [(14, 60), (22, 50), (999, 42)], 470)
        text_w = 470
        # с зоной спикера колонка начинается под ней, без зоны — по центру
        align = f"align-self:flex-start;margin-top:{panel_offset()}px" if SAFE_W else "align-self:center"
        right = f'<div style="flex:none;width:470px;{align}">{panel}</div>'
        bg = ""
    else:
        title, size = title_of(s, [(16, 66), (26, 54), (999, 44)], top_w())
        text_w = top_w()
        right = ""
        bg = arc_bg("var(--blue-400)", "right:-230px;bottom:-260px;width:600px;height:600px;opacity:.08")
    lines = lines_of(s)
    rows = rows_html(lines, dark=True, size=25, gap=16, default="good")
    return f"""
<div class="slide ink">
  {bg}
  <div class="slide-pad" style="flex-direction:row;align-items:center;gap:56px">
    <div style="flex:1;max-width:{text_w}px">
      {badge_html(s.get("badge"))}
      {eyebrow_html(s.get("subtitle"), 16)}
      <h2 class="s-display" style="font-size:{size}px;margin:0 0 30px;max-width:{text_w}px">{title}</h2>
      {rows}
      {note_html(s.get("footnote"), dark=True, mt=22)}
    </div>
    {right}
  </div>
  {foot(page, light_text=True)}
</div>"""




def t_case(s: dict, page: int, cfg: dict) -> str:
    name = esc(s.get("title"))
    initials = "".join(part[0] for part in str(s.get("title", "")).split()[:2]).upper()
    statement_plain = str(s.get("subtitle") or "").strip()
    statement = esc(statement_plain)
    case_cfg = BRAND.get("case") or {}
    disclaimer = case_cfg.get("disclaimer") or ""
    role = esc(s.get("role") or case_cfg.get("role") or "")
    lines = lines_of(s)
    facts = rows_html(lines, dark=False, size=25 if len(lines) <= 4 else 23, gap=14 if len(lines) <= 4 else 11,
                      default="result")
    notes = ""
    if s.get("footnote"):
        notes += note_html(s["footnote"], mt=26)
        notes += note_html(disclaimer, mt=6)
    else:
        notes += note_html(disclaimer, mt=26)
    if s.get("photo"):
        portrait = (
            f'<img src="{img_uri(s["photo"], max_h=660)}" alt="{name}" '
            'style="width:280px;height:280px;object-fit:cover;border-radius:24px;box-shadow:var(--shadow-md)">'
        )
    else:
        portrait = (
            '<span style="width:180px;height:180px;border-radius:36px;background:var(--brand-grad);'
            'display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;'
            f'font-family:var(--font-display);font-size:56px">{initials}</span>'
        )
    return f"""
<div class="slide" style="background:var(--bone)">
  <div class="slide-pad" style="flex-direction:row;align-items:center;gap:54px">
    <div style="flex:1">
      <div class="s-eyebrow" style="margin-bottom:22px">{esc(s.get("eyebrow") or case_cfg.get("eyebrow") or "")}</div>
      <p style="font-family:var(--font-display);font-weight:500;font-size:{fit(statement_plain, [(28, 42), (44, 36), (999, 31)])}px;line-height:1.25;letter-spacing:-.02em;margin:0">{statement}</p>
      <div style="margin-top:30px">{facts}</div>
      {notes}
    </div>
    <div style="flex:none;width:300px;display:flex;flex-direction:column;align-items:center;gap:14px;align-self:flex-end;padding-bottom:16px">
      {portrait}
      <div style="text-align:center">
        <div style="font-weight:700;font-size:23px">{name}</div>
        <div style="font-size:18px;color:var(--fg-3);margin-top:2px">{role}</div>
      </div>
    </div>
  </div>
  {foot(page)}
</div>"""


def t_author(s: dict, page: int, cfg: dict) -> str:
    """Слайд об авторе: портрет без фона справа, история слева."""
    title, size = title_of(s, [(16, 60), (26, 50), (999, 40)], 640)
    sub = esc(s.get("subtitle"))
    rows = "".join(
        '<div style="display:flex;gap:14px;align-items:flex-start;font-size:25px;color:var(--fg-2);line-height:1.35">'
        '<span style="color:var(--blue-500);font-size:25px;line-height:1.2">—</span>'
        f"<span>{keep(esc(ln))}</span></div>"
        for ln in lines_of(s)
    )
    photo = s.get("photo")
    portrait = (
        f'<img src="{img_uri(photo, max_h=760)}" alt="{esc(s.get("title"))}" '
        'style="height:408px;width:auto;object-fit:contain;filter:drop-shadow(0 26px 50px rgba(13,19,34,.22))">'
        if photo else ""
    )
    return f"""
<div class="slide">
  {arc_bg("var(--blue-400)", "left:-190px;top:-140px;width:520px;height:520px;opacity:.06")}
  <div class="slide-pad" style="flex-direction:row;align-items:center;gap:40px">
    <div style="flex:1">
      <h2 class="s-display" style="font-size:{size}px;margin:0">{title}</h2>
      {f'<p class="s-lead" style="margin-top:16px;max-width:620px;font-size:28px">{sub}</p>' if sub else ''}
      <div style="display:flex;flex-direction:column;gap:16px;margin-top:34px;max-width:640px">{rows}</div>
    </div>
    <div style="flex:none;display:flex;align-items:flex-end;justify-content:center;width:400px;align-self:flex-end;padding-bottom:14px">{portrait}</div>
  </div>
  {foot(page)}
</div>"""


def t_bullets(s: dict, page: int, cfg: dict) -> str:
    title, size = title_of(s, [(16, 66), (26, 54), (999, 44)], top_w())
    sub = esc(s.get("subtitle"))
    items = lines_of(s)
    fs = 28 if len(items) >= 4 else 31
    rows = "".join(
        '<div style="display:flex;gap:18px;align-items:flex-start;border-top:1px solid var(--border-paper);padding-top:16px">'
        f'{glyph(split_mark(ln)[0] or "dot", False)}'
        f'<span style="font-size:{fs}px;line-height:1.3;color:var(--fg-1)">{keep(esc(split_mark(ln)[1]))}</span></div>'
        for ln in items
    )
    return f"""
<div class="slide">
  {arc_bg("var(--blue-400)", "right:-215px;bottom:-265px;width:560px;height:560px;opacity:.05")}
  <div class="slide-pad" style="justify-content:center">
    <h2 class="s-display" style="font-size:{size}px;margin:0;max-width:{top_w()}px">{title}</h2>
    {f'<p class="s-lead" style="margin-top:18px;max-width:{top_w()}px;font-size:28px">{sub}</p>' if sub else ''}
    <div style="display:flex;flex-direction:column;gap:{16 if len(items) <= 4 else 10}px;margin-top:{(36 if sub else 44) if len(items) <= 4 else 28}px;max-width:{top_w()}px;font-size:{fs}px">{rows}</div>
    {note_html(s.get("footnote"), mt=20)}
  </div>
  {foot(page)}
</div>"""


def t_closing(s: dict, page: int, cfg: dict) -> str:
    title, size = title_of(s, [(16, 72), (26, 58), (999, 48)], top_w())
    sub = esc(s.get("subtitle"))
    chips = "".join(
        '<span style="display:inline-flex;align-items:center;gap:10px;background:rgba(255,255,255,.14);'
        'border-radius:999px;padding:14px 26px;font-size:23px;color:#fff">'
        '<span style="width:7px;height:7px;border-radius:999px;background:var(--citron-400)"></span>'
        f"{esc(ln)}</span>"
        for ln in lines_of(s)
    )
    cta_text = s.get("cta") or cfg.get("cta")
    cta = ('<div style="margin-top:36px"><span style="background:var(--citron-400);color:var(--ink-900);'
           'font-weight:600;font-size:24px;padding:18px 36px;border-radius:999px">'
           f'{esc(cta_text)}</span></div>') if cta_text else ""
    return f"""
<div class="slide blue">
  {arc_bg("#ffffff", "right:-150px;top:-120px;width:640px;height:640px;opacity:.13")}
  <div class="slide-pad" style="justify-content:center">
    <h2 class="s-display" style="font-size:{size}px;color:#fff;max-width:{top_w()}px;margin:0">{title}</h2>
    {f'<p style="font-size:29px;color:#fff;margin:20px 0 0;max-width:790px;line-height:1.4">{sub}</p>' if sub else ''}
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:30px;max-width:{top_w()}px">{chips}</div>
    {cta}
  </div>
  {foot(page, light_text=True)}
</div>"""


def t_statement(s: dict, page: int, cfg: dict) -> str:
    """Одна фраза во весь слайд — для переходов. Строки body, если есть, идут списком под ней."""
    lines = lines_of(s)
    if lines:
        title, size = title_of(s, [(14, 84), (24, 68), (36, 56), (999, 46)], top_w())
    else:
        title, size = title_of(s, [(14, 96), (24, 76), (36, 60), (999, 48)], top_w())
    sub = esc(s.get("subtitle"))
    body = ""
    if lines:
        body = (f'<div style="margin-top:36px;max-width:{top_w()}px">'
                f'{rows_html(lines, dark=False, size=28 if len(lines) <= 4 else 26, gap=14, default="dot", color="var(--fg-1)")}</div>')
    return f"""
<div class="slide">
  {arc_bg("var(--blue-400)", "right:-230px;top:-190px;width:600px;height:600px;opacity:.05")}
  <div class="slide-pad" style="justify-content:center">
    <h2 class="s-display" style="font-size:{size}px;margin:0;max-width:{top_w()}px">{title}</h2>
    {f'<p class="s-lead" style="margin-top:26px;max-width:{top_w()}px;font-size:30px">{sub}</p>' if sub else ''}
    {body}
    {note_html(s.get("footnote"), mt=28)}
  </div>
  {foot(page)}
</div>"""


def t_docs(s: dict, page: int, cfg: dict) -> str:
    """Документы компании: сканы в карточках с подписями."""
    title, size = title_of(s, [(20, 52), (30, 44), (999, 36)], top_w())
    cards = ""
    for item in s.get("documents", []) or []:
        cards += (
            '<div class="s-card" style="flex:1;display:flex;flex-direction:column;gap:14px;align-items:center;padding:22px">'
            f'<img src="{img_uri(item["file"], max_h=560, crop=item.get("crop"))}" alt="{esc(item.get("caption"))}" '
            'style="width:100%;height:240px;object-fit:contain">'
            f'<div style="font-size:19px;line-height:1.3;color:var(--fg-2);text-align:center">{esc(item.get("caption"))}</div>'
            "</div>"
        )
    return f"""
<div class="slide">
  <div class="slide-pad" style="justify-content:flex-start">
    <div style="min-height:{panel_offset()}px">
      {eyebrow_html(s.get("subtitle"), 16)}
      <h2 class="s-display" style="font-size:{size}px;margin:0;max-width:{top_w()}px">{title}</h2>
    </div>
    <div style="display:flex;gap:22px;align-items:stretch">{cards}</div>
    {note_html(s.get("footnote"), mt=14)}
  </div>
  {foot(page)}
</div>"""


def t_cards(s: dict, page: int, cfg: dict) -> str:
    """Карточки — когда важен смысл каждого пункта, а не список."""
    title, size = title_of(s, [(18, 58), (28, 48), (999, 40)], top_w())
    items = lines_of(s)
    fs = 28 if len(items) <= 2 else 26
    cells = "".join(
        '<div class="s-card" style="flex:1;display:flex;align-items:center;padding:34px 30px">'
        f'<div style="font-size:{fs}px;line-height:1.32;color:var(--fg-1)">{keep(esc(line))}</div></div>'
        for line in items
    )
    return f"""
<div class="slide">
  <div class="slide-pad" style="justify-content:center">
    {eyebrow_html(s.get("subtitle"), 16)}
    <h2 class="s-display" style="font-size:{size}px;margin:0 0 40px;max-width:{top_w()}px">{title}</h2>
    <div style="display:flex;gap:22px;align-items:stretch">{cells}</div>
    {note_html(s.get("footnote"), mt=24)}
  </div>
  {foot(page)}
</div>"""


STEP_PREFIX = re.compile(r"^(?:Шаг\s*)?\d+\s*[.)—–-]\s*", re.I)


def t_steps(s: dict, page: int, cfg: dict) -> str:
    """Схема пути: пронумерованные шаги со стрелками между ними."""
    title, size = title_of(s, [(18, 58), (28, 48), (999, 40)], top_w())
    items = [STEP_PREFIX.sub("", ln) for ln in lines_of(s)]
    fs = 25 if len(items) <= 4 else 23
    pad = "30px 28px" if len(items) <= 4 else "26px 20px"
    cells = []
    for i, line in enumerate(items):
        cells.append(
            f'<div class="s-card" style="flex:1;display:flex;flex-direction:column;gap:16px;padding:{pad}">'
            f'<span style="font-family:var(--font-display);font-weight:700;font-size:44px;'
            f'line-height:1;color:var(--blue-500)">{i + 1}</span>'
            f'<div style="font-size:{fs}px;line-height:1.3;color:var(--fg-1)">{keep(esc(line))}</div></div>'
        )
    arrow = ('<span style="flex:none;display:flex;align-items:center;color:var(--fg-4);font-size:34px;'
             'padding:0 2px">→</span>')
    row = arrow.join(cells)
    return f"""
<div class="slide">
  {arc_bg("var(--blue-400)", "left:-215px;bottom:-265px;width:560px;height:560px;opacity:.05")}
  <div class="slide-pad" style="justify-content:center">
    {eyebrow_html(s.get("subtitle"), 16)}
    <h2 class="s-display" style="font-size:{size}px;margin:0 0 40px;max-width:{top_w()}px">{title}</h2>
    <div style="display:flex;gap:{14 if len(items) <= 4 else 8}px;align-items:stretch">{row}</div>
    {note_html(s.get("footnote"), mt=24)}
  </div>
  {foot(page)}
</div>"""


def t_screenshot(s: dict, page: int, cfg: dict) -> str:
    """Скриншот продукта или доказательства. С body — текст слева, кадр справа под окном спикера."""
    title, size = title_of(s, [(20, 52), (30, 44), (999, 36)], top_w())
    sub = esc(s.get("subtitle"))
    shot = img_uri(s["image"], max_h=760, crop=s.get("crop"))
    lines = lines_of(s)
    note = s.get("footnote")
    if lines:
        rows = rows_html(lines, dark=False, size=26 if len(lines) <= 4 else 24, gap=14, default="dot",
                         color="var(--fg-1)")
        return f"""
<div class="slide">
  <div class="slide-pad" style="justify-content:flex-start">
    <div style="min-height:{panel_offset()}px">
      <h2 class="s-display" style="font-size:{size}px;margin:0;max-width:{top_w()}px">{title}</h2>
      {f'<p class="s-lead" style="margin-top:12px;max-width:{top_w()}px;font-size:26px">{sub}</p>' if sub else ''}
    </div>
    <div style="display:flex;gap:40px;align-items:flex-start">
      <div style="flex:1;padding-top:6px">{rows}{note_html(note, mt=22)}</div>
      <div style="flex:none;width:560px;display:flex;justify-content:flex-end">
        <img src="{shot}" alt="{esc(s.get('title'))}" style="max-width:560px;max-height:{panel_max_h() - 44}px;object-fit:contain;border-radius:18px;box-shadow:var(--shadow-md)">
      </div>
    </div>
  </div>
  {foot(page)}
</div>"""
    # без текста слева кадр крупный: контент прижат к верху, иначе центрирование
    # добавляет пустоту сверху и выталкивает картинку на колонтитул
    return f"""
<div class="slide">
  <div class="slide-pad" style="justify-content:flex-start">
    <h2 class="s-display" style="font-size:{size}px;margin:0;max-width:{top_w()}px">{title}</h2>
    {f'<p class="s-lead" style="margin-top:14px;max-width:{top_w()}px;font-size:26px">{sub}</p>' if sub else ''}
    <div style="display:flex;justify-content:center;margin-top:22px">
      <img src="{shot}" alt="{esc(s.get('title'))}" style="max-height:{356 if sub else 396}px;max-width:100%;
      object-fit:contain;border-radius:18px">
    </div>
    {note_html(note, mt=16)}
  </div>
  {foot(page)}
</div>"""


STACK_ROW = re.compile(r"^(.+?)\s*[—–-]\s*([\d\s ]+(?:тыс\.\s*)?₽)\s*$")
TOTAL_RE = re.compile(r"^(вместе|итого|всего|общая|общий)", re.I)


def t_stack(s: dict, page: int, cfg: dict) -> str:
    """Нарастающий список ценности: строки «Название — сумма», итог подсвечен."""
    title, size = title_of(s, [(18, 60), (28, 50), (999, 42)], top_w())
    rows, notes = [], []
    for ln in lines_of(s):
        m = STACK_ROW.match(ln)
        if m:
            rows.append((m.group(1).strip(), m.group(2).strip()))
        else:
            notes.append(ln)
    cells = []
    for name, amount in rows:
        total = bool(TOTAL_RE.match(name))
        border = "border-top:1px solid rgba(255,255,255,.18);margin-top:6px;padding-top:18px" if total else \
            "border-top:1px solid rgba(255,255,255,.08);padding-top:14px"
        ncol = "#fff" if total else "#dfe6f2"
        acol = "var(--citron-400)" if total else "#fff"
        asize = 34 if total else 27
        cells.append(
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;gap:24px;{border}">'
            f'<span style="font-size:{26 if total else 24}px;line-height:1.3;color:{ncol};font-weight:{"600" if total else "400"}">{esc(name)}</span>'
            f'<span style="font-family:var(--font-display);font-weight:700;font-size:{asize}px;'
            f'letter-spacing:-.02em;color:{acol};white-space:nowrap">{esc(amount)}</span></div>'
        )
    notes_html = "".join(
        f'<div style="font-size:22px;line-height:1.35;color:#aeb8cc">{esc(n)}</div>' for n in notes
    )
    return f"""
<div class="slide ink">
  {arc_bg("var(--blue-400)", "right:-230px;bottom:-260px;width:600px;height:600px;opacity:.08")}
  <div class="slide-pad" style="justify-content:center">
    {eyebrow_html(s.get("subtitle"), 16)}
    <h2 class="s-display" style="font-size:{size}px;margin:0 0 30px;max-width:{top_w()}px">{title}</h2>
    <div style="display:flex;flex-direction:column;gap:12px;max-width:780px">{"".join(cells)}</div>
    {f'<div style="display:flex;flex-direction:column;gap:6px;margin-top:26px;max-width:780px">{notes_html}</div>' if notes else ''}
    {note_html(s.get("footnote"), dark=True, mt=20)}
  </div>
  {foot(page, light_text=True)}
</div>"""


def _tariff_card(t: dict) -> str:
    hl = bool(t.get("badge"))
    bg = "background:var(--ink-900);border:0;" if hl else ""
    name_col = "#fff" if hl else "var(--fg-1)"
    text_col = "#dfe6f2" if hl else "var(--fg-2)"
    accent = "var(--citron-400)" if hl else "var(--blue-500)"
    parts = [f'<div class="s-card" style="position:relative;flex:1;display:flex;flex-direction:column;gap:12px;'
             f'padding:30px 26px 26px;{bg}">']
    if hl:
        parts.append('<span style="position:absolute;top:-15px;left:24px;background:var(--citron-400);'
                     'color:var(--ink-900);font-weight:600;font-size:16px;padding:6px 14px;border-radius:999px">'
                     + esc(t["badge"]) + "</span>")
    parts.append(f'<div style="font-family:var(--font-display);font-weight:700;font-size:24px;'
                 f'color:{name_col}">{esc(t.get("name"))}</div>')
    parts.append(f'<div style="font-family:var(--font-display);font-weight:700;font-size:36px;'
                 f'letter-spacing:-.03em;line-height:1;color:{accent}">{esc(t.get("price"))}</div>')
    rows = "".join(
        f'<div style="display:flex;gap:10px;align-items:flex-start;font-size:21px;line-height:1.3;color:{text_col}">'
        f'<span style="color:{accent};flex:none">✓</span><span>{keep(esc(ln))}</span></div>'
        for ln in list_of(t.get("lines") or t.get("body"))
    )
    parts.append(f'<div style="display:flex;flex-direction:column;gap:8px;margin-top:6px">{rows}</div>')
    if t.get("note"):
        ncol = "rgba(223,230,242,.7)" if hl else "var(--fg-4)"
        parts.append(f'<div style="margin-top:auto;padding-top:10px;font-size:17px;line-height:1.3;color:{ncol}">'
                     f'{esc(t["note"])}</div>')
    parts.append("</div>")
    return "".join(parts)


def t_pricing(s: dict, page: int, cfg: dict) -> str:
    """Три тарифа в одну строку; выделенный тариф — тёмная карточка с плашкой."""
    title, size = title_of(s, [(18, 56), (28, 48), (999, 40)], top_w())
    sub = esc(s.get("subtitle"))
    cards = "".join(_tariff_card(t) for t in (s.get("tariffs") or []))
    return f"""
<div class="slide">
  <div class="slide-pad" style="justify-content:flex-start">
    <div style="min-height:{panel_offset()}px">
      <h2 class="s-display" style="font-size:{size}px;margin:0;max-width:{top_w()}px">{title}</h2>
      {f'<p class="s-lead" style="margin-top:12px;max-width:{top_w()}px;font-size:26px">{sub}</p>' if sub else ''}
    </div>
    <div style="display:flex;gap:22px;align-items:stretch;max-height:{panel_max_h()}px">{cards}</div>
    {note_html(s.get("footnote"), mt=16)}
  </div>
  {foot(page)}
</div>"""


TEMPLATES = {
    "title": t_title,
    "agenda": t_agenda,
    "stat": t_stat,
    "comparison": t_comparison,
    "feature": t_feature,
    "case": t_case,
    "author": t_author,
    "statement": t_statement,
    "docs": t_docs,
    "cards": t_cards,
    "steps": t_steps,
    "screenshot": t_screenshot,
    "bullets": t_bullets,
    "closing": t_closing,
    "stack": t_stack,
    "pricing": t_pricing,
}


def guess_type(s: dict, idx: int, total: int) -> str:
    if s.get("slide_type"):
        return s["slide_type"]
    if idx == 1:
        return "title"
    if idx == total:
        return "closing"
    title = str(s.get("title", ""))
    if re.match(r"^[\d\s]+[%₽]?\s+\S", title):
        return "stat"
    if any(re.match(r"^(СТАР|НОВ)", ln) for ln in lines_of(s)):
        return "comparison"
    return "bullets"


def safe_guide_html() -> str:
    return (
        f'<div style="position:absolute;top:0;right:0;width:{SAFE_W}px;height:{SAFE_H}px;'
        'border:2px dashed rgba(224,68,74,.8);background:rgba(224,68,74,.08);'
        'display:flex;align-items:center;justify-content:center;font-family:monospace;'
        'font-size:14px;color:#e0444a;z-index:9">окно спикера</div>'
    )


# ────────────────────────────── сборка HTML ──────────────────────────────

_FONT_CSS: str | None = None


def fonts_dir() -> Path | None:
    return resolve_asset(BRAND, (BRAND.get("fonts") or {}).get("dir", "assets/fonts"))


def font_css() -> str:
    """@font-face с base64-шрифтами из папки fonts.dir бренда; пусто, если fonts.json нет."""
    global _FONT_CSS
    if _FONT_CSS is not None:
        return _FONT_CSS
    folder = fonts_dir()
    manifest = folder / "fonts.json" if folder else None
    if not manifest or not manifest.exists():
        _FONT_CSS = ""
        return _FONT_CSS
    rules = []
    for f in json.loads(manifest.read_text(encoding="utf-8")):
        data = b64encode((folder / f["file"]).read_bytes()).decode()
        rules.append(
            "@font-face{font-family:'%s';font-style:normal;font-weight:%s;font-display:block;"
            "src:url(data:font/woff2;base64,%s) format('woff2');unicode-range:%s}"
            % (f["family"], f["weight"], data, f["unicode_range"])
        )
    _FONT_CSS = "\n".join(rules)
    return _FONT_CSS


def base_css() -> tuple[str, str, str]:
    """Токены и примитивы дизайн-системы. @import Google Fonts из токенов убираем всегда:
    при вшитых шрифтах он не нужен, без них подключаем ссылку из brand.yaml."""
    tokens_css = (DS / "colors_and_type.css").read_text(encoding="utf-8")
    slides_css = (DS / "slides.css").read_text(encoding="utf-8")
    fonts = font_css()
    tokens_css = re.sub(r"@import url\([^)]*fonts\.googleapis[^)]*\);?", "", tokens_css)
    if not fonts:
        url = (BRAND.get("fonts") or {}).get("google_css")
        if url:
            fonts = f"@import url('{url}');"
    tokens_css = tokens_css.replace("</style", "<\\/style")
    slides_css = slides_css.replace("</style", "<\\/style")
    return fonts, tokens_css, slides_css


def overrides_css() -> str:
    """Палитра и шрифты бренда поверх токенов + эфирные поправки кеглей и интерлиньяжа."""
    pal = BRAND.get("palette") or {}
    fnt = BRAND.get("fonts") or {}
    display, sans, mono = fnt.get("display", "Unbounded"), fnt.get("sans", "Onest"), fnt.get("mono", "JetBrains Mono")
    sky, primary, deep = pal.get("sky"), pal.get("primary"), pal.get("deep")
    return f"""
  :root, .slide {{
    --blue-400: {sky}; --brand-sky: {sky}; --blue-500: {primary}; --blue-600: {deep};
    --citron-400: {pal.get("accent")}; --ink-900: {pal.get("ink")}; --ink-700: {pal.get("ink_2")};
    --ink-600: {pal.get("ink_3")}; --paper: {pal.get("paper")}; --bone: {pal.get("bone")};
    --danger: {pal.get("danger")};
    --brand-grad: radial-gradient(120% 140% at 18% 110%, {sky} 0%, {primary} 93%);
    --font-display: '{display}', '{sans}', system-ui, sans-serif;
    --font-sans: '{sans}', system-ui, -apple-system, 'Segoe UI', sans-serif;
    --font-mono: '{mono}', ui-monospace, 'SFMono-Regular', monospace;
  }}
  .slide.blue {{ background: radial-gradient(130% 150% at 85% -20%, {sky} 0%, {primary} 55%, {deep} 100%); }}
  html, body {{ margin: 0; background: #0a0f1c; }}
  .slide .s-eyebrow {{ font-size: 17px; }}
  .slide .s-lead {{ font-size: 26px; }}
  .slide .s-display {{ line-height: 1.1; letter-spacing: -.015em; word-spacing: .08em; }}
  .slide h1.s-display, .slide h2.s-display {{ padding-top: .06em; }}
"""


def preconnect_html(fonts: str) -> str:
    if fonts and not fonts.startswith("@import"):
        return ""
    return ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')


def page_html(slide_html: str) -> str:
    fonts, tokens_css, slides_css = base_css()
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
{preconnect_html(fonts)}
<style>{fonts}</style>
<style>{tokens_css}</style>
<style>{slides_css}</style>
<style>{overrides_css()}</style>
</head><body>{slide_html}</body></html>"""


def deck_html(items: list[tuple[str, str]], notes: list[str], title: str) -> str:
    """Один HTML со всеми слайдами: ←/→ листают, R — в начало, печать даёт PDF."""
    sections = "\n".join(
        f'  <section data-label="{label}">{body}</section>' for label, body in items
    )
    notes_json = json.dumps(notes, ensure_ascii=False)
    # всё внутрь файла: дек должен открываться из любой папки и на чужой машине
    fonts, tokens_css, slides_css = base_css()
    stage_js = (DS / "deck-stage.js").read_text(encoding="utf-8")
    # в комментариях deck-stage.js встречается "</script>" — при инлайне он рвёт тег
    stage_js = stage_js.replace("</script", "<\\/script")
    preconnect = preconnect_html(fonts)
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_mod.escape(title)}</title>
{preconnect}
<style>{fonts}</style>
<style>{tokens_css}</style>
<style>{slides_css}</style>
<style>{overrides_css()}
  deck-stage:not(:defined) {{ visibility: hidden; }}
</style>
</head><body>
<script>
  // рейка миниатюр стартует скрытой — на эфире слева не должно быть ничего лишнего
  try {{ localStorage.setItem('deck-stage.railVisible', '0'); }} catch (e) {{}}
</script>
<deck-stage width="1280" height="720">
{sections}
</deck-stage>
<script type="application/json" id="speaker-notes">{notes_json}</script>
<script>{stage_js}</script>
<script>
  // Компонент прячет рейку за левый край и делает её inert. Возвращаем ей
  // события указателя и выводим обратно, когда курсор у самого края экрана.
  customElements.whenDefined('deck-stage').then(() => {{
    const deck = document.querySelector('deck-stage');
    const root = deck && deck.shadowRoot;
    const rail = root && root.querySelector('.rail');
    if (!rail) return;
    const style = document.createElement('style');
    style.textContent =
      '.rail[data-user-hidden]{{transform:translateX(-100%);' +
      'transition:transform 180ms cubic-bezier(.3,.7,.4,1);z-index:6}}' +
      '.rail[data-user-hidden].peek{{transform:translateX(0);' +
      'box-shadow:0 0 60px rgba(0,0,0,.55)}}';
    root.appendChild(style);
    const unlock = () => {{ if (rail.inert) rail.inert = false; }};
    unlock();
    new MutationObserver(unlock).observe(rail, {{ attributes: true }});
    deck.addEventListener('pointermove', (e) => {{
      const w = rail.getBoundingClientRect().width || 188;
      if (e.clientX <= 28) rail.classList.add('peek');
      else if (e.clientX > w + 24) rail.classList.remove('peek');
    }});
    deck.addEventListener('pointerleave', () => rail.classList.remove('peek'));
  }});
</script>
</body></html>"""


# ────────────────────────────── запуск ──────────────────────────────

KNOWN_FIELDS = {
    "title", "subtitle", "body", "presenter_notes", "slide_type", "footnote", "visual_note",
    "photo", "role", "eyebrow", "image", "crop", "url", "figure", "figure_label", "figure_note",
    "chain", "chain_title", "active", "badge", "left_label", "right_label", "left", "right",
    "tariffs", "documents", "cta",
}


def main() -> None:
    global SAFE_W, SAFE_H, BRAND, YAML_DIR
    ap = argparse.ArgumentParser(description="YAML-сценарий → HTML-дек → PNG → PPTX → PDF → мобильная версия")
    ap.add_argument("yaml_path")
    ap.add_argument("--out", required=True, help="каталог сборки")
    ap.add_argument("--name", default="deck", help="базовое имя файлов: <name>-deck.html, <name>.pptx …")
    ap.add_argument("--only", default="", help="номера слайдов через запятую (1-based)")
    ap.add_argument("--eyebrow", default=None, help="надстрочная метка титула (по умолчанию из brand.yaml)")
    ap.add_argument("--cta", default=None, help="плашка финального слайда (по умолчанию из brand.yaml)")
    ap.add_argument("--deck-title", default="", help="заголовок вкладки HTML-дека")
    ap.add_argument("--speaker-zone", action="store_true",
                    help="оставить пустым правый верхний угол под окно спикера в трансляции")
    ap.add_argument("--safe-w", type=int, default=SPEAKER_W, help="ширина зоны под окно спикера")
    ap.add_argument("--safe-h", type=int, default=SPEAKER_H, help="высота зоны под окно спикера")
    ap.add_argument("--safe-guide", action="store_true", help="подсветить зону спикера на слайдах")
    ap.add_argument("--html-only", action="store_true", help="только HTML, без рендера")
    ap.add_argument("--no-pdf", action="store_true", help="не печатать PDF")
    ap.add_argument("--no-mobile", action="store_true", help="не собирать версию для телефона")
    add_brand_argument(ap)
    args = ap.parse_args()

    yaml_path = Path(args.yaml_path).resolve()
    YAML_DIR = yaml_path.parent
    BRAND = load_brand(args.brand, YAML_DIR)
    print(f"[brand] {BRAND.get('name') or 'без названия'} · {BRAND['_source'] or 'встроенные дефолты'}")

    if args.speaker_zone or args.safe_guide:
        SAFE_W, SAFE_H = args.safe_w, args.safe_h
    cfg = {"eyebrow": args.eyebrow if args.eyebrow is not None else BRAND.get("eyebrow"),
           "cta": args.cta if args.cta is not None else BRAND.get("cta"),
           "safe_guide": args.safe_guide}
    slides = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if isinstance(slides, dict) and "slides" in slides:
        slides = slides["slides"]
    if not isinstance(slides, list) or not slides:
        raise SystemExit("❌ YAML должен быть списком слайдов (или словарём с ключом slides)")
    total = len(slides)
    picked = [int(x) for x in args.only.split(",") if x.strip()] or list(range(1, total + 1))

    if not font_css():
        print("[warn] шрифты не найдены локально — дек будет тянуть их из Google Fonts "
              "(создать кэш: scripts/fetch_fonts.py)")

    out = Path(args.out).resolve()
    # чистим прошлую сборку: иначе слайды от прежнего прогона остаются мусором
    for sub in ("html", "png"):
        d = out / sub
        if d.exists():
            for f in d.glob("*"):
                f.unlink()
        d.mkdir(parents=True, exist_ok=True)

    problems = 0
    jobs = []
    deck_items: list[tuple[str, str]] = []
    deck_notes: list[str] = []
    for page, idx in enumerate(picked, 1):
        s = slides[idx - 1]
        stype = guess_type(s, idx, total)
        if stype not in TEMPLATES:
            raise SystemExit(f"❌ Слайд {idx}: неизвестный slide_type «{stype}». "
                             f"Доступны: {', '.join(TEMPLATES)}")
        unknown = sorted(set(s) - KNOWN_FIELDS)
        if unknown:
            problems += 1
            print(f"  ⚠ слайд {idx}: поля {', '.join(unknown)} шаблон не знает — они не попадут на слайд")
        body = TEMPLATES[stype](s, page, cfg)
        if args.safe_guide:
            body = body.replace('<div class="slide-pad"', safe_guide_html() + '<div class="slide-pad"', 1)
        hp = out / "html" / f"{page:02d}-{stype}.html"
        hp.write_text(page_html(body), encoding="utf-8")
        jobs.append((page, stype, hp, out / "png" / f"{page:02d}-{stype}.png", s.get("presenter_notes", "")))
        deck_items.append((html_mod.escape(str(s.get("title", ""))[:40]), body))
        deck_notes.append(str(s.get("presenter_notes", "")).strip())
        print(f"[html] {page:02d} · {stype:11s} · {str(s.get('title',''))[:44]}")

    deck_title = args.deck_title or " · ".join(
        x for x in (str(slides[0].get("title", "")).strip(), BRAND.get("name")) if x) or args.name
    deck_path = out / f"{args.name}-deck.html"
    deck_path.write_text(deck_html(deck_items, deck_notes, deck_title), encoding="utf-8")
    print(f"[deck] {deck_path}")

    if args.html_only:
        return

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception:
            browser = p.chromium.launch()
        page_obj = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)
        for page, stype, hp, png, _ in jobs:
            page_obj.goto(hp.as_uri())
            page_obj.evaluate("document.fonts.ready")
            page_obj.wait_for_timeout(350)
            page_obj.screenshot(path=str(png), clip={"x": 0, "y": 0, "width": W, "height": H})
            geom = page_obj.evaluate(
                """(safe) => {
                  const slide = document.querySelector('.slide');
                  const pad = document.querySelector('.slide-pad');
                  if (!slide || !pad) return { intrusion: 0, bleed: 0 };
                  const r = slide.getBoundingClientRect();
                  const zoneLeft = r.right - safe.w;
                  const zoneBottom = r.top + safe.h;
                  // Меряем реальные прямоугольники текста и картинок, а не боксы
                  // блочных контейнеров: те растянуты во всю ширину и дают ложные срабатывания.
                  const boxes = [];
                  const walker = document.createTreeWalker(pad, NodeFilter.SHOW_TEXT);
                  let node;
                  while ((node = walker.nextNode())) {
                    if (!node.textContent.trim()) continue;
                    const range = document.createRange();
                    range.selectNodeContents(node);
                    boxes.push(...range.getClientRects());
                  }
                  pad.querySelectorAll('img, .s-card, svg').forEach(el => {
                    if (el.classList.contains('arc-bg') || el.closest('.arc-bg')) return;
                    boxes.push(el.getBoundingClientRect());
                  });
                  let intrusion = 0;
                  let bleed = 0;
                  boxes.forEach(b => {
                    if (!b.width || !b.height) return;
                    if (b.right > zoneLeft && b.top < zoneBottom) {
                      intrusion = Math.max(intrusion, Math.round(b.right - zoneLeft));
                    }
                    bleed = Math.max(bleed,
                      Math.round(b.bottom - (r.bottom - safe.foot)),
                      Math.round(b.right - (r.right - 30)));
                  });
                  return { intrusion, bleed };
                }""",
                {"w": SAFE_W, "h": SAFE_H, "foot": FOOT_H},
            )
            intrusion, bleed = geom["intrusion"], geom["bleed"]
            flag = f"  ⚠ выходит за поля на {bleed}px" if bleed and bleed > 0 else ""
            if SAFE_W and intrusion and intrusion > 0:
                flag += f"  ⛔ заезжает в зону спикера на {intrusion}px"
            if flag:
                problems += 1
            print(f"[png ] {png.name}{flag}")
        browser.close()

    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    for page, stype, hp, png, notes in jobs:
        sl = prs.slides.add_slide(blank)
        sl.shapes.add_picture(str(png), 0, 0, width=prs.slide_width, height=prs.slide_height)
        if notes:
            sl.notes_slide.notes_text_frame.text = str(notes).strip()
    pptx_path = out / f"{args.name}.pptx"
    prs.save(str(pptx_path))
    print(f"[pptx] {pptx_path} · слайдов: {len(jobs)}")

    if not args.no_pdf:
        from print_pdf import print_pdf
        print_pdf(deck_path, out / f"{args.name}.pdf")
    if not args.no_mobile:
        from build_mobile import build_mobile
        build_mobile(out / "png", out / f"{args.name}-mobile.html", deck_title, deck_title)
    print(f"[check] слайдов с замечаниями: {problems}")


if __name__ == "__main__":
    main()
