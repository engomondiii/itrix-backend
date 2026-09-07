# MVP release checklist

This checklist is intentionally lightweight. It records the evidence needed to merge the remediation branches safely without replacing Railway's existing automatic deployment from `main`.

## Release identity

- Backend base `main` SHA: `a4aa729aff322799101759f093fc3b4a7710848b`
- Frontend base `main` SHA: `9a155cfb0208366e8eb0a51d3778e4c8cd95d44d`
- Backend release branch: `mvp-release-hardening-20260907`
- Frontend release branch: `mvp-release-hardening-20260907`
- Backend final branch SHA: record from the PR head immediately before merge.
- Frontend final branch SHA: record from the PR head immediately before merge.
- Backend PR number/URL: record after PR creation.
- Frontend PR number/URL: record after PR creation.
- Rollback SHA: record the pre-merge `main` SHA for each repository.

## Required validation evidence

Record the exact result and test count, not only a green/red summary.

- [ ] Backend `python -m compileall .`
- [ ] Backend `python manage.py check`
- [ ] Backend `python manage.py makemigrations --check --dry-run`
- [ ] Clean disposable migration chain from zero
- [ ] Full real `pytest` suite
- [ ] Focused auth/security, legal, governance, readiness, transcript, attachment and Knowledge regressions
- [ ] Knowledge registration/currentness/hard-fact/evidence validation
- [ ] `python manage.py reingest_namespace --all` reconciliation behavior proved in non-production tests
- [ ] Frontend `npm ci`, typecheck, lint and production build
- [ ] Frontend production environment validator
- [ ] Playwright release-matrix guard and full real Chromium release run
- [ ] GitHub Actions green on both PRs
- [ ] `git diff --check` clean in both repositories

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
- If attachments are enabled, `ATTACHMENT_BLOB_ROOT` is durable/shared as required and `ATTACHMENT_AV_COMMAND` resolves to the external scanner.
- Frontend `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` and production feature flags match the deployed backend contract.

Do not copy secret values into this file or a PR.

## Merge/deploy procedure

Railway automatic deploy from `main` stays enabled. Do not add or trigger a competing GitHub deployment workflow.

Preferred order when the final compatibility review confirms the frontend can operate against the old backend during rollout:

1. merge backend PR
2. observe Railway backend automatic deployment and health/readiness
3. run required migrations and Knowledge post-merge actions
4. run backend/auth/legal smoke checks
5. merge frontend PR
6. observe Railway frontend automatic deployment
7. run complete manual smoke matrix

If the compatibility review shows the frontend cannot tolerate the old backend, document the coordinated alternative before merging either PR.

## Smoke and rollback

Record M01-M26 manual smoke results in the release notes/PR thread. At minimum, verify logout refresh revocation, signup/thread claim continuity, legal N→N+1 behavior, governance fail-closed behavior, stale-only namespace reconciliation and `/readyz` DB failure handling.

Rollback procedure:

1. identify the pre-merge `main` SHA recorded above
2. revert the merge commit on `main` (preferred; do not rewrite history)
3. let Railway automatically deploy the reverted `main`
4. verify health/readiness and smoke the affected flows
5. if a data migration is not backward-compatible, follow the migration's reviewed rollback/forward-fix plan rather than blindly reversing production data

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
