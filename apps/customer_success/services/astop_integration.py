"""Customer-safe ASTOP state projected through the existing Customer Success domain."""
from __future__ import annotations

from apps.customer_success.models import SupportRequest
from apps.customer_success.services import overlay
from apps.leads.models import ASTOPEngagement
from apps.leads.services.lo_terms import customer_safe_lo_summary
from apps.leads.services.progression_state import customer_safe_progression_state
from apps.leads.services.verified_value_economics import customer_safe_verified_value


def _verified_value_status(record: ASTOPEngagement | None) -> str:
    if record is None or not record.has_verified_value:
        return "not_verified"
    value = record.verified_value if isinstance(record.verified_value, dict) else {}
    return str(value.get("status") or "verified").strip() or "verified"


def _expansion_status(record: ASTOPEngagement | None) -> str:
    if record is None:
        return "not_recorded"
    expansion = record.expansion if isinstance(record.expansion, dict) else {}
    return str(expansion.get("status") or "not_recorded").strip() or "not_recorded"


def snapshot(client) -> dict:
    """Return ASTOP facts useful to Customer Success without internal commercial detail."""
    record = ASTOPEngagement.objects.filter(lead=client.lead).first()
    lo = customer_safe_lo_summary(record)
    progression = customer_safe_progression_state(client.lead)
    support = SupportRequest.objects.filter(client=client)
    open_support = support.exclude(status=SupportRequest.Status.RESOLVED)
    blocking_open = open_support.filter(blocking=True)

    if blocking_open.exists():
        next_action = "resolve_blocking_support"
    elif record is None:
        next_action = "continue_success_plan"
    elif lo["nextRequiredAction"] != "none":
        next_action = lo["nextRequiredAction"]
    else:
        next_action = "continue_success_plan"

    return {
        "customerSuccessActive": overlay.is_active(client),
        "astopStage": record.stage if record else "",
        # Canonical model semantics deliberately return None for incomplete or invalid
        # timestamp ordering. Never turn an invalid negative interval into customer-visible 0.
        "ttfvSeconds": record.ttfv_seconds if record else None,
        "verifiedValue": bool(record and record.has_verified_value),
        "verifiedValueStatus": _verified_value_status(record),
        "verifiedValueSummary": customer_safe_verified_value(record),
        "governedProgression": progression,
        "governedNextBestAction": progression["nextBestAction"],
        "support": {
            "openCount": open_support.count(),
            "blockingOpenCount": blocking_open.count(),
        },
        "deploymentScope": lo["licensedScopeSummary"],
        "loStatus": lo["loStatus"],
        "entitlementState": lo["entitlementState"],
        "entitlementExpiresAt": lo["entitlementExpiresAt"],
        "expansionStatus": _expansion_status(record),
        "nextRequiredAction": next_action,
    }
