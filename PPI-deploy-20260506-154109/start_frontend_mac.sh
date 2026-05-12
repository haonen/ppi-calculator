#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/base-extension"

export PPI_FRONTEND_HOST="${PPI_FRONTEND_HOST:-0.0.0.0}"
export PPI_FRONTEND_PORT="${PPI_FRONTEND_PORT:-5173}"

python3 static_server.py
