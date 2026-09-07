"""Conversation -> READY My Review bridge.

A concrete, consented Customer/Strategic Customer assessment may create a Lead and start
My Review generation only after the numbered journey has reached DIAGNOSED, the canonical
STR-03 Problem Mirror is confirmed/deliberately skipped, and an explicitly selected action
genuinely requires identity.  Account presence, seniority, company, conversation depth, or a
volunteered email never promote the relationship or trigger a review.

Generation is asynchronous and durable: ``maybe_reveal_client_page`` starts a PENDING review
without minting any browser credential.  ``finalize_ready_review`` runs only after a complete
schema-valid ResultPage is persisted READY, then mints a short-lived browser-bound one-time
exchange code.  The code is broadcast in the realtime reveal event and must be exchanged
through the Next.js BFF for an opaque httpOnly access-session cookie.  No bearer credential or
internal identifier belongs in a URL or assistant prose.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("itrix")

# Company is captured opportunistically. Deliberately permissive: capturing a
# slightly-off company string (which the operator can correct) is better than
# missing a real one — and it NEVER blocks the reveal, so a miss is harmless.
_COMPANY_PATTERNS = (
    re.compile(r"(?:our\s+)?(?:company|org(?:ani[sz]ation)?|employer|firm|startup)\s*(?:name)?\s*(?:is|:|=|named|called)?\s*([A-Z0-9][\w&.\- ]{1,60})", re.IGNORECASE),
    re.compile(r"(?:i(?:'m| am)\s+(?:from|with|at)|we(?:'re| are)\s+(?:from|at)|work(?:ing)?\s+(?:for|at))\s+([A-Z0-9][\w&.\- ]{1,60})", re.IGNORECASE),
    # The direct answer to the contact ask, which names both details in one line:
    # "GPSLAB, engomondiii@gmail.com". Anchored to the start of the message and
    # required to be immediately followed by the address, so it cannot fire
    # mid-sentence; courtesy openers ("Sure, ...", "Thanks, ...") are excluded
    # because they are assent, not an organisation.
    re.compile(
        r"^\s*(?!(?i:sure|yes|yeah|yep|ok(?:ay)?|thanks|thank you|hi|hello|hey|"
        r"here|please|alright|great|perfect)\b)"
        r"([A-Z0-9][\w&.\- ]{1,60}?)\s*[,;:\u2013\u2014-]\s*[\w.+-]+@"
    ),
)
_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# A name the visitor commonly gives with their email; captured for the Lead record.
# The name words are matched case-SENSITIVELY (real names are capitalised) so lowercase
# connectors like "and"/"my" are not swept in; the trigger phrase stays case-insensitive.
_NAME_PATTERN = re.compile(r"(?:[Mm]y name is|[Ii](?:'m| am)|[Tt]his is|[Nn]ame\s*[:=])\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")


def extract_contact_from_text(text: str) -> dict:
    """Pull name / company / email from ONE piece of text (all optional)."""
    result = {"email": "", "company": "", "name": ""}
    if not (text or "").strip():
        return result

    m = _EMAIL_PATTERN.search(text)
    if m:
        try:
            from apps.core.validators import validate_email_address

            result["email"] = validate_email_address(m.group(0))
        except Exception:  # noqa: BLE001 - an invalid address is simply not captured
            result["email"] = ""

    for pattern in _COMPANY_PATTERNS:
        cm = pattern.search(text)
        if cm:
            company = cm.group(1).strip().strip(".,;")
            company = re.split(
                r"\s+and\s+|\s+contact\s+|\s+email\s+|\s+my\s+",
                company, maxsplit=1, flags=re.IGNORECASE,
            )[0].strip()
            if company and "@" not in company and company.lower() not in {"is", "name"}:
                result["company"] = company[:200]
                break

    nm = _NAME_PATTERN.search(text)
    if nm:
        name = nm.group(1).strip()
        # Stop at a trailing "and ... / my ... / email ..." clause the pattern can over-capture.
        name = re.split(r"\s+and\s+|\s+my\s+|\s+email\s+|\s+contact\s+", name, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        # Guard against capturing "am from GPSLAB" style false hits.
        if name and "@" not in name and name.lower() not in {"am", "is", "from", "with", "at"}:
            result["name"] = name[:200]

    return result


def accumulated_contact(thread, *, extra_text: str = "") -> dict:
    """
    Build contact from EVERY visitor turn on the thread, plus optional extra text.

    This is the fix for the single-turn bug: an email given in one message and a
    company given in another are merged here. First non-empty value for each field
    wins (the earliest clear statement), so a later vague turn cannot overwrite a
    clear earlier one.
    """
    merged = {"email": "", "company": "", "name": ""}

    # ── AN ACCOUNT ALREADY TOLD US (fix, 2026-08-12) ─────────────────────────
    # A signed-in customer starting a conversation was being asked for their work
    # email and organisation — details their own account holds. Worse, until they
    # typed them into the chat the reveal stayed blocked on `no_email_yet`, so the
    # ask repeated and the page never arrived. The account is seeded FIRST, so it
    # wins over anything parsed out of the text: for an authenticated customer the
    # address on the account is the authoritative one, and a stray address quoted
    # mid-conversation ("our vendor is x@y.com") must not displace it.
    #
    # Anonymous threads are unaffected — there is no client, so nothing is seeded
    # and the behaviour is exactly as before.
    client = getattr(thread, "client", None) if thread is not None else None
    if client is not None:
        merged["email"] = (getattr(client, "email", "") or "").strip()
        merged["company"] = (getattr(client, "organization", "") or "").strip()
        merged["name"] = (getattr(client, "full_name", "") or "").strip()

    texts: list[str] = []
    if thread is not None:
        try:
            from apps.conversations.models import Message

            rows = (
                Message.objects.filter(thread=thread, sender_kind__in=["visitor", "client"])
                .order_by("seq", "created_at")
            )
            texts = [m.body or "" for m in rows]
        except Exception:  # noqa: BLE001
            texts = []
    if extra_text:
        texts.append(extra_text)

    for text in texts:
        found = extract_contact_from_text(text)
        for key in merged:
            if not merged[key] and found[key]:
                merged[key] = found[key]
    return merged


# Back-compat alias: the previous single-turn extractor name, now whole-text.
def extract_contact(text: str) -> dict:
    c = extract_contact_from_text(text)
    return {"email": c["email"], "company": c["company"]}


def maybe_reveal_client_page(thread, body: str) -> dict:
    """
    Close the conversation-to-review loop without navigating to a partial page.

    Once the qualification band is complete and an identity-dependent action has
    legitimately produced an email address, create/attach the durable Lead and
    start My Review generation.  The journey remains at DIAGNOSED while generation
    is PENDING.  ``finalize_ready_review`` performs the actual 3 -> 4 reveal only
    after a complete, schema-valid ResultPage has been persisted as READY.

    The function is deliberately idempotent: if a Lead already exists it simply
    reports the durable generation state and never issues a second reveal.
    """
    out = {
        "revealed": False,
        "token": None,
        "url": None,
        "company": "",
        "name": "",
        "reason": "",
        "generation_status": None,
    }
    if thread is None:
        out["reason"] = "no_thread"
        return out

    from apps.conversations.services import thread_state

    # Existing Lead means an earlier turn already started the durable review.
    if getattr(thread, "lead_id", None):
        try:
            from apps.result_page.models import ResultPage

            page = ResultPage.objects.filter(lead_id=thread.lead_id).first()
            out["generation_status"] = getattr(page, "generation_status", None)
            out["reason"] = "review_ready" if out["generation_status"] == ResultPage.GenerationStatus.READY else "review_preparing"
        except Exception:  # noqa: BLE001
            out["reason"] = "already_has_lead"
        return out

    # Value and the strategic confirmation gate must already have closed.
    if thread_state.current_state_number(thread) < 3:
        out["reason"] = "not_diagnosed"
        return out

    relationship = (getattr(thread, "relationship_state", "") or "").lower()
    if relationship not in {"customer", "strategic_customer"}:
        out["reason"] = "not_customer"
        return out
    if (getattr(thread, "mirror_status", "") or "").lower() not in {"confirmed", "skipped"}:
        out["reason"] = "mirror_not_confirmed"
        return out

    # Identity is requested only for an explicitly identity-dependent action.
    if not (getattr(thread, "identity_needed_action", "") or "").strip():
        out["reason"] = "identity_not_needed"
        return out

    contact = accumulated_contact(thread, extra_text=body or "")
    out["company"] = contact["company"]
    out["name"] = contact["name"]
    if not contact["email"]:
        out["reason"] = "no_email_yet"
        return out

    try:
        lead = _create_conversation_lead(thread, contact)
    except Exception:  # noqa: BLE001
        logger.exception("conversation lead creation failed for thread %s", getattr(thread, "id", "?"))
        out["reason"] = "lead_create_failed"
        return out

    try:
        from apps.review.services.qualification_processor import kick_off_result_page

        kick_off_result_page(lead, finalize_conversation=True)
    except Exception:  # noqa: BLE001
        logger.exception("could not start My Review for lead %s", getattr(lead, "id", "?"))
        out["reason"] = "review_start_failed"
        return out

    out.update({"reason": "review_preparing", "generation_status": "pending"})
    logger.info("My Review generation started from conversation for thread %s (lead %s)", thread.id, lead.id)
    return out


def finalize_ready_review(lead) -> dict:
    """Reveal a completed My Review to its originating conversation, once.

    This is called by the asynchronous generation worker *after* ResultPage has
    passed complete-schema validation and been persisted as READY.  It therefore
    cannot expose a partial artifact.  The access code is browser/session-bound
    by ``reveal_client_page(..., thread=thread)`` and is only a one-time exchange
    code, not the durable review credential itself.
    """
    from apps.conversations.models import Thread
    from apps.conversations.services import thread_state
    from apps.journey.services.advance import reveal_client_page
    from apps.result_page.models import ResultPage

    page = ResultPage.objects.filter(lead=lead).first()
    if page is None or page.generation_status != ResultPage.GenerationStatus.READY:
        return {"revealed": False, "reason": "not_ready"}

    thread = Thread.objects.filter(lead=lead).order_by("-updated_at").first()
    if thread is None:
        return {"revealed": False, "reason": "no_thread"}

    # Already mirrored to State 4: do not mint/rebroadcast a second access grant.
    if thread_state.current_state_number(thread) >= 4:
        return {"revealed": False, "reason": "already_revealed"}

    result = reveal_client_page(
        lead,
        meta={"source": "conversation_review_ready", "thread_id": str(thread.id)},
        thread=thread,
    )
    reveal = getattr(result, "reveal", None) or {}
    token = reveal.get("access_code") if isinstance(reveal, dict) else None

    try:
        thread_state._mirror_onto_thread(thread, "CLIENT_PAGE")
    except Exception:  # noqa: BLE001
        logger.debug("could not mirror CLIENT_PAGE onto thread %s", thread.id, exc_info=True)

    _broadcast_reveal_to_thread(thread, reveal if isinstance(reveal, dict) else {}, token)
    logger.info("READY My Review revealed to conversation thread %s (lead %s)", thread.id, lead.id)
    return {
        "revealed": True,
        "access_code": token,
        "url": None,
        "reason": "revealed",
    }

def _safe_visitor_turns(thread) -> list[str]:
    """Conversation source for downstream lead/review artifacts; confidential turns fail closed."""
    from apps.conversations.models import Message
    from apps.conversations.services.confidentiality import detect

    rows = Message.objects.filter(
        thread=thread, sender_kind__in=["visitor", "client"]
    ).order_by("seq", "created_at")
    out: list[str] = []
    for row in rows:
        text = " ".join((row.body or "").split()).strip()
        if not text:
            continue
        try:
            if detect(text).sensitive:
                continue
        except Exception:
            continue
        out.append(text)
    return out


def _create_conversation_lead(thread, contact: dict):
    """Create the internal subject from the full safe state, never just the first turn."""
    from django.db import transaction

    from apps.leads.models import Lead, LeadActivity, LeadSource
    from apps.review.models import ReviewSession

    turns = _safe_visitor_turns(thread)
    corpus = "\n".join(turns)[:8000]
    latest_context = " ".join(turns[-4:])[:1200] if turns else ""
    action = getattr(thread, "selected_action", "") or ""
    evaluation = getattr(thread, "evaluation_type", "") or ""
    mirror_status = getattr(thread, "mirror_status", "") or ""

    with transaction.atomic():
        session = ReviewSession.objects.create(
            client_id="",
            visitor_type="conversation",
            status=ReviewSession.Status.QUALIFIED,
            # Compatibility field now carries a bounded safe conversation synopsis;
            # Result generation still reads the durable Thread as authoritative.
            prompt=corpus[:2000],
        )

        lead = Lead.objects.create(
            review_session=session,
            lead_source=LeadSource.CONVERSATION,
            visitor_name=contact.get("name", "") or "",
            company=contact.get("company", "") or "",
            email=contact["email"],
            product_route="undetermined",
            tier=4,
            score=0,
            journey_state="DIAGNOSED",
            compute_bottleneck=latest_context[:500],
            recommended_next_step=(
                f"Carry out explicitly selected action: {action}." if action
                else "No identity-dependent next action is selected."
            ),
        )

        LeadActivity.objects.create(
            lead=lead,
            type=LeadActivity.ActivityType.SUBMISSION,
            label="Lead created from governed conversation — My Review generation pending.",
            meta={
                "source": "conversation",
                "thread_id": str(thread.id),
                "relationship_state": getattr(thread, "relationship_state", "visitor"),
                "mirror_status": mirror_status,
                "selected_action": action,
                "evaluation_type": evaluation,
                "safe_turn_count": len(turns),
            },
        )

        _attach_thread_to_lead(thread, lead)

    return lead


def _attach_thread_to_lead(thread, lead) -> None:
    thread.lead = lead
    thread.save(update_fields=["lead", "updated_at"])

    conversation = getattr(thread, "conversation", None)
    if conversation is not None and getattr(conversation, "lead_id", None) != lead.id:
        try:
            conversation.lead = lead
            conversation.save(update_fields=["lead", "updated_at"])
        except Exception:  # noqa: BLE001
            logger.debug("could not attach conversation to lead for thread %s", getattr(thread, "id", "?"))


def _broadcast_reveal_to_thread(thread, reveal: dict, token) -> None:
    """
    Push ``journey.reveal`` + a shell update to the THREAD's socket group.

    The anonymous visitor is subscribed to the thread group, not a lead group, so
    the reveal ``advance`` emitted to the lead group would not reach them. Re-emit
    here so an open transcript can react (and navigate) live.
    """
    try:
        from apps.conversations.services.fan_out import (
            broadcast_reveal,
            broadcast_shell_update,
        )
        from apps.journey.services import shell

        payload = {
            "state": reveal.get("state", "CLIENT_PAGE"),
            "surface": reveal.get("surface", "client_page"),
            "access_code": token,
            "value_delivered": True,
        }
        broadcast_reveal(thread.group_name, payload)

        contract = (
            shell.for_subject(thread.lead, thread=thread)
            if getattr(thread, "lead_id", None)
            else shell.for_anonymous_thread(thread)
        )
        broadcast_shell_update(thread.group_name, contract)
    except Exception:  # noqa: BLE001 - realtime must never break the turn
        logger.debug("reveal fan-out to thread group failed for thread %s", getattr(thread, "id", "?"))


def _client_page_url(_token: str) -> str:
    """Retired: My Review URLs are credential-free."""
    return "/c"


def _first_visitor_turn(thread) -> str:
    turns = _safe_visitor_turns(thread)
    return turns[0] if turns else ""
