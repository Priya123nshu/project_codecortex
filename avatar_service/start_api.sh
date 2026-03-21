#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv-avatar}"
HOST="${API_HOST:-0.0.0.0}"
PORT="${API_PORT:-8000}"

if [ -f "$VENV_DIR/bin/activate" ]; then
  # shellcheck disable=SC1090
  source "$VENV_DIR/bin/activate"
fi

export PYTHONPATH="${PYTHONPATH:-$PROJECT_ROOT}"
exec uvicorn avatar_service.api:app --host "$HOST" --port "$PORT"