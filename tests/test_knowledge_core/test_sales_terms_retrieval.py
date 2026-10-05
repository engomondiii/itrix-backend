"""Customer terms survive semantic ranking without bypassing authorization."""
import pytest
from apps.ai_engine.services import knowledge_retriever as retriever
from apps.knowledge_core.models import KnowledgeChunk, KnowledgeDocument

pytestmark = pytest.mark.django_db
NAME = 'astop_license_order_summary_v2_6.md'


def make_chunk(name=NAME, text='Three environments; seven-day renewal; fourteen-day offline validity.', **metadata):
    values = dict(title=name, file_path=f'knowledge_docs/public/{name}', namespace='astop',
                  disclosure_level='public', source_authority='governing', is_current=True,
                  permitted_paraphrase='summary', approved_audience=['public', 'visitor'],
                  allowed_journey_stages=['PUBLIC-SAFE'])
    values.update(metadata)
    doc = KnowledgeDocument.objects.create(**values)
    return KnowledgeChunk.objects.create(document=doc, namespace=doc.namespace,
        disclosure_level=doc.disclosure_level, chunk_index=0, text=text, vector_id=str(doc.id))


def retrieve(query='ASTOP activation renewal', **kwargs):
    kwargs.setdefault('journey_stage', 'PUBLIC-SAFE')
    return retriever.KnowledgeRetriever().retrieve(query, **kwargs)


def test_current_terms_reach_context_even_when_vector_results_omit_them(settings, monkeypatch):
    settings.ENABLE_AI_ENGINE = True
    term = make_chunk()
    overview = make_chunk('overview.md', 'ASTOP is observation software.', source_authority='authoritative')
    monkeypatch.setattr(retriever.Embedder, 'embed_one', lambda *args: [0.1])
    monkeypatch.setattr(retriever.PineconeQueryClient, 'query', lambda *args, **kwargs: [
        {'id': overview.vector_id, 'score': 0.99}])
    result = retrieve(top_k=1)
    assert result[0]['document_id'] == str(term.document_id)
    assert 'seven-day' in result[0]['text']


def test_pricing_survives_customer_hard_fact_authority_filter(settings):
    settings.ENABLE_AI_ENGINE = False
    term = make_chunk(text='Five named seats cost USD 80, including with a referral.')
    make_chunk('overview.md', 'ASTOP customer purchase license.', source_authority='authoritative')
    assert retrieve('ASTOP customer license pricing', top_k=1)[0]['document_id'] == str(term.document_id)


@pytest.mark.parametrize('metadata,kwargs', [
    ({'is_current': False}, {}),
    ({'permitted_paraphrase': 'none'}, {}),
    ({'disclosure_level': 'internal_only'}, {}),
    ({'approved_audience': ['internal']}, {}),
    ({'allowed_journey_stages': ['LICENSED']}, {'journey_stage': 'PUBLIC-SAFE'}),
    ({'claim_ceiling': 5}, {'claim_ceiling': 1}),
    ({}, {'namespaces': ('company',)}),
])
def test_customer_terms_never_bypass_access_gates(settings, metadata, kwargs):
    settings.ENABLE_AI_ENGINE = False
    make_chunk(**metadata)
    assert retrieve(**kwargs) == []


def test_other_named_products_do_not_receive_astop_terms():
    assert retriever._customer_term_sources('What does QNTA Runtime cost?') == ()
    assert retriever._customer_term_sources('AXIOM Compute license pricing') == ()
    assert NAME in retriever._customer_term_sources('ASTOP license pricing')
    assert NAME in retriever._customer_term_sources('ASTOP 가격과 활성화 갱신')


def test_real_ingested_sections_keep_activation_and_pricing_in_small_context(settings):
    from pathlib import Path
    from apps.knowledge_core.services.chunker import chunk_text
    settings.ENABLE_AI_ENGINE = False
    root = Path(__file__).resolve().parents[2] / 'knowledge_docs/public'
    for name in (NAME, 'astop_customer_journey_v1_5.md'):
        first = make_chunk(name)
        doc = first.document
        first.delete()
        for chunk in chunk_text((root / name).read_text()):
            KnowledgeChunk.objects.create(document=doc, namespace='astop', disclosure_level='public',
                chunk_index=chunk.index, heading=chunk.heading, text=chunk.text,
                vector_id=f'{doc.id}:{chunk.index}')
    activation = ' '.join(c['text'] for c in retrieve(
        'ASTOP three computers fourth environment replacement renewal interval offline validity expiry workload content', top_k=5))
    assert 'seven days' in activation
    assert 'fourteen days' in activation
    assert 'not workload content' in activation
    pricing = ' '.join(c['text'] for c in retrieve(
        'ASTOP individual and organization five named users price total Branch referral discounts stack customer license', top_k=5))
    assert 'Five organization seats cost USD 80' in pricing
    assert 'USD 18 with an eligible Branch referral' in pricing
