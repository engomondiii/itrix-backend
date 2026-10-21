"""Shared prompt policy for the observed customer-chat regressions."""
from pathlib import Path
from apps.ai_engine.services.system_prompt_builder import build_conversation_system_prompt
from apps.agents.services.concierge import (
    _CONCIERGE_SHARED_INSTRUCTION, _CONCIERGE_INSTRUCTION, _CONCIERGE_STREAM_INSTRUCTION,
)


def test_streaming_and_json_have_the_same_sales_and_evidence_instructions():
    for instruction in (_CONCIERGE_INSTRUCTION, _CONCIERGE_STREAM_INSTRUCTION):
        assert instruction.startswith(_CONCIERGE_SHARED_INSTRUCTION)
        assert 'no benchmark numbers' not in instruction
        assert 'guaranteed customer savings' in instruction
        assert 'one relevant next step' in instruction


def test_sales_prompt_keeps_gates_and_adds_customer_specific_next_steps():
    prompt = build_conversation_system_prompt(product_route='astop', license_pathway=None,
        tier=1, pressures=[], chunks=[])
    for rule in ('ONE useful next step', 'never repeat a seat-count',
                 'Do not request identity/contact on your own',
                 'Respect no-fit, stop, refusal', 'Never hide a material unresolved term',
                 'Never link a Store without verified live configuration',
                 'implementation details are never customer deliverables'):
        assert rule in prompt


def test_public_terms_use_current_store_prices_and_preserve_historical_rights():
    root = Path(__file__).resolve().parents[2] / 'knowledge_docs/public'
    access = (root / 'astop_product_and_access_20261002.md').read_text()
    assert 'USD 19' not in access and 'twelve-download' not in access
    terms = (root / 'astop_store_terms_20261019.md').read_text()
    assert 'USD 10 per month or USD 100 per year' in terms
    assert 'does not sell or distribute ASTOP directly' in terms
    assert 'confirms each relevant listing is live' in terms
    assert "accepted terms and payment history must not be rewritten" in terms
    assert not (root / 'astop_membership_terms_20261007.md').exists()
