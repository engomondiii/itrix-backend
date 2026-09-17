# MVP release checklist

This checklist records the evidence needed to merge the remediation branches safely without replacing Railway's existing automatic deployment from `main`.

## Release identity

- Backend base for this hardening delta: `6cbc754a2ad8554aee69056e2c39355b8874cdff`
- Frontend base `main` SHA: `9a155cfb0208366e8eb0a51d3778e4c8cd95d44d`
- Backend release branch: `mvp-release-hardening-20260907`
- Frontend release branch: `mvp-release-hardening-20260907`
- Backend final branch SHA: record from the PR head immediately before merge.
- Frontend final branch SHA: record from the PR head immediately before merge.
- Rollback SHA: record the pre-merge `main` SHA for each repository.

## Required validation evidence

Record the exact result and test count, not only a green/red summary.

- [ ] Backend `python -m compileall -q apps itrix tests manage.py`
- [ ] Backend `python manage.py check`
- [ ] Backend `python manage.py makemigrations --check --dry-run`
- [ ] Clean PostgreSQL migration chain from zero
- [ ] Focused remediation regressions
- [ ] Full `tests/test_attachments` partition
- [ ] Production Docker image build
- [ ] `clamscan --version` in the built image
- [ ] usable ClamAV definitions present in the built image
- [ ] clean-file `clamscan --no-summary` exits 0 in the built image
- [ ] deterministic harmless custom-signature probe is detected with exit 1
- [ ] Full real `pytest` suite with exact final count
- [ ] Knowledge registration/currentness/hard-fact/evidence validation
- [ ] `python manage.py reingest_namespace --all` reconciliation behavior proved in non-production tests
- [ ] Frontend `npm ci`, typecheck, lint and production build
- [ ] Frontend production environment validator
- [ ] Playwright release-matrix guard and full real Chromium release run
- [ ] GitHub Actions green on both PRs
- [ ] `git diff --check` clean in both repositories

## Attachment production contract

Production attachments support two canonical storage modes. Railway uses private S3-compatible object storage. Filesystem mode remains supported only for an explicitly mounted durable path.

The production settings import performs **structural/local validation only** and never contacts S3. Provider reachability is proved separately with the runtime validator.

### Railway backend variables

Configure these exact names. Never place secret values in Git, PR text, or release notes.

```text
ENABLE_ATTACHMENTS=True
ATTACHMENT_STORAGE_BACKEND=s3
ATTACHMENT_S3_BUCKET=${{Attachments.BUCKET}}
ATTACHMENT_S3_ENDPOINT=${{Attachments.ENDPOINT}}
ATTACHMENT_S3_REGION=${{Attachments.REGION}}
ATTACHMENT_S3_ACCESS_KEY_ID=${{Attachments.ACCESS_KEY_ID}}
ATTACHMENT_S3_SECRET_ACCESS_KEY=${{Attachments.SECRET_ACCESS_KEY}}
ATTACHMENT_S3_PREFIX=attachments/
ATTACHMENT_S3_ADDRESSING_STYLE=path
ATTACHMENT_AV_COMMAND=clamscan --no-summary
ATTACHMENT_PROCESS_INLINE=True
ATTACHMENT_EXTRACTION_START_METHOD=forkserver
CLIENT_JWT_SIGNING_KEY=<NEW RANDOM STRONG VALUE IN RAILWAY ONLY>
```

`SECRET_KEY` must also remain a strong production value independent from `CLIENT_JWT_SIGNING_KEY`. Existing database, Redis, AI, Pinecone, email, CORS/CSRF and host variables remain required according to their enabled features.

Do **not** set `ATTACHMENT_BLOB_ROOT` for the Railway S3 mode. Do not set `ATTACHMENT_SHARED_STORAGE_CONFIRMED` when `ATTACHMENT_PROCESS_INLINE=True`.

### Railway Bucket owner action

Before enabling the backend flag:

