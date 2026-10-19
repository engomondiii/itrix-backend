# October website and Store-policy integration

## Governing inputs and decisions

The supplied October website archive matches its extracted directory byte-for-byte (58 non-metadata files). Source fingerprints are in `source_alignment_20261019.json`. The development request treats the HTML as design references, not production JavaScript. The views preserve its layout, colours, assets and bilingual structure; the demo authentication, data, captcha and chatbot are replaced with real application behavior.

Precedence: the project owner's temporary Store rule governs availability; the October 8 meeting governs the retail distribution direction and working prices; Portfolio v1.7 governs product names, stages and research relationships; the October 16 request governs website and administrator behavior. Mockup labels AXIOM Tensor / AXIOM QNTA are reconciled to product names AXIOM Compute / QNTA Runtime; AXIOM-TENSOR remains a technology. The old mockup patent count and SPADES description are reconciled to v1.7. Application status never implies a grant. The mockup typography is retained where the broader brand manual specifies different general typography, following the owner's instruction to match these screens.

Only curated summaries enter Knowledge Core. Confidential meeting details, raw internal operating documents, patent application identifiers, credentials and personal information are not published in the repository. The retired portfolio v1.4, journey v1.6 and website membership summary are physically replaced; manifest tombstones also prevent stale database copies from becoming current. Other useful sources remain. Existing customers' agreements and historical account rights are preserved separately from new acquisition.

## Open-question recommendations

1. Keep `/itx-console-7k2m`; its obscurity is not authentication. Each admin API verifies the session and current allowlist.
2. Use the two allowlisted mailboxes, single-use hashed five-minute OTP, one resend/minute, five/hour and five-attempt lockout. A mailbox outage is recovered by an authorized infrastructure owner changing the allowlist through deployment configuration; no password/backdoor is added. Protect the mailboxes with MFA.
3. No office IP allowlist by default because admins travel. IP rate limits and auditable sessions remain.
4. Run the web, separate dashboard, backend, worker and database on existing Railway services. Point `itrix.co.kr` at the web service using Railway's issued DNS records. Confirm Gabia's role as DNS/domain provider and any existing site that must be preserved. Do not guess DNS values.
5. Retain the existing mail transport until the approved sender is verified. Configure SPF/DKIM/DMARC with the chosen mail provider before switching to `no-reply@itrix.co.kr`.
6. Store explicit newsletter opt-in and signed unsubscribe/resubscribe state now. No campaign sender or third-party marketing export is enabled without the owner's service choice.
7. Cloudflare Turnstile, validated server-side for the expected hostname and action. Missing verification configuration fails closed; no fake checkbox bypass.
8. Korean `/`, English `/en`, same-page language links; default Korean rather than automatic browser-language redirects.
9. No analytics provider loaded. Persist necessary/optional consent; add analytics only after provider choice and only after consent.
10. Railway region and processor details must be confirmed by the deployment owner and inserted into the draft privacy notice before opening intake. Do not infer the database region from the Pinecone configuration.
11. Recruitment dates, capacity and free-PoC wording remain editable notice content, not an invented launch promise. The owner must publish confirmed dates. Store release timing is independent of website launch.

## Runtime configuration

Backend and worker share the new settings:

- `WEBSITE_ADMIN_EMAILS=admin@itrix.co.kr,associate@iwl.kr` (server-only, not editable in UI)
- `WEBSITE_ALERT_EMAILS=admin@itrix.co.kr,associate@iwl.kr`
- `WEBSITE_PUBLIC_URL=https://itrix.co.kr` (use the real review domain until cutover)
- `WEBSITE_FROM_EMAIL` = an approved, verified sender; defaults to existing `EMAIL_FROM`
- `WEBSITE_PROXY_KEY` = a new random shared secret also installed on web and dashboard. Never a `NEXT_PUBLIC_` variable.
- `WEBSITE_TURNSTILE_SECRET`, `WEBSITE_TURNSTILE_SITE_KEY`, `WEBSITE_CAPTCHA_HOSTS` = approved widget credentials/hostname allowlist
- `WEBSITE_PRIVACY_VERSION` = legally approved version; `WEBSITE_INTAKE_ENABLED=false` until legal text, region, retention, captcha and mail are ready
- `WEBSITE_RETENTION_DAYS=365`, `WEBSITE_AUDIT_RETENTION_DAYS=366` are draft defaults, not legal advice; align with approved notice and backup policy.
- `ASTOP_APPLE_STORE_CONFIRMED=false`, `ASTOP_MICROSOFT_STORE_CONFIRMED=false`; leave URLs empty. Change a Store flag only after itriX confirms its actual listing is live. Website checkout and new trial/distribution APIs remain retired independently of old commerce flags.

