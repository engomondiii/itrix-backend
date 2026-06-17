"""
SLA compliance calculator.

Computes response-time metrics from follow-up tasks — matches ``ResponseTimeMetrics``:
average hours to first response for Tier 1 / Tier 2, breach counts, and overall compliance
rate (0–1). "Response" = the lead's first_response_at relative to the task's start; a task
past due with no response counts as a breach.
"""

from __future__ import annotations

from django.utils import timezone

from apps.follow_up.models import FollowUpStatus, FollowUpTask


def _hours_between(start, end) -> float:
    return max(0.0, (end - start).total_seconds() / 3600.0)


def response_time_metrics() -> dict:
    now = timezone.now()
    tier_hours = {1: [], 2: []}
    tier_breaches = {1: 0, 2: 0}
    total_tasks = 0
    compliant = 0

    tasks = FollowUpTask.objects.select_related("lead").all()
    for task in tasks:
        tier = task.tier
        total_tasks += 1
        lead = task.lead
        responded_at = getattr(lead, "first_response_at", None) if lead else None

        if responded_at:
            hrs = _hours_between(task.created_at, responded_at)
            if tier in tier_hours:
                tier_hours[tier].append(hrs)
            # Compliant if responded before the (effective) due time.
            if responded_at <= task.effective_due:
                compliant += 1
            else:
                if tier in tier_breaches:
                    tier_breaches[tier] += 1
        else:
            # No response yet — breach only if overdue.
            if task.status != FollowUpStatus.COMPLETED and task.effective_due < now:
                if tier in tier_breaches:
                    tier_breaches[tier] += 1
            else:
                # Still within SLA window and not yet due → counts as on-track.
                compliant += 1

    def _avg(values):
        return round(sum(values) / len(values), 1) if values else 0.0

    compliance_rate = round(compliant / total_tasks, 3) if total_tasks else 1.0

    return {
        "tier1AvgHours": _avg(tier_hours[1]),
        "tier2AvgHours": _avg(tier_hours[2]),
        "tier1Breaches": tier_breaches[1],
        "tier2Breaches": tier_breaches[2],
        "complianceRate": compliance_rate,
    }
