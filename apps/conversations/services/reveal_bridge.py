"""
The conversation -> client-page bridge (states 3 -> 4).

── WHAT THIS DOES ───────────────────────────────────────────────────────────
The conversational surface takes an anonymous visitor through the qualification
band (ARRIVED -> IN_REVIEW -> DIAGNOSED) but has no way past DIAGNOSED. The custom
"pitch room" the visitor is meant to receive is State 4 (CLIENT_PAGE), reached by
the ``reveal_client_page`` transition, which mints the ``/c/<token>`` capability
token. That transition, and the Lead it needs, only ever existed in the OLD
structured-form path. This bridge wires the conversation to that EXISTING reveal
machinery — it does not duplicate it.

── THE TWO THINGS THAT MADE THE FIRST VERSION FAIL ──────────────────────────
1. It read contact from the CURRENT TURN ONLY and required a company AND an email
   in that one message. Real visitors give their details across several turns
   ("my name is X and my email is Y" ... then later "our company is Z"), so the
   two pieces never coincided in one message and the reveal never fired.

   FIX: contact is accumulated across EVERY visitor turn on the thread, so details
   given in different messages combine.

2. It required a company at all. An email alone is enough to anchor a Lead and mint
   the page; a company enriches the record but is not essential.

   FIX: the trigger is EMAIL-ANCHORED. A valid email is sufficient; the company is
   captured when present but never blocks the reveal.

── WHAT IT DOES WHEN IT FIRES ───────────────────────────────────────────────
    1. creates a real Lead from the thread (lead_source=conversation, honest
       exploratory defaults — no fabricated Q1-Q9 score),
    2. attaches the captured contact,
    3. claims the anonymous thread onto that Lead so the conversation continues as
       the same thread,
    4. fires the EXISTING ``reveal_client_page`` transition (3 -> 4), minting the
       client-page token exactly as the form path does,
    5. broadcasts the reveal to the THREAD's socket group (the anonymous visitor is
       subscribed there) so the surface can navigate live, and returns the
       ``/c/<token>`` URL so the reply can present a link.

Idempotent and best-effort: a thread that already has a lead / already revealed is
a satisfied no-op, and any failure leaves the conversation working.
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
    If the conversation is ready, create the Lead and reveal the client page.

    Returns:
        {"revealed": bool, "token": str|None, "url": str|None,
         "company": str, "name": str, "reason": str}

    ``revealed`` is True only when THIS call performed the 3 -> 4 reveal. It is a
    no-op when the loop has not closed, no email has been given yet, the thread
    already has a lead, or the feature is unavailable.

    ── THE TRIGGER ──────────────────────────────────────────────────────────
    Gate 1: the qualification loop has closed (DIAGNOSED, state >= 3).
    Gate 2: an EMAIL has been given at any point in the conversation. Company and
            name are captured when present but do not gate the reveal.
    """
    out = {"revealed": False, "token": None, "url": None, "company": "", "name": "", "reason": ""}
    if thread is None:
        out["reason"] = "no_thread"
        return out

    if getattr(thread, "lead_id", None):
        out["reason"] = "already_has_lead"
        return out

    from apps.conversations.services import thread_state

    # Gate 1: value must have been delivered (loop closed).
    if thread_state.current_state_number(thread) < 3:
        out["reason"] = "not_diagnosed"
        return out

    # Gate 2: a valid email anywhere in the conversation (accumulated across turns).
    contact = accumulated_contact(thread, extra_text=body or "")
    out["company"] = contact["company"]
    out["name"] = contact["name"]
    if not contact["email"]:
        out["reason"] = "no_email_yet"
        return out

    try:
        lead = _create_conversation_lead(thread, contact)
    except Exception:  # noqa: BLE001 - never break the turn on lead creation
        logger.exception("conversation lead creation failed for thread %s", getattr(thread, "id", "?"))
        out["reason"] = "lead_create_failed"
        return out

    try:
        from apps.journey.services.advance import reveal_client_page

        result = reveal_client_page(lead, meta={"source": "conversation", "thread_id": str(thread.id)})
        reveal = getattr(result, "reveal", None) or {}
        token = reveal.get("capability_token") if isinstance(reveal, dict) else None
    except Exception:  # noqa: BLE001
        logger.exception("reveal_client_page failed for lead %s", getattr(lead, "id", "?"))
        out["reason"] = "reveal_failed"
        return out

    try:
        thread_state._mirror_onto_thread(thread, "CLIENT_PAGE")
    except Exception:  # noqa: BLE001
        pass

    url = _client_page_url(token) if token else None
    _broadcast_reveal_to_thread(thread, reveal if isinstance(reveal, dict) else {}, token)

    out.update({"revealed": True, "token": token, "url": url, "reason": "revealed"})
    logger.info("client page revealed from conversation for thread %s (lead %s)", thread.id, lead.id)
    return out


def _create_conversation_lead(thread, contact: dict):
    """
    Create a real Lead from an anonymous thread and claim the thread onto it.

    Honest exploratory defaults (general route, tier 4) rather than a fabricated
    Q1-Q9 score. Marked ``lead_source=conversation`` — exactly the case the model
    describes ("somebody described a problem and Layer 1 qualified them").
    """
    from django.db import transaction

    from apps.leads.models import Lead, LeadActivity, LeadSource
    from apps.review.models import ReviewSession

    first_turn = _first_visitor_turn(thread)

    with transaction.atomic():
        session = ReviewSession.objects.create(
            client_id="",
            visitor_type="conversation",
            status=ReviewSession.Status.QUALIFIED,
            prompt=first_turn[:2000],
        )

        lead = Lead.objects.create(
            review_session=session,
            lead_source=LeadSource.CONVERSATION,
            visitor_name=contact.get("name", "") or "",
            company=contact.get("company", "") or "",
            email=contact["email"],
            product_route="general",
            tier=4,
            score=0,
            journey_state="DIAGNOSED",
            compute_bottleneck=first_turn[:500],
            recommended_next_step="Client page revealed from conversation.",
        )

        LeadActivity.objects.create(
            lead=lead,
            type=LeadActivity.ActivityType.SUBMISSION,
            label="Lead created from conversation — contact captured, client page revealed.",
            meta={
                "source": "conversation",
                "thread_id": str(thread.id),
                "company": contact.get("company", ""),
                "name": contact.get("name", ""),
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
            "capability_token": token,
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


def _client_page_url(token: str) -> str:
    from django.conf import settings

    base = (
        getattr(settings, "FRONTEND_WEB_URL", "")
        or getattr(settings, "FRONTEND_URL", "")
        or ""
    ).rstrip("/")
    path = f"/c/{token}"
    return f"{base}{path}" if base else path


def _first_visitor_turn(thread) -> str:
    from apps.conversations.models import Message

    m = (
        Message.objects.filter(thread=thread, sender_kind__in=["visitor", "client"])
        .order_by("seq", "created_at")
        .first()
    )
    return (m.body or "") if m else ""
