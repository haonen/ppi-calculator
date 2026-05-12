#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

export PPI_BACKEND_HOST="${PPI_BACKEND_HOST:-0.0.0.0}"
export PPI_BACKEND_PORT="${PPI_BACKEND_PORT:-8000}"

python backend_server.py
