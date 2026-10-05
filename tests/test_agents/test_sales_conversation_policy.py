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
                 'never bypass identity', 'Do not request identity/contact on your own',
                 'Respect no-fit, stop, refusal', 'Never hide a material unresolved term',
                 'Activation renewal is not subscription', 'Signing keys are never customer deliverables'):
        assert rule in prompt


def test_public_terms_remove_obsolete_prices_and_explain_correct_discount():
    root = Path(__file__).resolve().parents[2] / 'knowledge_docs/public'
    access = (root / 'astop_product_and_access_20261002.md').read_text()
    assert 'USD 19' not in access and 'twelve-download' not in access
    terms = (root / 'astop_license_order_summary_v2_6.md').read_text()
    assert 'Five organization seats cost USD 80' in terms
    assert 'USD 18 with an eligible Branch referral' in terms
    assert 'three' in terms.lower() and 'seven days' in terms and 'fourteen days' in terms
    assert 'not workload content' in terms
