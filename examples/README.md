# Примеры

**[ai-agent-vs-chatbot](ai-agent-vs-chatbot/)** — «ИИ-агент и чат-бот»:
11 слайдов, десять разных типов (`title`, `agenda`, `statement`, `bullets`,
`comparison`, `stat`, `steps`, `feature` с цепочкой, `cards`, `closing`).
Тема нейтральная: без людей, цен и цифр, которым нужен источник.

| Файл | Что это |
|---|---|
| `slides.yaml` | сценарий — видно, как поля превращаются в слайды |
| `ai-agent-vs-chatbot-deck.html` | готовый дек: откройте двойным кликом, листайте ←/→ |
| `../preview.png` | превью в корневом README: слайды 1, 5, 7, 8 |

PNG, PPTX, PDF и мобильная версия в git не лежат — они пересобираются:

```bash
~/.slides-agent/venv/bin/python skills/slides/scripts/build_deck.py \
    examples/ai-agent-vs-chatbot/slides.yaml \
    --out examples/ai-agent-vs-chatbot --name ai-agent-vs-chatbot
```

Превью:

```bash
P=examples/ai-agent-vs-chatbot/png
~/.slides-agent/venv/bin/python skills/slides/scripts/preview.py \
    $P/01-title.png $P/05-comparison.png $P/07-steps.png $P/08-feature.png \
    -o examples/preview.png
```

Собран с брендом по умолчанию — пресетом `presets/univerus`.
