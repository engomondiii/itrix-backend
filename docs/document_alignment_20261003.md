# October 2026 source alignment

This change reconciles the old itriX archive, the new archive and the knowledge sources on main. It does not merge, deploy, import private originals into public Git, or reingest a production index. `source_alignment_20261003.json` inventories 97 extracted entries (68 baseline, 29 new), including nested package provenance and exact SHA-256 hashes. A hash identifies an original without publishing its contents. Patent-file reference strings are redacted from public filenames in that audit.

## Authority and conflicts

| Domain | Governing input | Implementation |
| --- | --- | --- |
| Products and stages | Portfolio / Technology Architecture v1.4, 2 October | ASTOP; AXIOM Compute; planned AXIOM Core; QNTA Runtime. Historical ALPHA API codes remain stable. |
| ASTOP research evidence | White Paper v2.3 and updated R07 PRISM | 58.8–69.2% observation-induced tokens; 23.1–30.1% model calls; 88.1–90.0% delivered bytes, within the tested panel. Older 51.9–84.5% stays historical. |
| Access journey | Customer Journey v1.0 | Individual, organization and protected enterprise paths; install, configure, compare quality/cost, continue/tune/stop/refund/expand. |
| Retail commercial terms | License Order v2.6 | USD20 individual; USD16/seat organization with at least two seats; eligible Branch discount10%, never stacked. Overrides journey's USD19 and twelve-download examples. No invented subscription, perpetual-license promise or support bundle. |
| Identity and delivery | Software Protection v1.5 | Verified legal identity and email, exact LO acceptance, verified captured payment, named seats, signed production delivery, opaque activation IDs. |
| Branch | Branch Agreement v1.4 | Existing licensee applies; operator approves; separate exact agreement accepted; only then code activation. Parent derives only from earlier qualifying attributed purchase. |
| Referral economics | Formal five-level schedule | 10%,5%,2.5%,1.25%,0.75% = 19.5%. USD18 eligible net fee accrues USD3.5100 across five levels. The confidential strategy illustration is inconsistent; it is not used as an executable formula. |
| Strategy version | IWL filename v2.1, internal title v2.0 | Preserve discrepancy; no asserted newer legal authority. Original remains confidential. |
| Sales deck | Options, explicitly undecided | No automatic freemium/trial, native Windows installer, Homebrew publication or hosted-service entitlement. |
| QNTA | Contract and Systems plus portfolio | Two aspects of one architecture; QNTA Runtime is the product. Selected numerical/inference-graph tests do not prove arbitrary-model training, universal acceleration or energy savings. |
| Research package | Seven research papers, eight specification entries | Evidence register, not eight patent grants. Judge-CIA has a substitute draft where the filed PDF is missing; QNTA is outside this package. Personal patent identifiers/addresses stay excluded. |
| People | Existing September profiles | Keep exact existing sources and dated biographical/inventorship qualifications. New filings do not retroactively prove individual inventorship or change the September freshness boundary. |

## Knowledge changes

Three public, bounded summaries are added: `itrix_product_portfolio_v1_4.md`, `astop_product_and_access_20261002.md`, `research_portfolio_summary_20261002.md`. These are editorial derivatives, not replacements falsely represented as byte-identical originals. Source hashes identify their inputs. The exact confidential originals must remain in approved private storage. `import_october_sources --archive <new-documents.zip> --storage-root <private-directory> --dry-run` validates every supported original against the reviewed hashes. Without `--dry-run`, it writes exact bytes outside the Git checkout and registers internal-only originals; patent specifications and the unsupported strategy deck are prohibited from embedding. It makes no embedding or public-disclosure call. Use an approved private volume for deployment.

The source manifest marks the September product canonical, company overview, White Paper v3.5, old ASTOP summary/GTM, MVP guide v3.5, older PRISM paper and combined controlled AXIOM-TENSOR/QNTA summary noncurrent for retrieval. Files are retained for traceability rather than destructively deleted. Existing registration removes stale SQL chunks; existing namespace reconciliation removes stale vector entries. The comparative document remains useful for request/harness/observation distinctions, with its older benchmark explicitly historical. Other technical and legal baseline material remains unchanged where no replacement exists.

Product families are not extra products. CRE is enabling technology; FQNM and SPADES are research assets. QNTA Core is a future designation. Observe/represent/learn/execute are not mandatory customer stages. Independent AXIOM qualification no longer requires prior ASTOP value; workload, identity, NDA and commercial gates still apply to the existing protected assessment flow.

## Commerce deployment contract

`apps.commerce` is a separate commercial ledger and client/operator API. It does not overwrite the protected enterprise ASTOP engagement, generalized NDA, or existing content authorizations. Download/license rights never authorize unrelated restricted knowledge.

