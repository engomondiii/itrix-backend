# ─────────────────────────────────────────────────────────────────────────────
# itriX backend — production image
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps plus the production malware scanner. We deliberately use standalone
# clamscan; no clamd daemon is required by the attachment pipeline.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        ca-certificates \
        clamav \
        clamav-freshclam \
    && rm -rf /var/lib/apt/lists/*

# Refresh definitions while building the immutable image. Retry transient mirror/rate
# failures, then REQUIRE a usable database and a successful clean-file scan. An image
# without definitions is not attachment-capable and must not build successfully.
RUN set -eu; \
    attempt=1; \
    while ! freshclam --quiet; do \
        if [ "$attempt" -ge 3 ]; then \
            echo "freshclam failed after $attempt attempts" >&2; \
            exit 1; \
        fi; \
        attempt=$((attempt + 1)); \
        sleep 5; \
    done; \
    clamscan --version; \
    find /var/lib/clamav -maxdepth 1 -type f \( -name '*.cvd' -o -name '*.cld' -o -name '*.ndb' \) -print -quit | grep -q .; \
    printf 'itriX clean attachment scanner probe\n' > /tmp/clamav-clean.txt; \
    clamscan --no-summary /tmp/clamav-clean.txt; \
    rm -f /tmp/clamav-clean.txt

# Python deps first (better layer caching)
COPY requirements.txt requirements-dev.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# App source
COPY . .

# Ensure the start script is executable inside the image (it also runs migrations
# on boot — see start.sh). Copying from a Windows checkout can drop the exec bit,
# so set it explicitly rather than relying on the source file's mode.
RUN chmod +x /app/start.sh

# collectstatic imports the real production settings, so give it explicit BUILD-TIME
# cryptographic placeholders that satisfy the production contract without baking any
# deployment secret. Attachments remain disabled for this build-only settings import;
# runtime enablement is separately validated from the Railway environment.
RUN DJANGO_SETTINGS_MODULE=itrix.settings.production \
    SECRET_KEY='build-only-team-key-9F2rW6vQ1xK8mP4sT7zC5nH3jL0aD6yB' \
    CLIENT_JWT_SIGNING_KEY='build-only-client-key-4M8qV2cR7pN1xT6zK9wH5jD3sL0fB7yG' \
    ENABLE_ATTACHMENTS='false' \
    python manage.py collectstatic --noinput

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
