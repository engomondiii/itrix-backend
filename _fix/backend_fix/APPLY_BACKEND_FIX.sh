#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# itriX backend fix applier
#
# Place this zip's contents (this script + the apps/ tree) anywhere, then run this
# script FROM THE itrix-backend ROOT (the directory that contains manage.py):
#
#     cd /path/to/itrix-backend
#     unzip -o itrix-backend-fix.zip -d _fix
#     bash _fix/APPLY_BACKEND_FIX.sh
#
# It backs up each target file it will overwrite (…​.bak-YYYYmmddHHMMSS) and then
# copies the fixed files into their exact locations. Idempotent + safe to re-run.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# Resolve the directory this script lives in (the unzipped payload root).
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The itrix-backend root = current working directory; sanity-check it.
DEST_ROOT="$(pwd)"
if [[ ! -f "$DEST_ROOT/manage.py" ]]; then
  echo "ERROR: run this from the itrix-backend root (the folder with manage.py)." >&2
  echo "       current dir: $DEST_ROOT" >&2
  exit 1
fi

STAMP="$(date +%Y%m%d%H%M%S)"

# List of files shipped in this fix (relative paths from the backend root).
FILES=(
  "apps/review/services/qualification_processor.py"
)

echo "itriX backend fix → applying ${#FILES[@]} file(s) into: $DEST_ROOT"
for rel in "${FILES[@]}"; do
  src="$SRC_DIR/$rel"
  dest="$DEST_ROOT/$rel"
  if [[ ! -f "$src" ]]; then
    echo "  ! missing payload file: $rel (skipped)" >&2
    continue
  fi
  mkdir -p "$(dirname "$dest")"
  if [[ -f "$dest" ]]; then
    cp -p "$dest" "$dest.bak-$STAMP"
    echo "  • backed up  $rel  →  $rel.bak-$STAMP"
  fi
  cp -f "$src" "$dest"
  echo "  ✓ applied    $rel"
done

echo "Done. Restart the backend (gunicorn/daphne) to pick up the change."