1. create or select the private Railway Bucket service named/referenced as `Attachments`;
2. expose its Railway reference variables to the backend service using the exact mappings above;
3. keep the bucket private — no public website/CDN URL is used by the application;
4. verify the bucket credentials permit only the required object operations for this application namespace;
5. deploy the attachment-capable backend image;
6. run `python manage.py validate_attachment_runtime` in the backend service;
7. enable/use the frontend attachment surface only after that command succeeds.

The runtime command writes only a synthetic probe object, verifies head/read/hash equality, securely materializes it for ClamAV, requires a clean scan, deletes the probe in `finally`, and fails if durable deletion cannot be proved. It never uses customer attachment contents and does not print credentials.

## Database and Knowledge actions

A backend release may require migrations. After the backend merge and Railway deployment is healthy, run the production migration command used by the service and verify it completes before customer smoke tests.

Knowledge reconciliation is a deliberate post-merge production action. Use repository management commands against the intended production database/index only after the merge has been reviewed:

1. `python manage.py register_knowledge_docs`
2. inspect current/noncurrent document state
3. `python manage.py sync_hard_facts`
4. `python manage.py sync_evidence_metadata`
5. `python manage.py reingest_namespace --all`
6. ingest current material with the repository's approved ingestion command where required
7. `python manage.py validate_knowledge_core`
8. run taxonomy/grounding smoke checks

Never point CI or pre-merge validation at production Pinecone.

## Environment verification

Before merge, verify in Railway without exposing values:

- `SECRET_KEY` and `CLIENT_JWT_SIGNING_KEY` exist, are strong and independent.
- `DATABASE_URL`, `REDIS_URL`, AI-provider configuration, `PINECONE_API_KEY`, `PINECONE_INDEX` and email configuration are present when their features are enabled.
- CORS, CSRF and `ALLOWED_HOSTS` match the production domains.
- the attachment variables above are complete before `ENABLE_ATTACHMENTS=True` is applied.
- `python manage.py validate_attachment_runtime` passes against the intended private bucket and the image's ClamAV installation.
- Frontend `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` and production feature flags match the deployed backend contract.

## Merge/deploy procedure

Railway automatic deploy from `main` stays enabled. Do not add or trigger a competing GitHub deployment workflow.

Preferred order when the final compatibility review confirms the frontend can operate against the old backend during rollout:

1. finish both PR reviews and CI while **not merging**;
2. owner provisions/verifies the private Railway Bucket references and strong independent signing key;
3. merge backend PR only when owner chooses to release;
4. observe Railway backend automatic deployment and health/readiness;
5. run migrations as required;
6. run `python manage.py validate_attachment_runtime` before attachment traffic is accepted;
7. run the Knowledge production actions above;
8. run backend/auth/legal/attachment smoke checks;
9. merge frontend PR only after backend compatibility and runtime validation are healthy;
10. observe Railway frontend automatic deployment and run complete manual smoke matrix.

If the compatibility review shows the frontend cannot tolerate the old backend, document the coordinated alternative before merging either PR.

## Smoke and rollback

Record M01-M26 manual smoke results in the release notes/PR thread. At minimum, verify logout refresh revocation, signup/thread claim continuity, legal N→N+1 behavior, governance fail-closed behavior, stale-only namespace reconciliation, `/readyz` DB failure handling, attachment upload/scan/download/delete, and runtime probe cleanup.

Rollback procedure:

1. identify the pre-merge `main` SHA recorded above;
2. revert the merge commit on `main` (preferred; do not rewrite history);
3. let Railway automatically deploy the reverted `main`;
4. verify health/readiness and smoke the affected flows;
5. if a data migration is not backward-compatible, follow the migration's reviewed rollback/forward-fix plan rather than blindly reversing production data.

## Version/tag and GitHub Release

Do not create the final tag before both PRs are merged and production smoke checks pass.

After release verification:

```bash
git checkout main
git pull --ff-only
git tag -a <version> -m "itriX <version>"
git push origin <version>
```

Then create the GitHub Release from that tag, include both PRs, final SHAs, validation evidence, migration/Knowledge actions, environment/runtime verification, smoke results and rollback SHAs.
