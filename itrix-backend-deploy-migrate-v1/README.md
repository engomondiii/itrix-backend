# itrix-backend - Run Migrations on Deploy (fixes the production 500)

## The diagnosis

The production 500 on `/api/threads` (the "We could not reach itriX just now"
screen, with the URL falling back to a `thr_local_...` id) was **not a code bug**.
It was a **deploy bug**, and the conversation-memory change surfaced it.

Traced precisely:

- The conversation-memory fix added two columns to the `Thread` table
  (`current_state`, `questions_asked`) with migration `0004`.
- The image starts the server **directly** (`CMD daphne ...`) with **no migration
  step** - there is no release command in the Dockerfile, no `release:` line in the
  Procfile, and no `railway.json`. So Railway never ran migrations on deploy.
- Result: the new code deployed against the **old database schema**. When the code
  tried to INSERT a `Thread` row (which now includes the two new columns), Postgres
  raised `column "current_state" does not exist`, Django returned **500**, and the
  frontend fell back to a local thread id - which then 503'd on the turns endpoint.

This was reproduced exactly: with the migration NOT applied, `POST /api/threads`
returns **500**; after `migrate`, it returns **201** with the reply and the
memory/state fix working. The failure is in Django's core INSERT (model has fields
the table lacks), so it cannot be caught with try/except - **the migration has to
run**. My earlier note that "Railway migrates on release" was wrong for this repo:
there was no release command configured.

## The fix

Make migrations run automatically on every deploy, so the running code and the
database schema can never drift apart again.

- **`start.sh`** (new) - the container entrypoint. Runs `python manage.py migrate
  --noinput`, then `exec`s daphne. Migrations are idempotent, so this is safe on
  every start; `set -e` makes a failed migration abort the boot (visible failed
  deploy) rather than serving a half-migrated schema.
- **`Dockerfile`** (modified) - `CMD` now calls `sh /app/start.sh` (via `sh`
  explicitly so it works even if the exec bit was lost on a Windows checkout), and
  a `chmod +x` is added. The previous direct-daphne CMD is replaced.
- **`Procfile`** (modified) - the `web:` process now runs `migrate --noinput &&`
  before daphne, so the fix holds whether Railway uses the Dockerfile CMD or the
  Procfile.

Deploying this **heals the current 500** (the pending migration runs on boot) and
**prevents the whole class of schema-drift problem** for all future migrations.

## Files in this change set

New (1):
- `start.sh` - migrate-then-serve entrypoint. **Must stay LF** (a CRLF shell
  script fails on Linux with "bad interpreter"). A `.gitattributes` rule is
  included to enforce this.

Modified (2):
- `Dockerfile` - CMD -> `sh /app/start.sh`, plus `chmod +x`.
- `Procfile` - `web:` migrates before serving.

## How to install

Unzip this package inside the root of your `itrix-backend` repo (the folder with
`manage.py`), then from that folder run:

```powershell
powershell -ExecutionPolicy Bypass -File .\itrix-backend-deploy-migrate-v1\INSTALL.ps1
```

It backs up `Dockerfile` + `Procfile` before overwriting and refuses to run outside
the repo root. Then:

```powershell
Get-Content gitattributes-append.txt | Add-Content .gitattributes
git add -A
git commit -m "Run DB migrations on deploy (fix production 500)"
git push
```

On the next Railway deploy, watch the logs for `[start] running database
migrations` - the pending migration applies and the 500 clears.

## Prerequisite

This assumes the conversation-memory package
(`itrix-backend-conversation-memory-v1`) is already installed in the repo - that is
what added migration `0004`, which this deploy fix will run. If for some reason that
package is not in the repo, install it first; then this one.

## Applying the migration immediately (optional)

If you want the 500 gone before the next deploy finishes, you can run the migration
against the production database directly from the Railway shell (Railway ->
itrix-backend -> Console):

```
python manage.py migrate --noinput
```

Otherwise, just push - the new `start.sh` runs it on deploy.

## Verification performed

- Reproduced the 500 with the migration unapplied; confirmed 201 after it runs.
- Simulated the full boot sequence (schema missing the columns -> `start.sh`'s
  migrate -> `POST /api/threads` returns 201 with `journey_state: 2` and an agent
  reply). The fix heals a column-missing database end to end.
- `start.sh` passes `sh -n` (syntax) and is pure LF.
- Full backend test suite: **966 passed, 0 failed** with these changes in place.
