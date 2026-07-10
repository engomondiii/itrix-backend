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

# Collect static (safe even if empty); failures shouldn't break the build at this
# stage because env vars may not be present — settings tolerate missing values.
RUN DJANGO_SETTINGS_MODULE=itrix.settings.production SECRET_KEY=build-time-dummy \
    python manage.py collectstatic --noinput || true

EXPOSE 8000

# Railway/Heroku inject $PORT.
#
# v4.0.4: serve BOTH HTTP and WebSocket from ONE ASGI process with Daphne. gunicorn (WSGI)
# cannot handle /ws/* upgrades. We start via a small entrypoint so $PORT is expanded by the
# shell to a real integer BEFORE daphne runs (daphne rejects a non-integer -p, unlike
# gunicorn). Shell-form CMD guarantees /bin/sh performs the variable expansion.
CMD daphne -b 0.0.0.0 -p ${PORT:-8000} itrix.asgi:application