New records preserve verified identity snapshots, exact accepted order text and hash, acceptance time and hashed session evidence, payment references, licenses, named seats, activations, signed build delivery traces, refunds, Branch agreement evidence, frozen referral lineage, four-decimal reward accrual and operator audit events. No payment status supplied by a browser activates a license. Staff operations require ADMIN; clients are owner-scoped. Refund approval revokes all order seats and renewal before repayment. A durable repayment-pending record and provider idempotency key survive provider outages. Offline enforcement is bounded by token expiry; this cannot promise immediate offline removal.

Configuration defaults:
- `ASTOP_COMMERCE_ENABLED=false` and empty `ASTOP_COMMERCE_ADAPTER` keep checkout and delivery unavailable.
- `ASTOP_VALIDATION_DAYS=7`, `ASTOP_MAX_ENVIRONMENTS=2` are configurable implementation defaults requiring commercial approval; they are not guaranteed limits in the public LO summary.
- Final LO and Branch text must be reviewed and published through an authorized private operator session. Draft fields, legal entity, payout cycle/minimum/currency, dispute terms and other missing Branch particulars must be completed first. Nothing in this PR is a legal approval.

The selected adapter must implement:
1. `checkout(order_id, amount, currency)` with an idempotent hosted-payment session. The amount is the accepted license fee; taxes and any additional payable amount must be reconciled with the final displayed order before enabling live sales.
2. `verify_webhook(body, headers)` verifying signature, event age, replay protection and merchant account, returning only verified capture/refund/chargeback events. Capture returns order ID, immutable event ID, payment reference, currency and license fee excluding separately charged tax. No sandbox events in production.
3. `delivery(license_id, platform)` returning a short-lived authorized HTTPS URL and production build ID/hash/signing identity. Delivery must re-check entitlement at redemption so previously issued URLs cannot defeat revocation. No raw debug binary or embedded email.
4. `sign_activation(claims)` producing a cryptographically signed, environment-bound token with expiry and version. The shipped ASTOP runtime must verify the signature/expiry offline and renew against active entitlement. No adapter or binary is invented by this change.
5. `refund(payment_reference, amount, currency, idempotency_key)` returning a confirmed provider reference only after repayment is accepted. Retry pending refunds using the same key.

Activation/build signing, native binary enforcement, provider tax treatment, compliance identity verification and real-money payout execution need the actual production services and approved policy. Until those are integrated and end-to-end tested, leave commerce disabled. Referral accrual and reviewed eligibility are implemented; no automatic bank transfer or payout cadence is invented from an incomplete Branch draft. Controlled/related-account fraud must be reviewed before reward release. No reward is payable for recruitment alone.

## Manual rollout after review

1. Review and merge coordinated backend, public-web and staff-dashboard PRs. Backend goes first; frontend unavailable states tolerate commerce not being configured.
2. Back up the production database and index. Apply migrations. Existing customer IDs, ALPHA wire codes and authentication mechanisms are unchanged. Display-choice migrations do not rewrite customer data.
3. Run `register_knowledge_docs`, `sync_hard_facts`, `sync_evidence_metadata`, then the existing scoped `reingest_namespace` procedure for affected company/astop/technology namespaces. Use its dry-run first; inspect obsolete vector removal before committing the index changes. Run `validate_knowledge_core`, `verify_rag_grounding` and `verify_ai_answer` in the approved environment. No production calls were made while authoring this PR.
4. Verify public answers for all four offerings, bounded research metrics, historical comparisons, people qualifications, pricing and access prerequisites. Check anonymous and restricted-content behavior separately.
5. Complete missing legal and service configuration. Exercise sandbox payment capture/replay, wrong amount, unverified identity, stale LO, named-seat overflow/reassignment, refund provider failure/retry, chargeback, revoked download/renewal, offline expiry and five-level reward reversal. Only then consider enabling real sales.

Rollback: disable commerce first; retain the financial/acceptance ledger. Do not delete legal or payment evidence to roll back UI. Reverting terminology must not reactivate superseded claims. Use a reviewed forward data correction if any production order exists.

## Exact original import

Run `python manage.py import_october_sources --archive '/secure/New documents.zip' --storage-root /secure/knowledge-october --dry-run` before the corresponding command without `--dry-run`. It verifies all 25 eligible originals against the reviewed hashes, preserves exact bytes in private files outside Git, registers restricted metadata idempotently, and performs no embedding or public upload. Patent specifications and the undecided slide deck are marked prohibited for embedding. The archive's mapping and checksum files remain provenance entries in the audit. Grant access to private storage only through the existing authorization controls.

## Validation at submission

- Full backend suite: 2,127 passed, 2 skipped; follow-up commerce/import checks: 17 passed after final identity and evidence safeguards.
- Migration drift check: no changes detected. Source manifest canonical rules fit database limits.
- Actual supplied archive import dry-run: 25 exact originals verified; no private source bytes were published.
- Companion dashboard: lint and TypeScript pass, 72 tests pass, production build passes.
- Companion web: TypeScript and lint pass (existing warning-only lint output), production build passes. Local browser automation is blocked by the macOS Chromium sandbox; GitHub's Linux release workflow must provide browser validation before merge.
