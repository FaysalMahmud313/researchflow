#!/usr/bin/env bash
# Runs on the server as the "deploy" user after GitHub Actions has uploaded a release
# (backend code to /opt/researchflow/backend, built web app to /opt/researchflow/web.new).
# Database migrations run automatically when the API starts.
set -euo pipefail

APP=/opt/researchflow

echo "== Python packages"
if [ ! -x "$APP/venv/bin/python" ]; then
  python3 -m venv "$APP/venv"
fi
"$APP/venv/bin/pip" install --disable-pip-version-check -q -r "$APP/backend/requirements.txt"

echo "== Web app"
rm -rf "$APP/web.old"
if [ -d "$APP/web" ]; then
  mv "$APP/web" "$APP/web.old"
fi
mv "$APP/web.new" "$APP/web"
rm -rf "$APP/web.old"

echo "== Restart API"
sudo /usr/bin/systemctl restart researchflow
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
    echo "ResearchFlow is up."
    exit 0
  fi
  sleep 1
done
echo "The API did not start. On the server run: sudo journalctl -u researchflow -n 50" >&2
exit 1
