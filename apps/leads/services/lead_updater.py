"""
Lead updater.

Centralises mutations the dashboard performs on a lead — assign owner, change status,
add a note, attach email/company/name (from email capture) — and records the matching
``LeadActivity`` for each, so the lead timeline is always accurate. Keeping these in one
service means the viewset stays thin and every mutation is consistently logged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.utils import timezone

from apps.leads.models import Lead, LeadActivity, LeadMeeting, LeadNote, LeadStatus

logger = logging.getLogger("itrix")


def _actor_name(user) -> str:
    return getattr(user, "display_name", "") or getattr(user, "email", "") or "system"


@dataclass(frozen=True)
class AssignResult:
    """
    The outcome of one assignment attempt.

    ``applied`` False means the lead was already owned by someone else and
    ``only_if_unowned`` was in force — nothing was written and nothing was logged.
    ``current_owner`` is who holds it, so the caller can say so rather than
    reporting a generic failure.
    """

    applied: bool
    lead: Lead
    current_owner: object | None = None


def assign_owner(lead: Lead, *, owner, by=None, only_if_unowned: bool = False) -> AssignResult:
    """
    Assign (or clear) the lead owner and log it.

    ── THE CONDITIONAL WRITE IS THE POINT (fix, 2026-08-12) ─────────────────────
    ``lead.owner = owner; lead.save()`` is a read-modify-write across a round trip:
    two operators who both loaded the board see ``owner is None``, both save, and the
    second one wins silently. The guarded path below claims the lead with a SINGLE
    conditional UPDATE — ``filter(pk=..., owner__isnull=True).update(...)`` — and the
    database decides. The row count tells us whether we won.

    Doing it in the database rather than under ``select_for_update`` keeps this correct
    on both engines without holding a row lock across the activity write, and needs no
    transaction management from callers.

    The activity row is written ONLY on a write that landed. A timeline that logged
    losing attempts would show owner changes that never happened, and the timeline is
    the record people trust when they ask who took a lead.
    """
    previous = lead.owner

    if only_if_unowned and owner is not None:
        if previous is not None:
            # Idempotent: assigning to the current owner is the same intention twice,
            # not a conflict.
            if previous.id == owner.id:
                return AssignResult(applied=True, lead=lead, current_owner=previous)
            return AssignResult(applied=False, lead=lead, current_owner=previous)

        claimed = Lead.objects.filter(pk=lead.pk, owner__isnull=True).update(
            owner=owner, updated_at=timezone.now()
        )
        if not claimed:
            # Somebody else claimed it between our read and our write. Report THEIR
            # owner, freshly read — the instance we hold still says None.
            current = Lead.objects.filter(pk=lead.pk).select_related("owner").first()
            return AssignResult(
                applied=False,
                lead=lead,
                current_owner=getattr(current, "owner", None),
            )
        lead.owner = owner
    elif only_if_unowned and owner is None and previous is not None:
        # Clearing an owned lead is an override too, and takes the same explicit route.
        return AssignResult(applied=False, lead=lead, current_owner=previous)
    else:
        lead.owner = owner
        lead.save(update_fields=["owner", "updated_at"])

    LeadActivity.objects.create(
        lead=lead,
        type=LeadActivity.ActivityType.OWNER_CHANGE,
        label=(
            f"Owner changed to {owner.display_name}"
            if owner
            else "Owner cleared"
        ),
        by=by,
        by_name=_actor_name(by),
        meta={"from": str(previous.id) if previous else None, "to": str(owner.id) if owner else None},
    )
    return AssignResult(applied=True, lead=lead, current_owner=owner)


def change_status(lead: Lead, *, status: str, by=None) -> Lead:
    """Update the lead status (validated against the 12 choices) and log it."""
    valid = dict(LeadStatus.choices)
    if status not in valid:
        from apps.core.exceptions import ITrixError

        raise ITrixError(f"Unknown status: {status!r}")

    previous = lead.status
    lead.status = status
    # First human response stamps the SLA when leaving "New".
    if previous == LeadStatus.NEW and status != LeadStatus.NEW and lead.first_response_at is None:
        lead.first_response_at = timezone.now()
        lead.save(update_fields=["status", "first_response_at", "updated_at"])
    else:
        lead.save(update_fields=["status", "updated_at"])

    LeadActivity.objects.create(
        lead=lead,
        type=LeadActivity.ActivityType.STATUS_CHANGE,
        label=f"Status: {previous} → {status}",
        by=by,
        by_name=_actor_name(by),
        meta={"from": previous, "to": status},
    )
    return lead


def add_note(lead: Lead, *, body: str, by=None) -> LeadNote:
    """Attach an internal note and log a note activity."""
    note = LeadNote.objects.create(
        lead=lead, body=body, author=by, author_name=_actor_name(by)
    )
    LeadActivity.objects.create(
        lead=lead,
        type=LeadActivity.ActivityType.NOTE,
        label="Internal note added.",
        by=by,
        by_name=_actor_name(by),
    )
    return note


def book_meeting(
    lead: Lead,
    *,
    scheduled_at,
    duration_mins: int = 30,
    attendee: str = "",
    location: str = "",
    notes: str = "",
    by=None,
) -> LeadMeeting:
    """Book a meeting for the lead, advance status to "Meeting Booked", and log it."""
    meeting = LeadMeeting.objects.create(
        lead=lead,
        scheduled_at=scheduled_at,
        duration_mins=duration_mins or 30,
        attendee=attendee,
        location=location,
        notes=notes,
        booked_by=by,
        booked_by_name=_actor_name(by),
    )
    change_status(lead, status=LeadStatus.MEETING_BOOKED, by=by)
    LeadActivity.objects.create(
        lead=lead,
        type=LeadActivity.ActivityType.MEETING,
        label=f"Meeting booked with {attendee}." if attendee else "Meeting booked.",
        by=by,
        by_name=_actor_name(by),
        meta={"meeting_id": str(meeting.id), "scheduled_at": scheduled_at.isoformat() if scheduled_at else None},
    )
    return meeting


def apply_email_capture(
    lead: Lead, *, email: str = "", name: str = "", company: str = "", source: str = "web"
) -> Lead:
    """Fill contact details captured from the public site (best-effort, non-destructive)."""
    changed = []
    if email and not lead.email:
        lead.email = email
        changed.append("email")
    if name and not lead.visitor_name:
        lead.visitor_name = name
        changed.append("visitor_name")
    if company and not lead.company:
        lead.company = company
        changed.append("company")
    if changed:
        changed.append("updated_at")
        lead.save(update_fields=changed)
        LeadActivity.objects.create(
            lead=lead,
            type=LeadActivity.ActivityType.SUBMISSION,
            label=f"Contact details captured ({source}).",
            meta={"fields": changed, "source": source},
        )
    return lead
