"""
Drop the deprecated CLIENT and ENGAGED members (Backend v6.0 §Phase 3).

They survived exactly one release as aliases so that any row migration 0003 had not yet
touched could still deserialise. That window has closed.

── WHY THIS SWEEPS BEFORE IT ALTERS ─────────────────────────────────────────
Migration 0003 converted every row that existed WHEN IT RAN. But between 0003 and this
migration, a process still running the old code could have written a fresh ENGAGED row —
during a rolling deploy, that window is real and is measured in minutes.

So this migration re-runs the classification for any stragglers BEFORE removing the enum
members. Altering the field first would leave those rows holding a value the enum no
longer knows, which is exactly the state ``normalize_state`` exists to survive but which
we should not deliberately create.

── REVERSIBILITY ────────────────────────────────────────────────────────────
``reverse`` restores the choices. It does NOT restore the old values — 0003's own reverse
does that, and duplicating it here would let a partial rollback produce a mix of both
vocabularies.
"""

from __future__ import annotations

from django.db import migrations, models

ENGAGED = "ENGAGED"
CLIENT = "CLIENT"
NDA_REVIEW = "NDA_REVIEW"
ASSESSMENT = "ASSESSMENT"
POC = "POC"
INTEGRATION = "INTEGRATION"

JOURNEY_NUMBERS = {
    "ARRIVED": 1, "IN_REVIEW": 2, "DIAGNOSED": 3, "CLIENT_PAGE": 4, "INVITED": 5,
    "NDA_REVIEW": 6, "ASSESSMENT": 7, "POC": 8, "INTEGRATION": 9, "CUSTOMER_SUCCESS": 10,
}

# The post-Phase-3 vocabulary.
LIVE_CHOICES = [
    ("ARRIVED", "Arrived"),
    ("IN_REVIEW", "In review"),
    ("DIAGNOSED", "Diagnosed"),
    ("CLIENT_PAGE", "Client page"),
    ("INVITED", "Invited"),
    ("NDA_REVIEW", "NDA review"),
    ("ASSESSMENT", "Assessment"),
    ("POC", "PoC"),
    ("INTEGRATION", "Integration"),
    ("CUSTOMER_SUCCESS", "Customer success"),
    ("DORMANT", "Dormant"),
]

# Pre-Phase-3, for the reverse.
LEGACY_CHOICES = LIVE_CHOICES + [
    ("CLIENT", "Client (deprecated - use NDA_REVIEW)"),
    ("ENGAGED", "Engaged (deprecated - use ASSESSMENT/POC/INTEGRATION)"),
]


def _completed_poc(apps, lead_id) -> bool:
    try:
        PoC = apps.get_model("pocs", "PoC")
        return PoC.objects.filter(lead_id=lead_id, status="completed").exists()
    except Exception:  # noqa: BLE001
        return False


def _has_rows(apps, label: str, model: str, lead_id) -> bool:
    try:
        Model = apps.get_model(label, model)
        return Model.objects.filter(lead_id=lead_id).exists()
    except Exception:  # noqa: BLE001
        return False


def classify(apps, lead) -> str:
    """Identical to migration 0003's classifier — the same judgement, applied late."""
    status = (getattr(lead, "status", "") or "").strip()
    if status in {"Licensed", "Negotiation"}:
        return INTEGRATION
    if _completed_poc(apps, lead.id):
        return INTEGRATION
    if _has_rows(apps, "pocs", "PoC", lead.id):
        return POC
    if _has_rows(apps, "evaluations", "Evaluation", lead.id):
        return ASSESSMENT
    return ASSESSMENT


def sweep_stragglers(apps, schema_editor):
    """
    Convert any row still holding a legacy value.

    Expected to be a no-op in a healthy deployment — and that is the point. If it finds
    rows, they were written during the rolling-deploy window, and converting them here is
    cheaper than discovering them later as a page that will not render.
    """
    Lead = apps.get_model("leads", "Lead")

    Lead.objects.filter(journey_state=CLIENT).update(
        journey_state=NDA_REVIEW, state_key=NDA_REVIEW, journey_number=6
    )

    for lead in Lead.objects.filter(journey_state=ENGAGED).iterator():
        target = classify(apps, lead)
        lead.journey_state = target
        lead.state_key = target
        lead.journey_number = JOURNEY_NUMBERS[target]
        lead.save(update_fields=["journey_state", "state_key", "journey_number"])

    # Also clean the transition log's from/to columns so an audit read does not surface a
    # vocabulary that no longer exists. The EVENT column is left alone — those events
    # genuinely happened under the old names.
    JourneyTransition = apps.get_model("journey", "JourneyTransition")
    JourneyTransition.objects.filter(from_state=CLIENT).update(from_state=NDA_REVIEW)
    JourneyTransition.objects.filter(to_state=CLIENT).update(to_state=NDA_REVIEW)
    JourneyTransition.objects.filter(from_state=ENGAGED).update(from_state=ASSESSMENT)
    JourneyTransition.objects.filter(to_state=ENGAGED).update(to_state=ASSESSMENT)


def noop_reverse(apps, schema_editor):
    """
    Deliberately does nothing.

    Migration 0003's own reverse restores the legacy values. Duplicating that here would
    let a partial rollback produce a mix of both vocabularies, which is worse than either
    one.
    """
    return


class Migration(migrations.Migration):

    dependencies = [
        ("journey", "0004_artifacts"),
        ("leads", "0004_thread_spine"),
    ]

    operations = [
        # Sweep FIRST, then narrow the vocabulary.
        migrations.RunPython(sweep_stragglers, noop_reverse),
        migrations.AlterField(
            model_name="journeytransition",
            name="from_state",
            field=models.CharField(choices=LIVE_CHOICES, max_length=20),
        ),
        migrations.AlterField(
            model_name="journeytransition",
            name="to_state",
            field=models.CharField(choices=LIVE_CHOICES, max_length=20),
        ),
    ]
