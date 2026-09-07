from io import StringIO

from django.core.management import call_command

from apps.agents.services.concierge import ConciergeAgent
from apps.agents.services.output_contract import AgentOutput
from apps.ai_engine.services.knowledge_retriever import KnowledgeRetriever
from apps.knowledge_core.models import HardFact, KnowledgeDocument


def test_verify_ai_answer_accepts_current_hard_fact_grounding(db, monkeypatch):
    document = KnowledgeDocument.objects.create(
        title="itrix product canonical v3 5",
        file_path="knowledge_docs/public/itrix_product_canonical_v3_5.md",
        namespace="company",
        disclosure_level="public",
        source_authority="authoritative",
        is_current=True,
        ingestion_status="COMPLETE",
    )

    fact = HardFact.objects.create(
        key="test-current-product-catalogue",
        category=HardFact.Category.CORPORATE,
        public_statement=(
            "itriX currently has three products: ASTOP, ALPHA Compute and ALPHA Core."
        ),
        source_reference=(
            "knowledge_docs/public/itrix_product_canonical_v3_5.md"
        ),
        source_document=document,
        source_authority="authoritative",
        is_current=True,
        disclosure_level="public",
        approved_audience=["public", "visitor", "general"],
        claim_ceiling=1,
    )

    captured = {}

    def fake_run_ai(self, ctx):
        captured["extra"] = dict(ctx.extra or {})
        return AgentOutput(
            payload={
                "reply": (
                    "itriX sells ASTOP, ALPHA Compute and ALPHA Core."
                )
            },
            chunk_ids=[f"hard-fact:{fact.id}"],
            used_ai=True,
            claim_level=1,
        )

    monkeypatch.setattr(ConciergeAgent, "run_ai", fake_run_ai)

    out = StringIO()
    call_command(
        "verify_ai_answer",
        "--question",
        "What products does itriX sell?",
        stdout=out,
    )

    assert captured["extra"]["journey_state"] == "ARRIVED"
    assert captured["extra"]["audience"] == "general"
    assert "HARD-FACT" in out.getvalue()
    assert "CURRENT-CANONICAL" in out.getvalue()
    assert "PASS:" in out.getvalue()


def test_verify_rag_grounding_uses_arrived_public_context(monkeypatch):
    captured = {}

    def fake_retrieve(self, query, **kwargs):
        captured.update(kwargs)
        return [
            {
                "chunk_id": "vector-1",
                "text": (
                    "itriX currently has three products: "
                    "ASTOP, ALPHA Compute and ALPHA Core."
                ),
                "document_title": "itrix product canonical v3 5",
                "heading": "Current product catalogue",
                "namespace": "company",
                "canonical_priority": 100,
                "retrieval_backend": "pinecone",
                "score": 0.9,
            }
        ]

    monkeypatch.setattr(KnowledgeRetriever, "retrieve", fake_retrieve)

    out = StringIO()
    call_command(
        "verify_rag_grounding",
        "--question",
        "What products does itriX sell?",
        stdout=out,
    )

    assert captured["context"] == "public"
    assert captured["audience"] == "general"
    assert captured["journey_stage"] == "ARRIVED"
    assert "Pinecone-grounded chunks: 1/1" in out.getvalue()
    assert "Canonical/current chunks: 1/1" in out.getvalue()
