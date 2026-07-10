itriX BACKEND patch — v4.0.3 (realtime chat + live client-page generation)

HOW TO APPLY
  1. Unzip this file into the ROOT of your itrix-backend repo
     (the folder that contains manage.py). You'll get:
         itrix-backend-patch/apply.sh
         itrix-backend-patch/files/...
  2. From the repo root, run:
         bash itrix-backend-patch/apply.sh
     It copies the fixed files into place, backs up whatever it overwrites into
     ./.patch-backup-<timestamp>/, adds that backup to .gitignore, then deletes the
     patch payload, the zip, and itself so nothing extra is committed.
  3. Commit & push:
         git add -A
         git commit -m "realtime chat + live client-page streaming"
         git push
  4. On Railway (backend service): make sure a Redis plugin is attached and REDIS_URL is
     set. The Procfile web: process is now Daphne (ASGI) — do NOT set a Start Command that
     forces gunicorn, or WebSockets will 404 again. Redeploy.

FILES IN THIS PATCH (all against the shipped v4 backend)
  Procfile                                  web: → Daphne (serves HTTP + WS in one process)
  apps/realtime/routing.py                  + ws/client-page/{token}/ route
  apps/realtime/middleware.py               accept the browser's itrix.bearer.<token> subprotocol
  apps/realtime/consumers/review.py         streaming chat + streaming client-page generation
  apps/ai_engine/services/claude_client.py  + stream() token generator
  apps/agents/services/concierge.py         + stream_reply() token generator
  apps/conversations/services/fan_out.py    frontend-shaped {type,payload} camelCase events

Deploy the itrix-web patch too — the two work together.
