"""
Lead updater.

Centralises mutations the dashboard performs on a lead — assign owner, change status,
add a note, attach email/company/name (from email capture) — and records the matching
``LeadActivity`` for each, so the lead timeline is always accurate. Keeping these in one
service means the viewset stays thin and every mutation is consistently logged.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.leads.models import Lead, LeadActivity, LeadNote, LeadStatus

logger = logging.getLogger("itrix")


def _actor_name(user) -> str:
    return getattr(user, "display_name", "") or getattr(user, "email", "") or "system"


def assign_owner(lead: Lead, *, owner, by=None) -> Lead:
    """Assign (or clear) the lead owner and log it."""
    previous = lead.owner
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
    return lead


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
