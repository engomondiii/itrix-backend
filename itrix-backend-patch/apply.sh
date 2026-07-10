#!/usr/bin/env bash
#
# itriX BACKEND patch installer (v4.0.3 — realtime chat + live client-page generation)
#
# Run this from the ROOT of the itrix-backend repo (the folder containing manage.py):
#
#     bash apply.sh
#
set -euo pipefail

REPO_ROOT="$(pwd)"

if [[ ! -f "$REPO_ROOT/manage.py" || ! -d "$REPO_ROOT/apps" ]]; then
  echo "✗ This does not look like the itrix-backend root (no manage.py / apps/)."
  echo "  cd into the backend repo root and run:  bash apply.sh"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/files"
if [[ ! -d "$SRC" ]]; then
  echo "✗ Patch payload not found ($SRC). Unzip the patch here first."
  exit 1
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$REPO_ROOT/.patch-backup-$STAMP"
echo "→ Backing up any files this patch will overwrite into ./.patch-backup-$STAMP/"

while IFS= read -r abs; do
  rel="${abs#"$SRC"/}"
  dest="$REPO_ROOT/$rel"
  if [[ -f "$dest" ]]; then
    mkdir -p "$BACKUP/$(dirname "$rel")"
    cp "$dest" "$BACKUP/$rel"
  fi
  mkdir -p "$(dirname "$dest")"
  cp "$abs" "$dest"
  echo "  ✓ $rel"
done < <(find "$SRC" -type f)

find "$REPO_ROOT/apps/realtime" "$REPO_ROOT/apps/agents" "$REPO_ROOT/apps/ai_engine" "$REPO_ROOT/apps/conversations" \
  -name '*.pyc' -delete 2>/dev/null || true
find "$REPO_ROOT/apps/realtime" "$REPO_ROOT/apps/agents" "$REPO_ROOT/apps/ai_engine" "$REPO_ROOT/apps/conversations" \
  -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# Keep the safety backup out of git.
if [[ -f "$REPO_ROOT/.gitignore" ]] && ! grep -q '.patch-backup-' "$REPO_ROOT/.gitignore" 2>/dev/null; then
  printf '\n# itriX patch safety backups\n.patch-backup-*/\n' >> "$REPO_ROOT/.gitignore"
fi

echo "→ Cleaning up the patch files (they won't be committed)…"
rm -rf "$SRC"
find "$REPO_ROOT" -maxdepth 1 -type f -name 'itrix-backend-patch*.zip' -delete 2>/dev/null || true
rm -f "$SCRIPT_DIR/apply.sh"
rmdir "$SCRIPT_DIR" 2>/dev/null || true

cat <<'DONE'

✓ Backend patch applied.

WHAT CHANGED
  • Procfile now runs Daphne (ASGI) as the web process → one process serves BOTH
    HTTP and WebSocket. (gunicorn/WSGI cannot serve /ws/* — that was the 404 source.)
  • ws/client-page/{token}/ route added (the frontend's socket URL) + a streaming
    ClientPageConsumer.
  • WS auth middleware now understands the browser's single "itrix.bearer.<token>"
    subprotocol and echoes it back so the handshake completes.
  • Claude client gained stream(); the Concierge gained stream_reply() → chat replies
    stream token-by-token, and the client page streams its "what we heard" narrative live.
  • fan_out now emits frontend-shaped {type,payload} camelCase events.

NEXT STEPS (on Railway, backend service)
  1. Commit & push:   git add -A && git commit -m "realtime chat + live client-page streaming" && git push
  2. Ensure a Redis service is attached and REDIS_URL is set (ENABLE_REALTIME=True uses it).
  3. Railway will use the Procfile web: (Daphne). No Start Command override should force gunicorn.
  4. Redeploy. The review/client-page sockets now upgrade instead of 404-ing.

A timestamped backup of every overwritten file is in ./.patch-backup-*/  (safe to delete).
DONE