Web: `DASHBOARD_ORIGIN=https://itrix-dashboard-production.up.railway.app`, `API_URL` to backend `/api/v1`, `WEBSITE_PROXY_KEY`, public site/API/WS URLs. Build again when public URLs or rewrites change. Dashboard: `API_URL` to backend `/api/v1`, `WEBSITE_PUBLIC_URL` to the web origin, the same proxy key. Its runtime config and Next assets are routed under `/itx-console-assets`; its API/cookie path is `/itx-console-7k2m`. The web proxy keeps admin JS out of the public application bundle. The existing client account system and historical staff operations remain separate from the new website administrator plane.

Both BFFs only trust the ingress-provided `X-Real-IP` when forwarding it with the shared key. Confirm Railway ingress overwrites that header before launch; do not trust arbitrary browser-supplied forwarded addresses. Direct API requests use their connection peer. Use a shared Django cache for IP throttles across workers.

## After the owner merges all three pull requests

Do not merge these branches automatically. GitHub-connected Railway services deploy from main. Review their build/deployment status before running commands in the **new backend deployment**, not an older container:

```sh
python manage.py migrate --noinput
python manage.py check
python manage.py register_knowledge_docs --dry-run
python manage.py register_knowledge_docs
python manage.py sync_hard_facts
python manage.py sync_evidence_metadata
python manage.py reingest_namespace --all
python manage.py validate_knowledge_core
```

The full reingestion clears superseded vectors in every affected namespace. Do not treat document registration alone as ingestion. Review validation and parity output; retry failed namespaces rather than declaring success after an interrupted command. This implementation task does not run production migrations or ingestion.

New website mail uses a transactional outbox. Celery schedules `website.deliver_mail` each minute and retention daily. **A running Celery worker alone does not run the beat scheduler.** Confirm the project has exactly one beat process, or use Railway scheduled services for `python manage.py process_website_mail` and `python manage.py expire_website_data` at these intervals. Initial submission also dispatches delivery when Celery is enabled; the scheduled retry is still necessary for broker/mail outages. Monitor pending mail and delivery attempts; unsuccessful SMTP remains retryable. Delivery is at-least-once, not an exactly-once email promise.

Configure daily PostgreSQL backups and retention in Railway; these cannot be enabled by a Git commit. Backups containing deleted records must expire under the approved policy. On restore, rerun retention and reconcile deletions before exposing restored data. Application-level personal-field encryption is not introduced: confirm infrastructure encryption/region and restrict database access; assess field encryption with the data controller if required.

## Acceptance checks after deployment

Verify KO/EN layouts at 1440, 820, 390 and 360 pixels, language switch, mobile menu, notice dates/KST hiding and cookie settings. Submit one approved test PoC and inquiry and check references, both admin notifications and localized confirmations. Verify failed captcha and mail retry. Sign in using each allowed mailbox, reject an unauthorized one, test expiration/reissue/logout, inspect records/status/notes, filtered CSV and deletion with explicitly disposable data. Check signed unsubscribe and resubscribe. Do not submit real customer data for testing.

Ask X must remain the existing engine: test Korean/English answers, ASTOP prefill, Store pre-launch interest and enterprise PoC paths. It must never offer the old website checkout/trial or promise a Store URL while flags are off. The research portfolio must identify four offerings and stages, distinguish applications from grants and avoid guaranteed performance claims. Confirm historical account support still works. Review draft legal placeholders and footer business information before enabling public intake.
