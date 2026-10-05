# Customer-chat corrections — 5 October 2026

## Reported behavior and changes

The supplied transcript contains five answers from the proposed seven-question check. It is customer feedback, not a claim that all seven cases passed.

- Pricing repeated retired USD 19/download examples and incorrectly discounted five organization seats to USD 72. The current public sources now state USD 80 for five seats, including with a qualifying referral, and USD 18 for an eligible referred individual. Historical reconciliation remains in earlier audit documents, outside the active customer explanation.
- Activation answers missed three environments and seven-day renewal despite those being documented, and confused validation renewal with billing. Public terms now group these with the fourteen-day offline window, confirmed environment replacement and running-session continuity.
- Exact terms could lose retrieval slots to broader, higher-authority overviews. Relevant current public License Order/journey chunks are now included as candidates and prioritized by question relevance. They still pass currentness, namespace, audience, stage, disclosure, paraphrase and claim-ceiling checks. Other explicitly named products do not inherit ASTOP pricing.
- Conversation instructions now answer first, then offer one context-specific next step for substantive product/buying/evaluation questions. Known information must not be requested again. Refusal, no-fit and a visitor choosing to leave remain valid.
- JSON and streaming chat now share the same sales/evidence policy. An old blanket ban on benchmark numbers/comparisons conflicted with the source-grounded policy; the shared instruction permits only authorized, qualified evidence, never guaranteed savings.
- Voluntary advocacy is distinct from agreement-governed reward rights. Customer downloads are distinct from signing secrets, which are never customer deliverables.

No pricing engine, accepted agreements, payment integration, authentication, database schema or dashboard behavior changes. The existing web Markdown renderer already supports the relative links to `/astop` and `/workspace/astop`; this correction requires no web repository change.

## Release and customer acceptance

After manual merge and successful Railway backend deployment, refresh the changed ASTOP knowledge sources from the deployed container:

```sh
python manage.py register_knowledge_docs
python manage.py reingest_namespace --namespace astop
python manage.py validate_knowledge_core
```

No new migration is required. Reingestion is necessary: updating repository text alone does not replace existing database/vector chunks. Prior source-alignment JSON files record historical snapshots; the accompanying sales audit records current amended hashes.

Use a new website conversation for acceptance so earlier incorrect answers do not influence the conversation. Repeat the seven original questions and also test a follow-up after specifying five seats. Check:

1. Correct product maturity and one relevant, optional next step.
2. Six stages and all six Decide choices, without claiming discovery is proof.
3. Individual USD 20 / eligible referral USD 18; five organization seats USD 80, never a stacked discount. No invented billing period or retired-price narrative.
4. Three environments, confirmed replacement, seven-day validation renewal, fourteen-day offline expiry from last validation, preservation of entitled running sessions; no workload content in licensing traffic.
5. Fair workload-specific proof, overhead and fidelity, with no claimed customer or 24-hour test.
6. Decisions distinguished from actual refund submission/approval; enterprise only for a concrete exception.
7. Restricted information refused briefly; optional advocacy distinguished from approved Branch reward rights; signing secrets never released.

Automated checks verify retrieval behavior and prompt contracts, not live language-model output. A fresh production chat after deployment/ingestion remains the final acceptance check. Checkout and other external service readiness are not established by this change.

## Local validation

- Focused retrieval/concierge/prompt regression run: 41 passed.
- Full backend suite: 2,153 passed, 2 skipped, 5 attachment-extraction failures. The failures report `extraction sandbox could not start: [Errno 1] Operation not permitted` in this macOS sandbox; security controls were not disabled to force a passing result. GitHub CI must provide the normal-environment release result.
- Migration drift check: no changes detected. Diff hygiene passed.
