#!/usr/bin/env sh
# ─────────────────────────────────────────────────────────────────────────────
# itriX backend — container start command
# ─────────────────────────────────────────────────────────────────────────────
# WHY THIS EXISTS
# The image previously started the server directly (CMD daphne ...), with no
# database migration step anywhere — not in the Dockerfile, not in a Procfile
# release phase, and there is no railway.json release command. So a deploy that
# shipped a NEW MIGRATION started the server against an OLD schema, and every
# request that touched a new column failed with a 500 ("column ... does not
# exist"). That is exactly what happened when the conversation-memory change
# added Thread.current_state / Thread.questions_asked: the code deployed, the
# migration never ran, and thread creation 500'd.
#
# This script makes migrations run on every deploy, BEFORE the server accepts
# traffic, so the running code and the database schema can never drift apart.
#
# SAFETY
#   * Django migrations are idempotent: already-applied migrations are skipped,
#     so running this on every start / restart is safe and cheap.
#   * With a single replica (the current config) there is no migration race.
#     If this service is ever scaled to multiple replicas, move `migrate` to a
#     Railway "release command" / pre-deploy step so it runs exactly once — the
#     rest of this script (exec daphne) stays the same.
#   * `set -e` makes a FAILED migration abort startup instead of serving traffic
#     against a half-migrated schema. Railway then shows the deploy as failed
#     with the migration error in the logs, which is the correct, visible outcome
#     rather than a server that boots and 500s.
# ─────────────────────────────────────────────────────────────────────────────
set -e

echo "[start] running database migrations..."
python manage.py migrate --noinput

echo "[start] starting daphne on port ${PORT:-8000}..."
# exec so daphne becomes PID 1 and receives OS signals (graceful shutdown).
exec daphne -b 0.0.0.0 -p "${PORT:-8000}" itrix.asgi:application
