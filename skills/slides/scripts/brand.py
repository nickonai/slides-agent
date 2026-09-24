#!/usr/bin/env python3
"""
Загрузчик бренд-конфигурации презентаций.

Весь фирменный стиль дека — название, слово-логотип в колонтитуле, знак,
фоновый мотив, палитра, шрифты, текст плашки на финальном слайде, надстрочная
метка титула — живёт в brand.yaml, а не в коде генератора.

Порядок поиска (первый найденный выигрывает):

1. путь, переданный явно (флаг --brand);
2. brand.yaml в папке YAML-сценария или выше по дереву до папки с .git;
3. путь из переменной окружения SLIDES_BRAND;
4. brand.yaml в корне скилла (skills/slides/brand.yaml);
5. пресет presets/univerus/brand.yaml — бренд по умолчанию.

Найденный файл накладывается поверх встроенных дефолтов рекурсивно:
в brand.yaml достаточно перечислить только то, что отличается.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_PRESET = SKILL_DIR / "presets" / "univerus" / "brand.yaml"

ENV_VAR = "SLIDES_BRAND"
CONFIG_NAME = "brand.yaml"

# Встроенные значения. Палитра и шрифты — те, на которые рассчитана вёрстка
# шаблонов; название и сайт пустые, чтобы чужой бренд не утёк в дек.
DEFAULT_BRAND: dict = {
    "name": "",
    # Слово рядом со знаком в колонтитуле и на титульном слайде.
    "wordmark": "",
    "site": "",
    # Текст плашки на слайде closing, если в самом слайде нет поля cta.
    "cta": "",
    # Надстрочная метка титульного слайда, если в слайде нет поля eyebrow.
    "eyebrow": "Презентация",
    "logo": {
        # Одноцветный SVG-знак. Лучше всего с fill="currentColor":
        # тогда генератор перекрашивает его под светлый и тёмный фон.
        "mark": "",
    },
    # Фоновый мотив: тот же знак, крупно и почти прозрачно, уведён за край.
    "motif": True,
    "palette": {
        "primary": "#3785e2",  # основной цвет: номера, точки, акценты на светлом
        "sky": "#4ba7f9",      # светлый акцент: знак, мотив, градиент финала
        "deep": "#2a6fc4",     # тёмный край градиента финального слайда
        "accent": "#d0ea50",   # кислотный акцент: плашки и метки на тёмном
        "ink": "#080d18",      # фон тёмных слайдов
        "ink_2": "#131b2e",    # карточки на тёмном
        "ink_3": "#1c273f",    # шапка макета браузера
        "paper": "#f5f2eb",    # фон светлых слайдов
        "bone": "#faf8f3",     # фон слайда-кейса
        "danger": "#e0444a",   # значок ✕
    },
    "fonts": {
        # Папка с fonts.json и woff2-файлами. Относительный путь — от папки
        # brand.yaml, затем от корня скилла.
        "dir": "assets/fonts",
        "display": "Unbounded",
        "sans": "Onest",
        "mono": "JetBrains Mono",
        # Запасной источник, если папка шрифтов пуста: дек потянет шрифты из сети.
        "google_css": (
            "https://fonts.googleapis.com/css2?family=Unbounded:wght@300..900"
            "&family=Onest:wght@300..800&family=JetBrains+Mono:wght@400..700&display=swap"
        ),
    },
    "case": {
        "eyebrow": "Кейс",
        "role": "участник программы",
        "disclaimer": "Это результат конкретного человека, а не обещание вашего результата.",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def find_brand_file(explicit: str | Path | None = None,
                    project_dir: Path | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"❌ Бренд-конфигурация не найдена: {path}")
        return path

    if project_dir:
        current = Path(project_dir).resolve()
        for directory in [current, *current.parents]:
            candidate = directory / CONFIG_NAME
            if candidate.exists():
                return candidate
            if (directory / ".git").exists():
                break

    env_value = os.environ.get(ENV_VAR)
    if env_value:
        path = Path(env_value).expanduser()
        if not path.exists():
            raise SystemExit(f"❌ {ENV_VAR} указывает на несуществующий файл: {path}")
        return path.resolve()

    skill_config = SKILL_DIR / CONFIG_NAME
    if skill_config.exists():
        return skill_config.resolve()

    return DEFAULT_PRESET if DEFAULT_PRESET.exists() else None


def load_brand(explicit: str | Path | None = None,
               project_dir: Path | None = None) -> dict:
    """Итоговая конфигурация + служебные ключи _source и _base_dir."""
    brand_file = find_brand_file(explicit, project_dir)
    if brand_file is None:
        brand = _deep_merge(DEFAULT_BRAND, {})
        brand["_source"] = None
        brand["_base_dir"] = SKILL_DIR
        return brand

    import yaml

    raw = yaml.safe_load(brand_file.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise SystemExit(f"❌ {brand_file} должен быть YAML-словарём")
    brand = _deep_merge(DEFAULT_BRAND, raw)
    brand["_source"] = brand_file
    brand["_base_dir"] = brand_file.parent
    return brand


def resolve_asset(brand: dict, relative: str) -> Path | None:
    """Файл ассета: абсолютный путь, иначе рядом с brand.yaml, иначе от корня скилла."""
    if not relative:
        return None
    path = Path(relative).expanduser()
    if path.is_absolute():
        return path if path.exists() else None
    for base in (brand.get("_base_dir", SKILL_DIR), SKILL_DIR):
        candidate = Path(base) / path
        if candidate.exists():
            return candidate
    return None


def mark_svg_parts(brand: dict) -> tuple[str, str] | None:
    """(viewBox, внутренности) знака из SVG-файла или None, если знака нет."""
    path = resolve_asset(brand, (brand.get("logo") or {}).get("mark", ""))
    if not path:
        return None
    text = path.read_text(encoding="utf-8")
    m = re.search(r"<svg\b([^>]*)>(.*)</svg>", text, re.S)
    if not m:
        return None
    vb = re.search(r'viewBox="([^"]+)"', m.group(1))
    return (vb.group(1) if vb else "0 0 200 200"), m.group(2).strip()


def add_brand_argument(parser) -> None:
    parser.add_argument(
        "--brand",
        help=("Путь к brand.yaml. По умолчанию ищется рядом со сценарием и выше, "
              f"затем в ${ENV_VAR}, затем пресет Универус."),
    )
