# ─────────────────────────────────────────────────────────────────────────────
# itriX backend — production image
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps (psycopg + build essentials for any wheels that need compiling)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps first (better layer caching)
COPY requirements.txt requirements-dev.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# App source
COPY . .

# Ensure the start script is executable inside the image (it also runs migrations
# on boot — see start.sh). Copying from a Windows checkout can drop the exec bit,
# so set it explicitly rather than relying on the source file's mode.
RUN chmod +x /app/start.sh

# Collect static (safe even if empty); failures shouldn't break the build at this
# stage because env vars may not be present — settings tolerate missing values.
RUN DJANGO_SETTINGS_MODULE=itrix.settings.production SECRET_KEY=build-time-dummy \
    python manage.py collectstatic --noinput || true

EXPOSE 8000

# Railway/Heroku inject $PORT.
#
# v4.0.4: serve BOTH HTTP and WebSocket from ONE ASGI process with Daphne. gunicorn (WSGI)
# cannot handle /ws/* upgrades.
#
# The container now starts via start.sh, which RUNS DATABASE MIGRATIONS before
# execing daphne. Previously the server started directly with no migration step,
# so a deploy carrying a new migration served an old schema and 500'd on any new
# column. start.sh closes that gap; it also expands $PORT via the shell to a real
# integer before daphne runs (daphne rejects a non-integer -p, unlike gunicorn).
#
# Invoked via `sh` explicitly (not `["/app/start.sh"]`) so it runs even if the
# executable bit did not survive the checkout/copy — one less thing that can break
# a deploy on a Windows-origin working tree.
CMD ["sh", "/app/start.sh"]
