#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" != "0" ]]; then
  echo "Please run as root on the server."
  exit 1
fi

DEPLOY_SRC="${1:-/tmp/multi-plugin-deploy}"
APP_DIR="${2:-/opt/ppi}"

if [[ ! -d "$DEPLOY_SRC" ]]; then
  echo "Deploy source not found: $DEPLOY_SRC"
  exit 1
fi

if [[ ! -d "$APP_DIR" ]]; then
  echo "App directory not found: $APP_DIR"
  exit 1
fi

mkdir -p "$APP_DIR/env"

for category in skin hair makeup; do
  if [[ ! -f "$APP_DIR/env/ppi-${category}.env" ]]; then
    cp "$DEPLOY_SRC/backend/env/ppi-${category}.env.example" "$APP_DIR/env/ppi-${category}.env"
    echo "Created $APP_DIR/env/ppi-${category}.env. Please edit its token before production use."
  fi
  cp "$DEPLOY_SRC/backend/systemd/ppi-backend-${category}.service" /etc/systemd/system/
done

cp "$DEPLOY_SRC/backend/nginx/ppi-multi-plugin-nginx.conf" /etc/nginx/sites-available/ppi-multi-plugin
ln -sf /etc/nginx/sites-available/ppi-multi-plugin /etc/nginx/sites-enabled/ppi-multi-plugin
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload
systemctl enable ppi-backend-skin ppi-backend-hair ppi-backend-makeup
systemctl restart ppi-backend-skin ppi-backend-hair ppi-backend-makeup

nginx -t
systemctl reload nginx

systemctl status ppi-backend-skin --no-pager
systemctl status ppi-backend-hair --no-pager
systemctl status ppi-backend-makeup --no-pager
