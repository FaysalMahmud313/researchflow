#!/usr/bin/env bash
# Assemble the ready-to-run copy of ResearchFlow (what the Publish workflow puts on the
# "deploy" branch). Build the web app first: cd frontend && npm ci && npm run build
#   bash deploy/build_bundle.sh <output-folder>
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:?Usage: bash deploy/build_bundle.sh <output-folder>}"

if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  echo "frontend/dist is missing. Build the web app first: cd frontend && npm ci && npm run build" >&2
  exit 1
fi
if [ -e "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null)" ]; then
  echo "$OUT is not empty." >&2
  exit 1
fi

mkdir -p "$OUT"
cp -r "$ROOT/backend/app" "$ROOT/backend/scripts" "$ROOT/backend/wsgi.py" "$OUT/"
# uvicorn is not needed under a WSGI host; leaving it out saves disk space there.
grep -v '^uvicorn' "$ROOT/backend/requirements.txt" > "$OUT/requirements.txt"
cp -r "$ROOT/frontend/dist" "$OUT/web"
for f in setup.sh update.sh backup.sh README.md; do
  cp "$ROOT/deploy/pythonanywhere/$f" "$OUT/"
done
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} +
echo "Bundle ready in $OUT"
