"""
Review-chat service.

The single code path for a review-chat turn, shared by the REST endpoint
(POST review/sessions/{id}/chat/) and the review WebSocket consumer. It:

    1. resolves (or creates) the review conversation for the session,
    2. persists the visitor's inbound message,
    3. routes to the Concierge agent (governed) for a reply,
    4. persists the agent reply with its governance status,
    5. fans both out over the WS group (no-op when realtime is off).

It returns the agent reply message plus the deliverable body, so the REST endpoint can
answer synchronously even when realtime is disabled — the funnel works either way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from apps.conversations.services import fan_out, ingest
from apps.conversations.services.history import get_or_create_review_conversation

logger = logging.getLogger("itrix")


@dataclass
class ReviewChatResult:
    conversation_id: str
    reply: str
    suggest_nda: bool
    governance_status: str
    under_review: bool
    cited_chunk_ids: list


def handle_review_chat_turn(*, review_session_id: str, lead=None, body: str) -> ReviewChatResult:
    """Persist a review-chat turn and produce the Concierge reply."""
    from apps.leads.models import Lead

    if lead is None and review_session_id:
        lead = Lead.objects.filter(review_session_id=review_session_id).first()

    conv = get_or_create_review_conversation(review_session_id=review_session_id, lead=lead)

    # 1) persist the visitor turn + fan out
    inbound = ingest.ingest_inbound(conv, sender_kind="visitor", body=body)
    fan_out.broadcast_message(inbound)

    # 2) deterministic safety stops run BEFORE retrieval/model invocation.  Review chat is
    # another public entry point, so it must not bypass the same confidential-input / oracle
    # protections used by the main thread route.
    from apps.conversations.services import confidentiality, protected_probe, response_policy, terminology

    thread = getattr(conv, "thread", None)
    if thread is None and lead is not None:
        from apps.conversations.models_thread import Thread

        thread = Thread.objects.filter(lead=lead).order_by("-updated_at").first()
    locale = getattr(thread, "locale", "") or getattr(getattr(lead, "review_session", None), "locale", "en") or "en"

    intercept = confidentiality.detect(body)
    if intercept.sensitive:
        reply_text = confidentiality.safe_reply(locale=locale)
        reply_msg = ingest.ingest_agent_message(
            conv, agent_key="concierge", body=reply_text, governance_status="auto_approved",
            claim_level=0, meta={"policy_stop": "confidential_input"}, thread=thread,
        )
        fan_out.broadcast_message(reply_msg)
        return ReviewChatResult(
            conversation_id=str(conv.id), reply=reply_text, suggest_nda=False,
            governance_status="auto_approved", under_review=False, cited_chunk_ids=[],
        )

    if protected_probe.is_probe(body):
        if thread is not None:
            protected_probe.record(thread)
        reply_text = protected_probe.safe_reply(locale=locale)
        reply_msg = ingest.ingest_agent_message(
            conv, agent_key="concierge", body=reply_text, governance_status="auto_approved",
            claim_level=0, meta={"policy_stop": "protected_probe"}, thread=thread,
        )
        fan_out.broadcast_message(reply_msg)
        return ReviewChatResult(
            conversation_id=str(conv.id), reply=reply_text, suggest_nda=False,
            governance_status="auto_approved", under_review=False, cited_chunk_ids=[],
        )

    # 3) route to the Concierge (governed). Deterministic fallback when agents are off.
    from apps.agents.services.context import AgentContext, PLANE_PUBLIC
    from apps.agents.services.runtime import run_concierge

    ctx = AgentContext(
        lead_id=str(lead.id) if lead else None,
        prompt=getattr(getattr(lead, "review_session", None), "prompt", "") or body,
        pressures=list(getattr(getattr(lead, "review_session", None), "pressure_areas", []) or []),
        product_route=getattr(lead, "product_route", "general"),
        license_pathway=(
            lead.commercial_path if lead and getattr(lead, "commercial_path", "none") != "none" else None
        ),
        tier=getattr(lead, "tier", 4),
        plane=PLANE_PUBLIC,
        context_label="review",
        extra={"message": body},
    )
    out = run_concierge(ctx)
    payload = out.payload or {}
    reply_text = terminology.normalise_outbound(payload.get("reply", ""))
    reply_text = response_policy.enforce(reply_text, thread=thread)

    # 4) persist the agent reply with its governance status + fan out (governed).
    reply_msg = ingest.ingest_agent_message(
        conv,
        agent_key="concierge",
        body=reply_text,
        governance_status=out.governance_status,
        claim_level=out.claim_level,
        cited_chunk_ids=out.chunk_ids,
    )
    fan_out.broadcast_message(reply_msg)

    return ReviewChatResult(
        conversation_id=str(conv.id),
        reply=reply_text if reply_msg.is_deliverable else "",
        suggest_nda=bool(payload.get("suggestNda", False)),
        governance_status=out.governance_status,
        under_review=not reply_msg.is_deliverable,
        cited_chunk_ids=out.chunk_ids,
    )
