#!/usr/bin/env bash
# Pull the latest code and restart UEnvision.
# Run on the server:  sudo bash /home/uenvision/uenvision-capstone/deploy/update.sh
set -euo pipefail

APP_DIR=/home/uenvision/uenvision-capstone
as_app() { sudo -u uenvision bash -c "cd '$APP_DIR' && set -a && . ./.env && set +a && $1"; }

echo "==> Backing up the database"
cp "$APP_DIR/db.sqlite3" "$APP_DIR/db.sqlite3.$(date +%Y%m%d-%H%M%S).bak"

echo "==> Pulling the latest code"
as_app "git pull --ff-only"

echo "==> Installing requirements"
as_app "venv/bin/pip install -q -r requirements.txt"

echo "==> Applying database migrations"
as_app "venv/bin/python manage.py migrate --noinput"

echo "==> Collecting static files"
as_app "venv/bin/python manage.py collectstatic --noinput"

echo "==> Restarting the site"
systemctl restart uenvision
systemctl --no-pager --lines=5 status uenvision
echo "Done."
