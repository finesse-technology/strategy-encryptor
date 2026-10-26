#!/usr/bin/env bash
# Launch the Strategy Encryptor GUI using the project's .venv (Linux / macOS).
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"

if [ ! -x "$PY" ]; then
    echo "[ERROR] .venv not found at $ROOT/.venv"
    echo
    echo "Create it first:"
    echo "    python3 -m venv .venv"
    echo "    .venv/bin/python -m pip install -r requirements.txt"
    echo
    exit 1
fi

exec "$PY" "$ROOT/gui.py"
