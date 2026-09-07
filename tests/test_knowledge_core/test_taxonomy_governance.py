"""September-2026 product taxonomy and Knowledge source-governance regressions."""
from __future__ import annotations

from pathlib import Path

from apps.ai_engine.services.knowledge_retriever import _domain_rank, _query_claim_domains
from apps.knowledge_core.canonical_taxonomy import PRODUCT_NAMES, TECHNOLOGIES, prompt_block
from apps.knowledge_core.management.commands.register_knowledge_docs import source_authority_for
from apps.knowledge_core.management.commands.validate_knowledge_core import current_public_conflicts
from apps.knowledge_core.source_manifest import ClaimDomain, policy_for

ROOT = Path(__file__).resolve().parents[2]


def test_canonical_entity_types_are_deterministic():
    assert PRODUCT_NAMES == ("ASTOP", "ALPHA Compute", "ALPHA Core")
    assert TECHNOLOGIES == ("PRISM", "AXIOM", "AXIOM-TENSOR", "CRE", "FQNM", "QNTA")
    block = prompt_block()
    assert "PRODUCTS — the complete currently sold product catalogue" in block
    assert "ASTOP" in block and "ALPHA Compute" in block and "ALPHA Core" in block
    assert "these are NOT separately sold products" in block


def test_current_v35_canonical_is_current_and_old_v24_is_explicitly_noncurrent():
    current = policy_for("itrix_product_canonical_v3_5.md")
    old = policy_for("itrix_product_canonical_v2_4.md")
    assert current is not None and current.current is True and current.authority == "authoritative"
    assert ClaimDomain.TAXONOMY in current.claim_domains
    assert old is not None and old.current is False and old.authority == "legacy"
    assert old.superseded_by == "itrix_product_canonical_v3_5.md"


def test_filename_word_canonical_does_not_grant_authority():
    authority, current, rule = source_authority_for("made_up_canonical_notes.md")
    assert (authority, current, rule) == ("working", True, "")


def test_claim_domain_precedence_prefers_taxonomy_source_for_product_question():
    domains = _query_claim_domains("What products does itriX sell?")
    assert ClaimDomain.TAXONOMY in domains
    taxonomy = {"claim_domains": [ClaimDomain.TAXONOMY]}
    unrelated = {"claim_domains": [ClaimDomain.LEGAL]}
    unclassified = {"claim_domains": []}
    assert _domain_rank(taxonomy, domains) > _domain_rank(unclassified, domains)
    assert _domain_rank(unclassified, domains) > _domain_rank(unrelated, domains)


def test_current_public_canonical_contains_all_products_and_separates_technologies():
    text = (ROOT / "knowledge_docs/public/itrix_product_canonical_v3_5.md").read_text()
    for product in PRODUCT_NAMES:
        assert product in text
    for technology in TECHNOLOGIES:
        assert technology in text
    assert "They are not separately sold products" in text
    assert current_public_conflicts(text) == []


def test_validator_detects_positive_obsolete_public_doctrine():
    cases = {
        "itriX currently has only two products: ALPHA Compute and ALPHA Core.": "two-product public catalogue",
        "The complete products are ALPHA Compute and ALPHA Core.": "complete product catalogue omits ASTOP",
        "Products are AXIOM, CRE and ALPHA Compute.": "technology classified as sold product",
        "ASTOP is self-service for public visitors.": "ASTOP self-service claim",
        "Choose ASTOP Pro for $499 per month.": "obsolete ASTOP tier model",
        "ASTOP checkout lets you buy the product online.": "ASTOP public checkout",
        "Public visitors can download the ASTOP production binary.": "public unrestricted executable access",
        "ASTOP includes a money-back guarantee.": "obsolete money-back guarantee",
    }
    for text, expected in cases.items():
        assert expected in current_public_conflicts(text), text


def test_validator_allows_negative_current_boundaries():
    text = (
        "ASTOP is not self-service. Do not expose public $499 pricing. "
        "Public visitors cannot download production binaries. "
        "There is no public checkout and no money-back guarantee."
    )
    assert current_public_conflicts(text) == []


def test_historical_sales_sources_are_explicitly_noncurrent():
    for name in (
        'Project Playbook_Ai Sales Platform for ITrix.docx',
        'Kickoff Direction for the itriX Project.docx',
        'itriX AI Sales Engine MVP Functional Specification_V1.0.docx',
    ):
        policy = policy_for(name)
        assert policy is not None and policy.current is False and policy.authority == 'legacy'


def test_ingest_command_excludes_noncurrent_sources(db, monkeypatch):
    from django.core.management import call_command
    from apps.knowledge_core.models import KnowledgeDocument
    from apps.knowledge_core.management.commands import ingest_documents

    current = KnowledgeDocument.objects.create(
        title='current', file_path='knowledge_docs/public/current.md', namespace='company',
        disclosure_level='public', is_current=True, ingestion_status='PENDING'
    )
    KnowledgeDocument.objects.create(
        title='old', file_path='knowledge_docs/public/old.md', namespace='company',
        disclosure_level='public', is_current=False, ingestion_status='PENDING'
    )
    seen = []
    class R:
        ok=True; chunk_count=1; error=''
    def fake(doc, dry_run=False):
        seen.append(doc.pk)
        return R()
    monkeypatch.setattr(ingest_documents, 'ingest_document', fake)
    call_command('ingest_documents')
    assert seen == [current.pk]


