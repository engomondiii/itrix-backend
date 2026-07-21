"""
Data migration: split ENGAGED into ASSESSMENT / POC / INTEGRATION, and map
CLIENT -> NDA_REVIEW (Backend v6.0 §Phase 1).

── WHY THIS NEEDS TO BE A DATA MIGRATION AND NOT A DEFAULT ──────────────────
v4.0 collapsed three commercially distinct situations into one ``ENGAGED`` value. A lead
running a paid Assessment, a lead mid-PoC, and a lead negotiating a licence all looked
identical. There is no way to recover that distinction from the state value alone — it
has to be reconstructed from the RECORDS that prove which stage the subject actually
reached.

── THE EVIDENCE ORDER ───────────────────────────────────────────────────────
Evidence is read from the LATEST stage backwards, because a subject in integration also
has a PoC record and an evaluation record. Taking the first match from the earliest
stage would demote every advanced lead.

    LO / integration record  -> INTEGRATION  (9)
    PoC record               -> POC          (8)
    Evaluation record        -> ASSESSMENT   (7)
    no evidence              -> ASSESSMENT   (7)  — the conservative floor

The floor is ASSESSMENT rather than NDA_REVIEW because ENGAGED always meant "past the
NDA and paying". Demoting a paying customer to a pre-payment state would withdraw
customer-success access they already have, which is the more harmful error.

── REVERSIBILITY ────────────────────────────────────────────────────────────
``reverse`` maps all three back to ENGAGED and NDA_REVIEW back to CLIENT. The split is
lossy in reverse by nature — that is unavoidable — but reversing restores the v4.0
semantics exactly, so a rollback lands on a coherent state rather than a broken one.

RUN ``manage.py journey_migration_report`` FIRST. It performs this same classification
as a DRY RUN and prints the distribution, so the split is reviewed before it is applied.
"""

from __future__ import annotations

from django.db import migrations

# v4.0 -> v6.0
ENGAGED = "ENGAGED"
CLIENT = "CLIENT"
NDA_REVIEW = "NDA_REVIEW"
ASSESSMENT = "ASSESSMENT"
POC = "POC"
INTEGRATION = "INTEGRATION"

JOURNEY_NUMBERS = {
    "ARRIVED": 1,
    "IN_REVIEW": 2,
    "DIAGNOSED": 3,
    "CLIENT_PAGE": 4,
    "INVITED": 5,
    "NDA_REVIEW": 6,
    "ASSESSMENT": 7,
    "POC": 8,
    "INTEGRATION": 9,
    "CUSTOMER_SUCCESS": 10,
}


def _has_rows(apps, label: str, model: str, lead_id) -> bool:
    """
    True when ``model`` has a row for this lead.

    Tolerant of a model that does not exist in this deployment: an app that was never
    installed is not evidence of anything, and must not abort the migration.
    """
    try:
        Model = apps.get_model(label, model)
    except LookupError:
        return False
    try:
        return Model.objects.filter(lead_id=lead_id).exists()
    except Exception:  # noqa: BLE001 - schema mismatch mid-migration
        return False


def _completed_poc(apps, lead_id) -> bool:
    """True when this lead has a PoC that reached ``completed``."""
    try:
        PoC = apps.get_model("pocs", "PoC")
    except LookupError:
        return False
    try:
        return PoC.objects.filter(lead_id=lead_id, status="completed").exists()
    except Exception:  # noqa: BLE001
        return False


def classify(apps, lead) -> str:
    """Reconstruct which of the three states an ENGAGED lead actually reached."""
    lead_id = lead.id

    # Latest stage first — an integrating subject also has PoC and evaluation rows.
    #
    # There is no dedicated licence-out record in the v4.0 schema, so INTEGRATION is
    # reconstructed from the two signals that DO exist: a lifecycle status that only a
    # licensing conversation produces, or a PoC that has finished (a completed PoC with
    # nothing after it means the subject moved on to commercial decisions).
    status = (getattr(lead, "status", "") or "").strip()
    if status in {"Licensed", "Negotiation"}:
        return INTEGRATION
    if _completed_poc(apps, lead_id):
        return INTEGRATION
    if _has_rows(apps, "pocs", "PoC", lead_id):
        return POC
    if _has_rows(apps, "evaluations", "Evaluation", lead_id):
        return ASSESSMENT

    # No evidence: hold at the conservative floor rather than demoting a paying subject.
    return ASSESSMENT


def forwards(apps, schema_editor):
    Lead = apps.get_model("leads", "Lead")

    # CLIENT -> NDA_REVIEW is a straight rename: same meaning, numbered position 6.
    Lead.objects.filter(journey_state=CLIENT).update(
        journey_state=NDA_REVIEW, state_key=NDA_REVIEW, journey_number=6
    )

    # ENGAGED needs per-row evidence, so it cannot be a bulk update.
    for lead in Lead.objects.filter(journey_state=ENGAGED).iterator():
        target = classify(apps, lead)
        lead.journey_state = target
        lead.state_key = target
        lead.journey_number = JOURNEY_NUMBERS[target]
        lead.save(update_fields=["journey_state", "state_key", "journey_number"])

    # Backfill the denormalised fields for every OTHER row so no reader has to handle a
    # half-populated ladder. DORMANT is left with journey_number NULL — it is off-ladder
    # by design, not missing data.
    for state_key, number in JOURNEY_NUMBERS.items():
        Lead.objects.filter(journey_state=state_key).update(
            state_key=state_key, journey_number=number
        )
    Lead.objects.filter(journey_state="DORMANT").update(
        state_key="DORMANT", journey_number=None
    )


def backwards(apps, schema_editor):
    """
    Restore v4.0 semantics.

    Lossy by nature — the three states collapse back into one — but the result is a
    coherent v4.0 dataset rather than a mix of vocabularies.
    """
    Lead = apps.get_model("leads", "Lead")
    Lead.objects.filter(journey_state__in=[ASSESSMENT, POC, INTEGRATION]).update(
        journey_state=ENGAGED, state_key="", journey_number=None
    )
    Lead.objects.filter(journey_state=NDA_REVIEW).update(
        journey_state=CLIENT, state_key="", journey_number=None
    )
    Lead.objects.filter(journey_state="CUSTOMER_SUCCESS").update(
        journey_state=ENGAGED, state_key="", journey_number=None
    )


class Migration(migrations.Migration):

    dependencies = [
        ("journey", "0002_ten_state_journey"),
        # The denormalised columns must exist before we can populate them.
        ("leads", "0004_thread_spine"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
