# Client revisions — Round 3, October 27, 2026

Branch: `client-round3-20261027`. Review and merge manually; no production deployment or ingestion was performed while preparing these changes.

## Approved scope

- N1: ASTOP public-validation notice, 5 companies / 3 months free; 78% claim explicitly limited to internal tests, localized program route, approved external application link, Escape and KST-day dismissal.
- N2: supplied EmptyCalls **B** visualization, 10 calls versus 1, 9 empty calls versus 0, 10-second loop, completed still frame for reduced motion, stacked mobile logs.
- 02: supplied PoC, Contact and Partnership layouts with Google Forms; two cross-request cards with staggered shimmer and reduced-motion support. Website form collection, website OTP administration and submission emails are retired. Historical records remain; customer authentication remains operational.
- 05: header language follows public page language and assistant locale; visible mobile KO/EN controls.
- 08: home contact section uses available width instead of a fixed 1421px width.
- 09 / 25: retain confirmed Round 2 CEO message and publication content.
- 14 / 20 / 21: exact supplied partnership, architecture and English PRISM copy.
- N3: four core-technology validations followed by four revised industry projects; research / NCIA / publications retained.
- N4: canonical human-facing names ASTOP and AXIOM Tensor, including current Knowledge Core summaries and answer instructions. Historical original research files and code identifiers are preserved.

The notice and three request HTML references contain Korean only despite the document describing bilingual references. Exact English document copy is used where provided; remaining interface wording is translated consistently for client review.

## Release procedure

Merge and deploy backend plus worker first to retire native website intake and queued mail. Then deploy web and dashboard. Confirm each service runs the merged commit. Do not run an old deployment's code for ingestion.

No new environment variables or database migrations are introduced. `WEBSITE_NATIVE_OPERATIONS_ENABLED` is deliberately false in application settings; old website intake and Turnstile settings cannot re-enable the retired workflows. Existing customer-authentication email settings remain required. The DigitalOcean proxy, DNS, certificates and renewal timer need no change.

Forms (same for Korean and English):
- PoC: https://forms.gle/FoGcs7LHhoTbmhtf8
- Contact: https://forms.gle/PCW2J9SF4wjDcPtA6
- Partnership: https://forms.gle/aACxKK1oggHiA8ueA

Authorized staff must use the company Google Forms account for review. Confirm that each form accepts responses and its sharing permissions are correct before release; changing external Google Forms settings is outside these repository changes.

## Knowledge Core refresh

After the new backend is deployed, enter its production container using Railway SSH and run:

```sh
python manage.py register_knowledge_docs --dry-run
python manage.py register_knowledge_docs
python manage.py sync_hard_facts
python manage.py sync_evidence_metadata
python manage.py reingest_namespace --all --dry-run
```

Inspect the reconciliation report before running the write operation. It must retain unrelated active documents:

```sh
python manage.py reingest_namespace --all
python manage.py validate_knowledge_core
```

No credentials belong in these commands or commits. Existing embedding / vector-index credentials are used by the deployed backend.

## Manual acceptance

Check all three inquiry pages in KO and EN: external button, correct form, two other-request links, no inline form or CAPTCHA. Verify mobile language switching changes assistant guidance and request locale. Confirm homepage notice qualifies savings and hides for today; ASTOP logs finish at 10 and 1 with reduced motion. Check home contact at phone/tablet/desktop widths. Old website admin and sign-in pages must show the retirement message; old admin API and intake return 410. Confirm normal customer sign-in and conversation remain available.
