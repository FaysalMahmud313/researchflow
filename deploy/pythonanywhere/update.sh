#!/usr/bin/env bash
# Update ResearchFlow on PythonAnywhere to the newest published build and restart it.
#   bash ~/researchflow/update.sh
# Database changes are applied automatically when the app starts; your data is kept.
set -euo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="$(echo "$USER" | tr '[:upper:]' '[:lower:]')"
VENV="$HOME/.virtualenvs/researchflow"

git -C "$APP" pull --ff-only
"$VENV/bin/pip" install --disable-pip-version-check --no-cache-dir -q -r "$APP/requirements.txt"

# Touching the web app's start file makes PythonAnywhere reload it.
for candidate in "$NAME.pythonanywhere.com" "$NAME.eu.pythonanywhere.com"; do
  file="${RF_WWW_DIR:-/var/www}/${candidate//./_}_wsgi.py"
  if [ -f "$file" ]; then
    touch "$file"
    echo "Updated and reloaded: https://$candidate"
    exit 0
  fi
done
echo "Updated. Now click Reload on the Web tab." >&2
