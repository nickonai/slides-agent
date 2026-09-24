# Шрифты

Шрифты вшиваются в HTML-дек как base64 — поэтому дек открывается без
интернета и выглядит одинаково на любой машине. Список файлов и
unicode-диапазонов — `fonts.json`.

| Семейство | Роль | Лицензия |
|---|---|---|
| Unbounded | заголовки | SIL Open Font License 1.1, `unbounded/OFL.txt` |
| Onest | основной текст | SIL Open Font License 1.1, `onest/OFL.txt` |
| JetBrains Mono | надстрочные метки, номера | SIL Open Font License 1.1, `jetbrains-mono/OFL.txt` |

Вшивать и распространять вместе с плагином можно, продавать шрифты отдельно
нельзя. Файлы — подмножества cyrillic и latin с Google Fonts, обновляются
`scripts/fetch_fonts.py`.

Свои шрифты: `fetch_fonts.py --dir <папка> --css "<ссылка css2 Google Fonts>"`,
положите рядом OFL.txt, укажите папку и имена семейств в `brand.yaml`.
