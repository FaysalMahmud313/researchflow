#!/usr/bin/env bash
# =============================================================================
# One-time setup of ResearchFlow on PythonAnywhere (free account, no card).
#
# Before running: on the Web tab choose "Add a new web app" > "Manual configuration"
# > Python 3.13. Then, in a Bash console:
#
#   bash ~/researchflow/setup.sh            # uses Python 3.13
#   bash ~/researchflow/setup.sh 3.12       # if you picked another version on the Web tab
#
# Safe to run again: it keeps your settings, secrets and data.
# =============================================================================
set -euo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYV="${1:-3.13}"
NAME="$(echo "$USER" | tr '[:upper:]' '[:lower:]')"
DATA="$HOME/researchflow-data"
ENV_FILE="$HOME/researchflow.env"
VENV="$HOME/.virtualenvs/researchflow"

# The web app's domain and WSGI file (US accounts, then EU accounts).
DOMAIN=""
WSGI_FILE=""
for candidate in "$NAME.pythonanywhere.com" "$NAME.eu.pythonanywhere.com"; do
  file="${RF_WWW_DIR:-/var/www}/${candidate//./_}_wsgi.py"
  if [ -f "$file" ]; then
    DOMAIN="$candidate"
    WSGI_FILE="$file"
    break
  fi
done
if [ -z "$WSGI_FILE" ]; then
  echo "No web app found yet." >&2
  echo "Open the Web tab, click 'Add a new web app', choose 'Manual configuration' and Python $PYV, then run this again." >&2
  exit 1
fi
if ! command -v "python$PYV" >/dev/null 2>&1; then
  echo "python$PYV is not installed here. Run again with a version this account has (3.11 or newer), e.g.: bash setup.sh 3.12" >&2
  exit 1
fi

echo "== Python packages (python$PYV)"
if [ -x "$VENV/bin/python" ] && [ "$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])')" != "$PYV" ]; then
  rm -rf "$VENV"   # built for another Python version; it must match the web app
fi
if [ ! -x "$VENV/bin/python" ]; then
  mkdir -p "$(dirname "$VENV")"
  "python$PYV" -m venv "$VENV"
fi
"$VENV/bin/pip" install --disable-pip-version-check --no-cache-dir -q -r "$APP/requirements.txt"

echo "== Data folder and settings"
mkdir -p "$DATA/uploads"
chmod 700 "$DATA"
if [ ! -f "$ENV_FILE" ]; then
  secret() { "$VENV/bin/python" -c "import secrets; print(secrets.token_urlsafe(48))"; }
  cat > "$ENV_FILE" <<EOF
# ResearchFlow settings on PythonAnywhere (created by setup.sh). Keep private.
APP_ENV=production
DEBUG=false
FRONTEND_ORIGIN=https://$DOMAIN
BACKEND_ORIGIN=https://$DOMAIN
SESSION_COOKIE_SECURE=true
# PythonAnywhere's proxy passes the visitor's address; needed for login rate limits.
TRUST_PROXY_HEADERS=true

DATABASE_PATH=$DATA/researchflow.sqlite3
# The home folder is a network disk, where SQLite's WAL mode is not reliable.
SQLITE_JOURNAL_MODE=DELETE
PRIVATE_STORAGE_DIR=$DATA/uploads
# Free accounts have 512 MB in total, so keep files small.
MAX_UPLOAD_SIZE_BYTES=26214400
PROJECT_STORAGE_QUOTA_BYTES=104857600

SESSION_SECRET_KEY=$(secret)
CSRF_SECRET_KEY=$(secret)
TOKEN_HASH_PEPPER=$(secret)

# Email. "console" sends nothing: people still register and sign in, and you reset
# passwords with scripts/admin.py. Free accounts can only reach an allowlist of sites,
# so SMTP may not be reachable from here.
EMAIL_BACKEND=console
# Optional: only these email domains may sign up, e.g. ALLOWED_EMAIL_DOMAINS=uni.edu
# ALLOWED_EMAIL_DOMAINS=
DOI_LOOKUP_ENABLED=false
EOF
  chmod 600 "$ENV_FILE"
fi

echo "== Web app start file"
[ -f "$WSGI_FILE.original" ] || cp "$WSGI_FILE" "$WSGI_FILE.original"
cat > "$WSGI_FILE" <<EOF
# ResearchFlow (written by setup.sh). Settings: $ENV_FILE
import sys

sys.path.insert(0, "$APP")
from wsgi import application  # noqa: E402,F401
EOF

echo
echo "============================================================================"
echo " Almost done. On the Web tab:"
echo "   1. Virtualenv:   $VENV"
echo "   2. Force HTTPS:  Enabled"
echo "   3. Click the green Reload button"
echo
echo " Then open https://$DOMAIN and create your account."
echo " Once a month, click 'Run until 1 month from today' on the Web tab to keep it online."
echo "============================================================================"
