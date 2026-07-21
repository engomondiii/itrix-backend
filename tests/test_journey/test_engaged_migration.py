"""
The ENGAGED split data migration (journey/0003).

The riskiest operation in Phase 1: it reconstructs three states from evidence, against a
live pipeline. These tests run the migration's OWN classifier against seeded rows so the
reconstruction is proven rather than assumed.
"""

from __future__ import annotations

import pytest

from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _classify(lead):
    """Call the migration's classifier with the real app registry."""
    import importlib

    from django.apps import apps as global_apps

    # The module name starts with a digit, so it cannot be imported with a normal
    # ``from ... import``. import_module handles it.
    module = importlib.import_module("apps.journey.migrations.0003_migrate_engaged_split")
    return module.classify(global_apps, lead)


def test_licensed_status_reconstructs_integration():
    lead = LeadFactory(journey_state="ENGAGED", status="Licensed")
    assert _classify(lead) == "INTEGRATION"


def test_negotiation_status_reconstructs_integration():
    lead = LeadFactory(journey_state="ENGAGED", status="Negotiation")
    assert _classify(lead) == "INTEGRATION"


def test_a_poc_record_reconstructs_poc():
    from apps.pocs.models import PoC

    lead = LeadFactory(journey_state="ENGAGED", status="PoC")
    PoC.objects.create(lead=lead, status="active")
    assert _classify(lead) == "POC"


def test_a_completed_poc_reconstructs_integration():
    """A finished PoC with nothing after it means the subject moved to commercials."""
    from apps.pocs.models import PoC

    lead = LeadFactory(journey_state="ENGAGED", status="PoC")
    PoC.objects.create(lead=lead, status="completed")
    assert _classify(lead) == "INTEGRATION"


def test_an_evaluation_record_reconstructs_assessment():
    from apps.evaluations.models import Evaluation

    lead = LeadFactory(journey_state="ENGAGED", status="Evaluation")
    Evaluation.objects.create(lead=lead)
    assert _classify(lead) == "ASSESSMENT"


def test_no_evidence_lands_on_the_conservative_floor():
    """
    ASSESSMENT, not NDA_REVIEW. ENGAGED always meant "past the NDA and paying", so
    demoting to a pre-payment state would withdraw customer-success access the subject
    already has — the more harmful error.
    """
    lead = LeadFactory(journey_state="ENGAGED", status="New")
    assert _classify(lead) == "ASSESSMENT"


def test_evidence_is_read_latest_stage_first():
    """
    A subject in integration ALSO has a PoC and an evaluation. Reading earliest-first
    would demote every advanced lead.
    """
    from apps.evaluations.models import Evaluation
    from apps.pocs.models import PoC

    lead = LeadFactory(journey_state="ENGAGED", status="Licensed")
    Evaluation.objects.create(lead=lead)
    PoC.objects.create(lead=lead, status="active")
    assert _classify(lead) == "INTEGRATION"
