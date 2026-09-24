#!/usr/bin/env bash
# Окружение Презентатора: Python-зависимости и браузер для рендера слайдов.
#
#   bash skills/slides/scripts/setup.sh
#
# Ставит venv в ~/.slides-agent/venv (путь меняется переменной
# SLIDES_AGENT_HOME) — вне папки плагина, чтобы переживать его обновления.
# Повторный запуск безопасен: обновит пакеты и докачает браузер, если его нет.
set -euo pipefail

HOME_DIR="${SLIDES_AGENT_HOME:-$HOME/.slides-agent}"
VENV="$HOME_DIR/venv"
PKGS="python-pptx pyyaml playwright pillow"

mkdir -p "$HOME_DIR"

if command -v uv >/dev/null 2>&1; then
  echo "[setup] uv найден — создаю окружение через uv"
  [ -x "$VENV/bin/python" ] || uv venv --python 3.12 "$VENV" || uv venv "$VENV"
  uv pip install --python "$VENV/bin/python" $PKGS
else
  PY=""
  for cand in python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
      PY="$cand"; break
    fi
  done
  if [ -z "$PY" ]; then
    echo "[setup] Нужен Python 3.10+ или uv. macOS: brew install uv. Linux: https://docs.astral.sh/uv/" >&2
    exit 1
  fi
  echo "[setup] создаю окружение: $PY -m venv $VENV"
  [ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
  "$VENV/bin/python" -m pip install $PKGS
fi

echo "[setup] ставлю браузер Chromium для рендера слайдов"
"$VENV/bin/python" -m playwright install chromium

echo
echo "[ok] Готово. Python Презентатора: $VENV/bin/python"
