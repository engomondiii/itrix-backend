"""
The shared 30/60/90 plan (Playbook §12F).

    DEPENDENCY FRAMING
    These items need something from your side. We have flagged them early so they do
    not surprise anyone.

That sentence is the whole design brief. ``needs_customer_action`` exists so a plan can
say "we are waiting on you" BEFORE the review, not during it.
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger("itrix")


def get_or_create_active(client, *, title: str = "Our shared plan"):
    from apps.customer_success.models import SuccessPlan

    plan = SuccessPlan.objects.filter(client=client, is_active=True).first()
    if plan is not None:
        return plan
    return SuccessPlan.objects.create(client=client, title=title, starts_on=timezone.now().date())


def add_milestone(plan, *, title: str, horizon: int = 30, owner_side: str = "shared",
                  owner_name: str = "", needs_customer_action: bool = False, due_on=None):
    from apps.customer_success.models import SuccessPlanMilestone

    return SuccessPlanMilestone.objects.create(
        plan=plan,
        title=title[:300],
        horizon=horizon,
        owner_side=owner_side,
        owner_name=owner_name[:200],
        needs_customer_action=needs_customer_action,
        due_on=due_on,
    )


def complete_milestone(milestone):
    from apps.customer_success.models import OutcomeStatus

    milestone.status = OutcomeStatus.ACHIEVED
    milestone.completed_at = timezone.now()
    milestone.save(update_fields=["status", "completed_at", "updated_at"])
    return milestone


def pending_customer_actions(client):
    """
    Milestones waiting on the CUSTOMER.

    Surfaced prominently rather than buried in the plan, because a dependency the
    customer does not know about is a dependency that will be missed and then blamed on
    whoever mentions it last.
    """
    from apps.customer_success.models import SuccessPlanMilestone

    return SuccessPlanMilestone.objects.filter(
        plan__client=client,
        plan__is_active=True,
        needs_customer_action=True,
        completed_at__isnull=True,
    ).order_by("due_on", "horizon")


def plan_summary(client) -> dict:
    from apps.customer_success.models import OutcomeStatus, SuccessPlan, SuccessPlanMilestone

    plan = SuccessPlan.objects.filter(client=client, is_active=True).first()
    if plan is None:
        return {"has_plan": False, "milestones": [], "awaiting_customer": 0}

    milestones = SuccessPlanMilestone.objects.filter(plan=plan).order_by("horizon", "due_on")
    return {
        "has_plan": True,
        "title": plan.title,
        "summary": plan.summary,
        "milestones": [
            {
                "id": str(m.id),
                "horizon": m.horizon,
                "title": m.title,
                "status": m.status,
                "ownerSide": m.owner_side,
                "ownerName": m.owner_name,
                "needsCustomerAction": m.needs_customer_action,
                "dueOn": m.due_on.isoformat() if m.due_on else None,
            }
            for m in milestones
        ],
        "awaiting_customer": milestones.filter(
            needs_customer_action=True, completed_at__isnull=True
        ).count(),
        "off_plan": milestones.filter(
            status__in=[OutcomeStatus.OFF_PLAN, OutcomeStatus.AT_RISK]
        ).count(),
    }
