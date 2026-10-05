# 4 October journey and activation alignment

Inputs: Customer Journey v1.2 (including 25 diagrams) and Internal Commercialization Operating Plan v1.5. Exact source hashes and editorial decisions are in `source_alignment_20261004.json`. The raw confidential operating plan is excluded from this public repository. Existing accepted legal releases, unrelated products, identity/auth mechanisms and the staff dashboard repository are unchanged.

## Implemented

- Six-stage ordinary journey: Discover, Acquire, Activate, Prove, Decide, Continue. Discovery establishes plausibility; proof requires a comparable real workload after activation. Enterprise evaluation is an exception, not a third ordinary license or prerequisite for ordinary sales. Advocacy and Branch participation are optional.
- Standard activation: three registered environments per named seat; explicit confirmed replacement; normal renewal at seven days; offline expiry fourteen days from the last successful validation. API signing claims include validation time, renewal time, expiry and completion of entitled running sessions. License-row locking serializes renewal/replacement; failed signing rolls back replacement. Unexpected activation payload fields, including workload data, are rejected.
- Refund/reversal/suspension block future issuance and renewal while preserving already issued expiry timestamps. Previously entitled jobs must finish; runtime enforcement is an adapter/build prerequisite, not claimed to be implemented inside a binary by this repository.
- Named organization users can find their assigned license and request delivery without seeing other users’ emails or acquiring administrator rights. Purchaser seat management remains owner-scoped.
- Existing protected enterprise progression requires a concrete exception and explanation of why self-service is insufficient. Protected work also requires technical and decision owners, baseline/fidelity/success-no-go criteria, security/data authorization, effort allowance, next decision and deadline. Existing records are not silently advanced or rewritten; future progression must satisfy these gates. The staff API continues to accept these fields inside `qualification_context` and `evaluation_scope`; dashboard UI work belongs to its separate maintainer.
- Knowledge Core physically replaces only the superseded journey/protection derivatives, edits three related sources and retains the remaining corpus. Thirty-one active sources remain. Old paths have explicit noncurrent replacement policies. Prompt guidance preserves distinct routes, actual service availability and proof/claim boundaries.

## Operator contract for protected enterprise records

`qualification_context.enterprise_exception`: one of `security`, `procurement`, `private_deployment`, `high_volume`, `extended_offline`, `protected_scope`; also supply `why_self_service_insufficient`. Company size alone is insufficient.

Before controlled evaluation, `evaluation_scope` must include `technical_owner`, `decision_owner`, `baseline_plan`, `fidelity_criteria`, `success_no_go`, `effort_allowance`, `next_decision`, `decision_deadline`, and `security_data_authorization`, alongside existing scope requirements. These are documented references/criteria, not a claim that a text entry itself verifies an external approval. Existing authorization and agreement gates remain required.

## External and management work

The operating plan’s staffing, ownership assignments, capacity authorization, marketing experiments, leadership decisions and negotiated enterprise economics remain management work. This change does not invent approvals, schedule campaigns or promise staffed services. Workload proof remains actual customer/operator measurement; the web guide does not fabricate test results or auto-promote feedback into authoritative knowledge. Protected work requires reviewed scope and effort evidence.

The portfolio table contains inconsistent Core/QNTA role wording; consistent prose and existing portfolio definitions prevail pending source correction. The referenced full Software Protection v1.6.1 is not supplied. Only explicitly available activation/continuity requirements are implemented, with earlier compatible protection controls retained.

## Merge and rollout

1. Review and merge backend and web PRs; backend first. Leave commerce disabled until integrations are approved and exercised. Nothing here merges or deploys production.
2. Railway auto-deploys the merged branches according to existing configuration. In the linked backend service run `python manage.py migrate` (via `railway ssh` for execution inside the deployed service). Migration `commerce.0002` adds nullable validation/renewal timestamps. Existing tokens and accepted contracts are not rewritten or retrospectively extended.
3. Check activation configuration: `ASTOP_MAX_ENVIRONMENTS=3`, `ASTOP_VALIDATION_DAYS=7` (renewal interval), `ASTOP_OFFLINE_VALIDITY_DAYS=14`. Remove or correct old two-environment overrides. Nonstandard policy fails closed and needs a separately approved implementation, not an arbitrary environment override.
4. In the deployed backend run `python manage.py register_knowledge_docs`, `python manage.py sync_hard_facts`, `python manage.py sync_evidence_metadata`, `python manage.py reingest_namespace --all`, then `python manage.py validate_knowledge_core`. Registration retires missing/replaced paths; all-namespace reconciliation removes stale vectors. Follow the existing deployment procedure and back up production as usual.
5. Verify visitor answers describe the six stages, post-activation proof, two ordinary license types, three environments, seven-day renewal and fourteen-day offline validity without universal savings or internal disclosures. Check prices remain unchanged and enterprise is not forced on ordinary buyers.
6. Before enabling sales, test the real payment/verification/delivery/signing adapter plus production runtime: authenticated expiring download redemption, signatures, three environments, confirmed fourth replacement, renewal on day 7, no new sessions after day 14, failed renewal after refund, preservation of entitled running jobs, repayment retry and revoked delivery. Licensing traffic must exclude workload content. A single signed build per platform is delivered through individual authenticated expiring links; do not implement customer-specific binaries. No production runtime/provider tests are claimed here.

## Validation

See the PR validation results for actual automated runs. Tests use test adapters and local database settings; no production ingestion or payment is performed. Existing full-suite failures, if any, are reported separately from this change.
