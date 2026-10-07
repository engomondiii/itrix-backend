# Knowledge Core — October 2026

The active corpus contains 31 documents. This README is outside the disclosure folders and is not ingested. Folder names govern retrieval disclosure; they do not make a public Git repository private.

## Current sources

| Subject | Active source | Scope |
| --- | --- | --- |
| Product catalogue and maturity | public/itrix_product_portfolio_v1_4.md | Four offerings; stages do not imply general availability |
| ASTOP behavior, evidence and access | public/astop_product_and_access_20261002.md | New finite-panel evidence, separate retail/enterprise routes |
| Discovery through install and feedback | public/astop_customer_journey_v1_6.md | Seven-day trial, annual membership and renewal; approved LO required |
| Pricing, seats, acceptance, refunds | public/astop_membership_terms_20261007.md | Curated summary, never a substitute for the exact accepted order |
| Referral eligibility and rewards | public/astop_branch_program_summary_v1_4.md | Separate approved agreement; incomplete draft cannot launch |
| Comparison with caching/harness tools | public/astop_comparison_current_20261003.md | September comparison context, October evidence boundaries |
| Research overview | public/research_portfolio_summary_20261002.md | Public-safe portfolio distinctions |
| R01–R07 and QNTA evidence | controlled_public/research_evidence_register_20261003.md | Bounded results, negative evidence, application-not-grant language |
| Software protection | internal_only/astop_activation_policy_20261004.md | Integration/enforcement requirements; no keys or identity data |
| Platform governance | internal_only/platform_governance_current_20261003.md | Preserved acceptance controls and October commercial precedence |
| People | Existing Kang and Park DOCX files in public/ | Original bytes unchanged; 8 September verification boundary retained |

The older AXIOM, CRE and FQNM explanations, unified framework, workload/bottleneck material and platform operating guidance remain available in six revised editions. The Atelier Indigo DOCX and dated enterprise acceptance feedback DOCX remain unchanged, alongside the people profiles, research assets and other useful guides. Age alone is not a removal criterion.

The technical ASTOP synthesis and five retained process guides were corrected where they conflicted with October access, product or disclosure rules. Other useful, dated research and general guidance remains. The research register qualifies current interpretation of older research assets; it does not silently rewrite their authors' original findings.

## 5 October update

The condensed Customer Journey v1.5 now replaces the v1.2 journey derivative. It preserves the six stages, adds explicit platform recording of the Decide outcome, and delegates detailed mechanics to protection and contract authorities. The two earlier input audits remain historical snapshots. See [latest source audit](../docs/source_alignment_20261005.json) and [v1.5 rollout](../docs/document_alignment_20261005.md). The 31-source corpus remains selective; no confidential raw operating plan or customer feedback is published.

## 4 October update

Customer Journey v1.2 replaces the older journey derivative and updates activation, refund continuity and ordinary/enterprise routing. The protection derivative is renamed to identify the actual supplied authority, without claiming to have read the referenced but absent full Protection v1.6.1. The confidential operating plan stays outside public Git; only necessary nonconfidential routing and execution safeguards are reflected. The corpus still has 31 active sources. All other original and retained sources stay in place.

[Current change audit](../docs/source_alignment_20261004.json) records the two input hashes and changed corpus files. [Current rollout and limits](../docs/document_alignment_20261004.md) supersedes the earlier activation defaults. The 3 October cleanup audit below is a historical snapshot, not the hash inventory for this update.

## Physical cleanup and provenance

35 older files were physically removed from their previous paths: 28 are replaced or consolidated into current editions, and seven historical planning/checklist files are excluded from active retrieval. Thirteen current derivative documents were added and six retained guides edited in the cleanup follow-up. The three October summaries were already added in the initial branch change. No archive of retired files remains inside an ingestion folder. Git history retains previous versions.

[Cleanup audit](../docs/knowledge_cleanup_20261003.json) lists every removed path and original SHA-256, additions, modifications and the current corpus hashes. [Source audit](../docs/source_alignment_20261003.json) inventories the extracted older/new archive inputs with exact hashes. [Implementation and rollout](../docs/document_alignment_20261003.md) records precedence decisions and service prerequisites.

The new Markdown sources are explicitly curated derivatives. Raw confidential strategy, patent identifiers/personal data, protected QNTA mechanisms and unapproved complete contracts were not published. The optional exact-original importer uses approved private storage outside this public repository. Such storage is separate from the cleaned versioned corpus; importing originals is not required to retrieve the curated summaries. Private originals never replace current public domain summaries or automatically authorize disclosure.

## After merge: operator ingestion

Back up the intended database and vector index first. Apply migrations, then run:

```sh
python manage.py register_knowledge_docs
python manage.py sync_hard_facts
python manage.py sync_evidence_metadata
python manage.py reingest_namespace --all --dry-run
# Review the intended index and affected namespaces before the real reconciliation.
python manage.py reingest_namespace --all
python manage.py validate_knowledge_core
```

Use all-namespace reconciliation because retired sources occupied several namespaces, including historical/general ones. Merely ingesting new documents will not prove obsolete remote vectors are removed. Registration deactivates missing sources and removes their SQL chunks; retrieval rejects noncurrent rows even before remote cleanup. Run the grounding/answer checks described in the rollout guide afterwards. No production ingestion was performed while preparing this branch.

Merging is not permission to enable commercial services. Payment/tax, verification, signed builds/runtime activation, final legal releases and real payout operations require configuration and end-to-end validation; commerce remains disabled by default.

## 7 October update
Current journey is Discover → Enroll → 7-Day Trial & Prove → Join → Continue → Renew. The two old public journey/LO summaries are physically replaced; other sources are retained and only conflicting ASTOP access wording is amended. Prior audit sections describe historical snapshots. Confidential originals are not published. See docs/document_alignment_20261007.md for launch prerequisites and preserved legacy rights.
