# itriX Backend Fix v4.0.1 — hang-proof the qualify → preparing → /c/[token] flow

## Symptom
With the AI flags ON in production (`ENABLE_AI_ENGINE=True`, `ENABLE_AGENTS=True`), the
Compute Bottleneck Review got stuck forever on `/review/preparing` — clean console, no
visible error. (The earlier v4.0 fix correctly made the backend RETURN the token, and the
proxy map it; this is a *different, deeper* problem that only appears with AI on.)

## Root cause
`qualify` ran **blocking AI work inside the HTTP request**, with **no timeouts**, behind
gunicorn's `--timeout 120`:
1. `LeadCreator` → `generate_lead_summary()` → a **Claude call**.
2. `ResultGenerator.generate_for_lead()` → Diagnosis agent → **OpenAI embed + Pinecone
   query + a Claude call**.
3. A second **Claude call** for the Concierge "warm-up".
When any of these was slow, the combined latency blew past the worker limit; the worker
was killed, the browser never received the token, and `/review/preparing` polled nothing.
Measured worst case (providers unreachable): **~103 s**. After the fix: **~0.1 s**.

## The fix (6 files)
- `apps/review/services/qualification_processor.py`
  - Mints the client-page **token first** (before any AI), so the response always carries it.
  - Moves result-page generation **off the request path** into a background thread
    (or Celery when enabled). The `/c/[token]` page regenerates on demand if the build
    hasn't finished, so nothing user-visible waits on it.
  - **Removes** the synchronous Concierge warm-up Claude call from the request path (it was
    best-effort priming only; live Concierge chat is unchanged).
  - Still returns `capability_token` + `journey_state` in **both** snake_case and camelCase.
- `apps/leads/services/lead_summary_generator.py`
  - The internal AI summary is now **opt-in** (`LEAD_SUMMARY_USE_AI`, default off), so lead
    creation on the sync path is instant + deterministic.
- `apps/ai_engine/services/claude_client.py`
  - Hard per-call **timeout** (`AI_CALL_TIMEOUT_SECONDS`, default 20s) + small retry cap;
    every failure/timeout degrades to the deterministic path immediately.
- `apps/ai_engine/services/pinecone_client.py`
  - Bounded query timeout; failures return no matches (graceful degrade).
- `apps/knowledge_core/services/embedder.py`
  - Client timeout; the **live** single-query path (`embed_one`) is retry/sleep-free so a
    slow OpenAI call can't stall a request. Offline ingestion keeps its retries.
- `itrix/settings/base.py`
  - Adds `AI_CALL_TIMEOUT_SECONDS`, `AI_CALL_MAX_RETRIES`, `LEAD_SUMMARY_USE_AI`
    (all env-overridable, safe defaults).

## Apply
From the `itrix-backend` root (folder with `manage.py`):
```bash
unzip -o itrix-backend-fix.zip -d _fix
bash _fix/backend_fix/APPLY_BACKEND_FIX.sh
```
Backs up every file it touches (`*.bak-<timestamp>`). Restart the backend after.

Optional extra margin: in `Procfile`, change `--timeout 120` → `--timeout 180`.

## Verified
- Django `manage.py check` clean under both development and **production** settings.
- Full review→qualify flow with **AI ON but providers unreachable + short timeout**:
  qualify returns **200 in ~0.1 s** with a valid `capabilityToken` + `journeyState=CLIENT_PAGE`.
- `GET /journey/{token}` resolves → `authorizedSurface: client_page`.
- `GET /client-page/{token}` returns **200** (renders), even when fetched immediately
  (race with the background build) — it regenerates on demand.
- Background thread confirmed to persist the `ResultPage` to the DB.
- AI-off path unchanged (no regression).
