# ASTOP trial and annual membership alignment

The 7 October sources replace the ordinary paid-before-proof journey with Discover → Enroll → 7-Day Trial & Prove → Join → Continue → Renew. The supported commercial model is a seven-day free trial, explicit annual membership after the full trial, USD 20/year Individual or USD 16/user/year Organization (2+), authorized annual renewal, and a fourteen-day refund request window after the applicable payment.

## Source decisions

Read all paragraph/table text, headers and footers in Customer Journey v1.6, Internal Commercialization Operating Plan v1.6 and IWL AI-Led Sales/IP Control Proposal v1.1 Condensed. The three files contain no embedded media. The operating plan is a confidential management working edition; the IWL document is an internal recommendation, not a signed approval. Originals and confidential business plans are not published in these public repositories. Only the customer journey and non-secret implementation requirements are represented in curated sources.

Physically replace public `astop_customer_journey_v1_5.md` and `astop_license_order_summary_v2_6.md` with `astop_customer_journey_v1_6.md` and `astop_membership_terms_20261007.md`. The latter is explicitly a membership-policy summary, not a fabricated revised LO. Mark the old documents inactive so old DB/vector rows cannot become current context. Amend only contradictory ASTOP access, refund and protection paragraphs in retained sources. Preserve people profiles, technical/research originals and unrelated product material. The 31-document active corpus size is unchanged.

The revised complete License Order, trial terms, Software Protection Policy and membership-aligned Branch Agreement were not supplied. Do not change already accepted contracts or call the launch approved. Existing orders retain 30-day refund snapshots; new annual orders carry 14 days. Retained 3-environment / 7-day validation / 14-day offline limits are technical controls, not billing periods, and are capped by trial/annual expiry. The 30-day Branch settlement hold is not the new customer refund window. No new reward rates, perpetual rights or provider choice is invented.

## Application changes

- Add trial enrollment and immutable trial acceptance evidence; verified account and legal identity required, one trial per account/verified identity, no trial payment or reward.
- Block Join until the full seven days end; preserve explicit LO and annual recurring consent. Reject scope changes without review rather than quietly changing verified user/entity scope.
- Add trial/annual expiry and renewal/cancellation state to licenses without converting legacy records. Preserve legacy activation token claims; add bounded entitlement claims for the new flow.
- Process trusted recurring captures with idempotent payment/period records and a fresh 14-day refund-request window. Refund approval stops future authority before repayment. Original order evidence remains unchanged.
- Cancellation persists before provider synchronization so a provider outage cannot leave server renewal authorized; failed synchronization is retriable. Already-paid access remains until expiry under the approved cancellation policy. Disputed/unauthorized captured funds require reconciliation, not automatic access.
- Update the EN/KO public page, authenticated trial/Join/renewal/refund interface, restricted BFF routes, sales prompts and exact-term retrieval. Proof feedback is still private, customer-reported and not automatic purchase/refund authorization.
- No dashboard changes. No changes to auth, unrelated product functionality or research claims.

## Production adapter and approval contract

`ASTOP_MEMBERSHIP_LAUNCH_APPROVED=false` is the default. Existing `ASTOP_COMMERCE_ENABLED` and adapter settings remain required. Do not enable the new flag merely because migrations succeed.

An authorized operator must publish immutable, reviewed `trial` and `lo` LegalRelease records with `policy=annual_v1_6`. The new Branch agreement requires the same policy marker before new membership Branch enrollment/reward release. The flag is an operational approval gate; source documents and test adapters do not constitute approval.

The production adapter must advertise all lifecycle capabilities: `trial_delivery`, `asymmetric_entitlements`, `annual_checkout`, `annual_renewal`, `renewal_notice`, `cancel_renewal`, `renewal_refund`. Required callables are `checkout_membership`, `cancel_renewal`, `sign_activation`, `delivery`, `verify_webhook` and `refund`. Capability declarations are not an end-to-end certification; the pilot below must be completed before approval.

- `checkout_membership` receives immutable order ID/amount/currency, yearly interval, recurring authorization, exact legal hash and stable idempotency key. It creates one subscription/payment path, never an immediate charge during trial. Payment webhooks map to the server order; initial capture creates annual access. Taxes, invoices and seller accounts remain provider/operator responsibilities.
- Recurring provider billing owns appropriate renewal notice under the approved terms; the adapter must not advertise `renewal_notice` until configured and tested. A signed verified `renewal` webhook identifies license, provider event, payment reference, USD license fee and exact `period_start` (previous `ends_at` ISO format). The server checks due date, consent, cancellation, amount and replay consistency before extending by a calendar year. Map the provider subscription/order to the issued license in the adapter. Rejected unexpected charges require provider reconciliation.
- `cancel_renewal` must be idempotent and confirm provider cancellation. Configure a scheduled `python manage.py sync_membership_cancellations` retry run and monitoring before enabling renewals. The command also covers stopped/revoked memberships; no scheduler is installed by this PR.
- Signing stays inside itriX's controlled service. Local ASTOP uses the public verification key and checks user/environment scope, signature, expiry and entitlement type. Trial authority cannot exceed seven days; annual membership does not imply a year of unchecked offline execution. Runtime enforcement and approved signed/notarized installers are external dependencies, not supplied by this repository.
- Delivery must verify entitlement again at redemption, with authenticated expiring URLs and approved production-build metadata. Signing secrets, raw identity and workload content must not be embedded in installers or tokens.
- Refund and chargeback webhooks map to the affected entitlement/order, stop future authority and reverse related rewards. Renewal refund requests have separate review/repayment records; provider repayment uses stable idempotency keys. Historical orders remain under their own terms. Renewal reward allocation awaits explicit agreement/settlement implementation; no automatic renewal reward payout is claimed.

Before launch test payment failure/replay, trial expiry, explicit Join, annual renewal/notice, cancellation retries, refund/reversal, copied credentials, fourth-machine replacement, expired/invalid signatures and tampered builds. This architecture does not make copying or reverse engineering impossible. Appoint owners for product/runtime, verification, legal terms, signing, payments/support and knowledge approval. Automated verification-provider integration and production installer/provider implementation remain external setup; the portal gives an unavailable state while gates are incomplete.

## Deployment after manual merge

Merge/deploy backend first, then web. Back up the database through the normal operational process before schema deployment. In the deployed backend:

```sh
python manage.py migrate --noinput
python manage.py check
python manage.py register_knowledge_docs
python manage.py sync_hard_facts
python manage.py sync_evidence_metadata
python manage.py reingest_namespace --all
python manage.py validate_knowledge_core
```

Full namespace ingestion follows metadata synchronization so evidence-source updates do not leave pending rows. Do not turn on commerce as part of this migration. Verify unavailable-state UX first; then execute an approved limited pilot with real integrations before enabling retail access. No live purchase, production activation, or external pilot is claimed by automated tests.

## Validation
Full backend suite: 2,178 passed, 2 skipped. After final account-state and cancellation refinements, the commerce/agent partition passed all 133 tests. Migration drift and Django checks passed. New tests cover free-trial nonpayment, full-trial Join gating, explicit recurring consent, identity/customer isolation, expiry-bounded activation, recurring idempotency, refund review and durable cancellation failure/retry. No live external payment or runtime test was performed.
