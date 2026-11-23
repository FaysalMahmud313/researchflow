#!/usr/bin/env bash
# Make one backup file of the database and uploaded files, to download from the Files tab.
#   bash ~/researchflow/backup.sh
# It replaces the previous backup (disk space is tight), so download it each time.
set -euo pipefail

DATA="$HOME/researchflow-data"
OUT="$HOME/researchflow-backup.tar.gz"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

[ -f "$DATA/researchflow.sqlite3" ] || { echo "No database yet."; exit 0; }
# A consistent copy, safe while the site is running.
"$HOME/.virtualenvs/researchflow/bin/python" - "$DATA/researchflow.sqlite3" "$WORK/researchflow.sqlite3" <<'PY'
import sqlite3
import sys

src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close()
src.close()
PY
(cd "$HOME" && tar -czf "$(basename "$OUT")" -C "$WORK" researchflow.sqlite3 -C "$DATA" uploads)
echo "Backup written: $OUT ($(du -h "$OUT" | cut -f1)). Download it from the Files tab."
