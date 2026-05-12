#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export PPI_BACKEND_HOST="${PPI_BACKEND_HOST:-127.0.0.1}"
export PPI_BACKEND_PORT="${PPI_BACKEND_PORT:-8000}"

exec .venv/bin/python backend_server.py
