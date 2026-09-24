# Установка Презентатора

Пока репозиторий приватный, для клонирования и установки плагина Claude Code нужен доступ к `nickonai/slides-agent` в GitHub. Ссылка сама по себе доступа не даёт. Перед передачей другому человеку выдайте ему доступ к репозиторию; не пересылайте свой токен или пароль.

Генератор требует Python 3.10+, пакеты `python-pptx`, `pyyaml`, `playwright`, `pillow` и Chrome или Chromium. `setup.sh` / `setup.ps1` создаёт отдельное окружение `~/.slides-agent/venv` и устанавливает Chromium. Для установки нужен интернет; системный Python скрипт не изменяет.

## macOS и Linux

Сначала обеспечьте доступ к приватному репозиторию через вашу обычную авторизацию GitHub. Затем:

```bash
git clone https://github.com/nickonai/slides-agent.git
cd slides-agent
bash skills/slides/scripts/setup.sh
```

Если Python 3.10+ не установлен, поставьте `uv` по [официальной инструкции](https://docs.astral.sh/uv/getting-started/installation/) и повторите запуск `setup.sh`.

В Codex откройте папку `slides-agent` и напишите «Сделай презентацию про …». Для Claude Code можно открыть этот же клон: `CLAUDE.md` указывает на общие правила. Чтобы использовать навык из любой рабочей папки, установите плагин:

```bash
claude plugin marketplace add nickonai/slides-agent
claude plugin install slides-agent@slides-agent
```

При установке плагина Claude Code нужен настроенный доступ к приватному GitHub-репозиторию. В любой папке проекта после этого можно попросить «Сделай презентацию про …» или вызвать `/slides`.

## Windows PowerShell

Установите Git и `uv`, если их ещё нет:

```powershell
winget install --id=Git.Git
winget install --id=astral-sh.uv
```

Откройте новое окно PowerShell и выполните:

```powershell
git clone https://github.com/nickonai/slides-agent.git
cd slides-agent
powershell -ExecutionPolicy Bypass -File skills\slides\scripts\setup.ps1
```

Python окружения: `%USERPROFILE%\.slides-agent\venv\Scripts\python.exe`. Дальше работа в Codex и установка плагина Claude Code такие же, как на macOS.

## ChatGPT

В клоне репозитория создайте пакет:

```bash
python3 scripts/package_skill.py
```

Загрузите `dist/slides-skill.zip` в ChatGPT: Plugins → Skills → Create → Upload from your computer. Доступность этой функции зависит от типа аккаунта и настроек рабочего пространства. Пакет не публикует навык другим людям автоматически. Чтобы передать навык, загрузите ZIP в их рабочем пространстве или используйте доступные там средства общего доступа.

Попросите: «Используй навык slides и сделай презентацию про …». Для сборки всех форматов среда ChatGPT должна позволять запуск Python, установку пакетов и браузера. Если это недоступно, навык соберёт самодостаточный HTML-дек в режиме `--html-only` и сообщит, какие форматы не получились. Возможности конкретного сеанса нужно проверить на нём самом.

## Проверка установки

Из корня клона:

```bash
~/.slides-agent/venv/bin/python skills/slides/scripts/build_deck.py \
  examples/ai-agent-vs-chatbot/slides.yaml \
  --out /tmp/slides-agent-demo --name demo
```

Ожидаются `demo-deck.html`, `demo.pptx`, `demo.pdf`, `demo-mobile.html` и строка `[check] слайдов с замечаниями: 0`. Посмотрите каждый PNG в `/tmp/slides-agent-demo/png/`: автоматическая проверка не заменяет визуальную.

На Windows замените путь к Python на `%USERPROFILE%\.slides-agent\venv\Scripts\python.exe` и выходную папку на удобный локальный путь.

## Настройка бренда

Скопируйте `skills/slides/brand.example.yaml` в `brand.yaml` в рабочем проекте. В нём задаются знак, цвета, шрифты, название и текст финального слайда. Свой файл рядом со сценарием имеет приоритет перед пресетом Универус. Храните исходные материалы и готовые презентации в `presentations/<slug>/`.
