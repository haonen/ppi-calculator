#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export PPI_PUBLIC_PROXY_HOST="${PPI_PUBLIC_PROXY_HOST:-127.0.0.1}"
export PPI_PUBLIC_PROXY_PORT="${PPI_PUBLIC_PROXY_PORT:-9000}"
export PPI_PUBLIC_PROXY_BACKEND="${PPI_PUBLIC_PROXY_BACKEND:-http://127.0.0.1:8000}"

exec .venv/bin/python unified_ngrok_proxy.py
