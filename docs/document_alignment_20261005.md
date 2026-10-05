# Customer Journey v1.5 follow-up

This follow-up incorporates the 5 October condensed journey into the same review branch. The earlier 4 October implementation and rollout guide remains applicable except where updated here. Source hash and changed corpus hashes are recorded in `source_alignment_20261005.json`.

The ordinary path remains Discover → Acquire → Activate → Prove → Decide → Continue. Public journey copy now presents actions and status, with detailed protection mechanics and refund treatment delegated to the Protection Policy and License Order. Earlier explicit three-environment, seven-day renewal and fourteen-day offline controls remain implemented because v1.5 supplies no replacement values. No claim is made to have read the absent full Protection v1.6.1.

## Decide records

The license workspace records Continue, Tune, Try another workload, Expand, Stop or Refund. Append-only records keep a workload label, baseline comparability, fidelity, net-value assessment, customer-reported measurements and separate qualitative feedback. Continue/Expand requires an activation, active entitlement and comparable reported measurements with preserved decisions and positive net value. Missing metrics stay absent, not zero. Reports are explicitly customer-reported; they do not establish independent verification, create entitlements, submit refunds or enter shared knowledge automatically. Customer history is scoped to the author, and the read-only staff ledger supports review of reusable learning without a dashboard repository change.

`GET/POST /api/v1/commerce/licenses/<id>/decisions/` is available through the owner/verified-seat access path. Inputs are bounded and outcome choices validated. Server audit metadata contains IDs/outcome only, not report contents. Use approved summaries and avoid raw workloads, secrets or personal data.

Enterprise exception records also accept `technical_review`, `scale_validation` and `senior_sponsorship` when accompanied by a concrete explanation of why ordinary self-service is insufficient. These labels do not bypass protected-work approval and evidence gates.

The v1.5 wording allows an eligible licensee or approved advocate to apply for Branching, but explicitly gives participation control to the Branch Agreement. Existing agreement-backed qualifying-purchase requirements remain. An approved advocate needs eligibility review and applicable approved terms; this journey is not authority to activate an unlicensed Branch or invent reward terms.

## Deployment and checks

Merge backend before web; run migrations including `commerce.0002` and `commerce.0003` in the deployed Railway backend, then register/sync/reingest/validate using the 4 October rollout commands. Reingestion must retire both older journey derivative paths and activate `astop_customer_journey_v1_5.md`. There are still 31 active corpus sources. Run a customer decision save/history check, test another-account isolation, reject unsupported Continue/Expand, and verify selecting Refund does not itself submit a refund request. Existing provider/runtime prerequisites remain; commerce is not enabled by this change.

The operating plan’s staffing, capacity approvals, agreements and commercial decisions require actual management execution. Only appropriate application and knowledge changes are implemented. No production ingestion, merge or deployment is performed by this branch.

## Local validation

Full backend suite: 2,144 passed, 2 skipped. Commerce, leads and Knowledge Core focused suite: 260 passed. Migration drift check and current source-audit hashes pass. Web production compilation passes with the supported Next.js Webpack option, TypeScript passes, and newly added components/tests lint without errors. The local Turbopack worker could not bind its port under the sandbox, so its standard build remains a GitHub CI check. Earlier interrupted and sandbox-limited runs are not counted as successful checks.
