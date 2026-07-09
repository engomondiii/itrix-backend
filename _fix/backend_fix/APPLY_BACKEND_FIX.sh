#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# itriX backend fix applier  (v4.0.1 — hang-proof qualify)
#
# Run FROM THE itrix-backend ROOT (the directory that contains manage.py):
#
#     cd /path/to/itrix-backend
#     unzip -o itrix-backend-fix.zip -d _fix
#     bash _fix/backend_fix/APPLY_BACKEND_FIX.sh
#
# Backs up each overwritten file (…​.bak-YYYYmmddHHMMSS) then copies the fixed files
# into their exact locations. Idempotent + safe to re-run.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_ROOT="$(pwd)"
if [[ ! -f "$DEST_ROOT/manage.py" ]]; then
  echo "ERROR: run this from the itrix-backend root (the folder with manage.py)." >&2
  echo "       current dir: $DEST_ROOT" >&2
  exit 1
fi
STAMP="$(date +%Y%m%d%H%M%S)"
FILES=(
  "apps/review/services/qualification_processor.py"
  "apps/leads/services/lead_summary_generator.py"
  "apps/ai_engine/services/claude_client.py"
  "apps/ai_engine/services/pinecone_client.py"
  "apps/knowledge_core/services/embedder.py"
  "itrix/settings/base.py"
)
echo "itriX backend fix (v4.0.1) → applying ${#FILES[@]} file(s) into: $DEST_ROOT"
for rel in "${FILES[@]}"; do
  src="$SRC_DIR/$rel"; dest="$DEST_ROOT/$rel"
  if [[ ! -f "$src" ]]; then echo "  ! missing payload: $rel (skipped)" >&2; continue; fi
  mkdir -p "$(dirname "$dest")"
  if [[ -f "$dest" ]]; then cp -p "$dest" "$dest.bak-$STAMP"; echo "  • backed up  $rel"; fi
  cp -f "$src" "$dest"; echo "  ✓ applied    $rel"
done
echo
echo "Done. Restart the backend (gunicorn/daphne) to pick up the change."
echo "Optional but recommended: raise the gunicorn timeout in the Procfile from 120 to 180"
echo "as an extra safety margin (the fix already keeps qualify well under a second)."