def test_noncurrent_source_is_inert_on_registration_and_direct_ingest_refuses_it(db, tmp_path, monkeypatch):
    """Superseded rows must stay auditable without ever becoming ingestible again."""
    import pytest
    from django.core.management import call_command
    from django.core.management.base import CommandError
    from apps.knowledge_core.models import KnowledgeChunk, KnowledgeDocument
    from apps.knowledge_core.management.commands import ingest_documents, register_knowledge_docs

    public = tmp_path / 'public'
    public.mkdir(parents=True)
    source = public / 'historical_product_notes.md'
    source.write_text('Historical two-product doctrine retained only for audit history.', encoding='utf-8')

    doc = KnowledgeDocument.objects.create(
        title='historical product notes',
        file_path=source.as_posix(),
        namespace='company',
        disclosure_level='public',
        is_current=True,
        ingestion_status='PENDING',
        chunk_count=1,
    )
    KnowledgeChunk.objects.create(
        document=doc,
        namespace='company',
        disclosure_level='public',
        chunk_index=0,
        text='stale two-product chunk',
        token_estimate=4,
    )

    monkeypatch.setattr(
        register_knowledge_docs,
        'source_authority_for',
        lambda _name: ('legacy', False, 'Superseded test source.'),
    )
    call_command('register_knowledge_docs', '--base', str(tmp_path))

    doc.refresh_from_db()
    assert doc.is_current is False
    assert doc.ingestion_status == 'COMPLETE'
    assert doc.chunk_count == 0
    assert doc.chunks.count() == 0

    seen = []

    class Result:
        ok = True
        chunk_count = 1
        error = ''

    def fake_ingest(candidate, dry_run=False):
        seen.append(candidate.pk)
        return Result()

    monkeypatch.setattr(ingest_documents, 'ingest_document', fake_ingest)
    call_command('ingest_documents')
    assert doc.pk not in seen

    with pytest.raises(CommandError, match='non-current/superseded'):
        call_command('ingest_documents', '--document-id', str(doc.pk))

    # A later ordinary registration/ingestion cycle must not resurrect chunks.
    call_command('register_knowledge_docs', '--base', str(tmp_path))
    call_command('ingest_documents')
    doc.refresh_from_db()
    assert doc.is_current is False
    assert doc.ingestion_status == 'COMPLETE'
    assert doc.chunk_count == 0
    assert doc.chunks.count() == 0
    assert doc.pk not in seen


def test_ingestion_service_keeps_noncurrent_document_inert(db, monkeypatch):
    """Defense in depth: direct service callers cannot resurrect a superseded source."""
    from apps.knowledge_core.models import KnowledgeChunk, KnowledgeDocument
    from apps.knowledge_core.services import ingestion_pipeline

    doc = KnowledgeDocument.objects.create(
        title='old direct-service source',
        file_path='knowledge_docs/public/old-direct.md',
        namespace='company',
        disclosure_level='public',
        is_current=False,
        ingestion_status='PENDING',
        chunk_count=1,
    )
    KnowledgeChunk.objects.create(
        document=doc,
        namespace='company',
        disclosure_level='public',
        chunk_index=0,
        text='obsolete chunk',
        token_estimate=2,
        vector_id='old-vector-id',
    )

    deleted = []

    class FakeUpserter:
        def delete_ids(self, *, namespace, ids):
            deleted.append((namespace, list(ids)))
            return True

    monkeypatch.setattr(ingestion_pipeline, 'PineconeUpserter', FakeUpserter)

    result = ingestion_pipeline.ingest_document(doc)
    doc.refresh_from_db()

    assert result.ok is True
    assert result.chunk_count == 0
    assert deleted == [('company', ['old-vector-id'])]
    assert doc.is_current is False
    assert doc.ingestion_status == 'COMPLETE'
    assert doc.chunk_count == 0
    assert doc.chunks.count() == 0


def test_general_audience_includes_public_visitor_sources_without_widening_customer_only():
    from apps.ai_engine.services.knowledge_retriever import _audience_allowed

    assert _audience_allowed(['public', 'visitor', 'customer'], 'general') is True
    assert _audience_allowed(['visitor'], 'general') is True
    assert _audience_allowed(['customer'], 'general') is False
    assert _audience_allowed(['internal'], 'general') is False


def test_alpha_product_names_are_taxonomy_queries_for_source_precedence():
    domains = _query_claim_domains('Does ALPHA Compute require ALPHA Core?')
    assert ClaimDomain.TAXONOMY in domains
    assert ClaimDomain.PUBLIC_EXPLANATION in domains
