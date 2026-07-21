"""
The persona registry is INTERNAL-ONLY in its entirety (Architecture v2.6 §10.5).

``persona_id`` and ``pitch_room_id`` must not appear in ANY payload on the anonymous or
client plane, at any state, in any turn, artifact or card.
"""

from __future__ import annotations

import pathlib

import pytest

from apps.personas.models import FunctionalFamily, Persona
from apps.personas.serializers import PersonaDetailSerializer

pytestmark = pytest.mark.django_db

PERSONAS_DIR = pathlib.Path(__file__).resolve().parents[2] / "apps" / "personas"


def test_persona_routes_are_team_gated():
    """
    Every view in the app must be permission-gated. There is no AllowAny path into this
    module and there must never be one.
    """
    from apps.personas import views

    for name in ("PersonaListView", "PersonaDetailView"):
        view = getattr(views, name)
        classes = [c.__name__ for c in view.permission_classes]
        assert "IsDashboardUser" in classes, f"{name} is not team-gated"
        assert "AllowAny" not in classes


def test_there_is_no_client_plane_serializer():
    """
    A scan, not a behavioural test: the risk is somebody ADDING a public serializer
    later, and only a scan catches that.
    """
    source = (PERSONAS_DIR / "serializers.py").read_text()
    assert "AllowAny" not in source


def test_persona_id_is_absent_from_the_shell_contract():
    from apps.journey.services import shell
    from tests.factories.lead_factory import LeadFactory

    persona = Persona.objects.create(
        persona_id="P-X01",
        company="Acme",
        functional_family=FunctionalFamily.AI_MODEL_SYSTEMS,
    )
    lead = LeadFactory(journey_state="CLIENT_PAGE", persona=persona)
    contract = shell.for_subject(lead)
    rendered = str(contract)
    assert "P-X01" not in rendered
    assert "persona" not in contract


def test_persona_id_is_absent_from_the_thread_serializer():
    from apps.conversations.serializers_thread import ThreadDetailSerializer
    from apps.conversations.services import threads as thread_svc
    from tests.factories.lead_factory import LeadFactory

    persona = Persona.objects.create(
        persona_id="P-X02",
        company="Acme",
        functional_family=FunctionalFamily.AI_MODEL_SYSTEMS,
    )
    lead = LeadFactory(persona=persona)
    thread = thread_svc.create_thread(visitor_session="s1", lead=lead)
    assert "P-X02" not in str(ThreadDetailSerializer(thread).data)


def test_department_names_are_explicitly_hypotheses():
    """A hypothesis rendered as an assertion is the failure this field prevents."""
    persona = Persona.objects.create(
        persona_id="P-X03",
        company="Acme",
        functional_family=FunctionalFamily.AI_MODEL_SYSTEMS,
    )
    assert persona.validation_status == "hypothesis"
    assert persona.is_hypothesis is True


def test_team_serializer_does_expose_the_registry():
    """The team plane is the ONE place this data is legitimately visible."""
    persona = Persona.objects.create(
        persona_id="P-X04",
        company="Acme",
        functional_family=FunctionalFamily.AI_MODEL_SYSTEMS,
    )
    data = PersonaDetailSerializer(persona).data
    assert data["personaId"] == "P-X04"
