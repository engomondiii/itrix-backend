"""
THE RAILS CONTRACT IS RETIRED (Backend v6.0 §Phase 3, §3.1, §11.4).

    left_rail / right_rail are emitted as deprecated stubs through Phases 1-2 and REMOVED
    IN PHASE 3, giving both frontends a full release to migrate.

After the deprecation window they are ABSENT from every payload, and a client that SENDS
them receives 400 — silently accepting a field we no longer honour would leave a frontend
believing it still controls something it does not.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest
from rest_framework import serializers

RAIL_FIELDS = ("left_rail", "right_rail", "leftRail", "rightRail")


def _all_serializers():
    import apps

    for module_info in pkgutil.walk_packages(apps.__path__, prefix="apps."):
        name = module_info.name
        if "serializers" not in name.rsplit(".", 1)[-1]:
            continue
        try:
            module = importlib.import_module(name)
        except Exception:  # noqa: BLE001
            continue
        for cls_name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, serializers.Serializer) and obj.__module__ == name:
                yield name, cls_name, obj


def test_no_serializer_declares_a_rail_field():
    offenders = []
    for module_name, cls_name, obj in _all_serializers():
        fields = set(getattr(getattr(obj, "Meta", None), "fields", []) or [])
        fields |= set(getattr(obj, "_declared_fields", {}).keys())
        leaked = fields & set(RAIL_FIELDS)
        if leaked:
            offenders.append(f"{module_name}.{cls_name}: {sorted(leaked)}")
    assert not offenders, "the rails contract is retired:\n  " + "\n  ".join(offenders)


def test_the_deprecation_stub_is_gone():
    """The one-release shim was removed in Phase 3."""
    from apps.conversations import serializers_thread

    assert not hasattr(serializers_thread, "deprecated_rail_stub")


@pytest.mark.django_db
def test_the_journey_payload_has_no_rails():
    from apps.journey.views import _journey_payload
    from tests.factories.lead_factory import LeadFactory

    payload = _journey_payload(LeadFactory(journey_state="CLIENT_PAGE"))
    for field in RAIL_FIELDS:
        assert field not in payload
    # And the replacement is present.
    assert "cards" in payload


@pytest.mark.django_db
def test_the_thread_shell_has_no_rails():
    from apps.conversations.serializers_thread import ThreadDetailSerializer
    from apps.conversations.services import threads as thread_svc

    thread = thread_svc.create_thread(visitor_session="s-rails")
    shell = ThreadDetailSerializer(thread).data["shell"]
    for field in RAIL_FIELDS:
        assert field not in shell
    assert "sidebar_sections" in shell
    assert "conversation_header" in shell


def test_a_request_carrying_a_rail_field_is_rejected():
    """
    Explicit rather than ignored: a 400 naming the field tells the frontend author what
    to change, where silence would let a stale client ship believing it still works.
    """
    from apps.conversations.serializers_thread import RailFieldsRetired, reject_rail_fields

    for field in RAIL_FIELDS:
        with pytest.raises(RailFieldsRetired):
            reject_rail_fields({field: []})


def test_a_clean_request_passes():
    from apps.conversations.serializers_thread import reject_rail_fields

    reject_rail_fields({"body": "hello", "attachment_ids": []})


def test_the_error_names_the_replacement():
    """An error that only says 'no' costs a support round trip."""
    from apps.conversations.serializers_thread import RailFieldsRetired, reject_rail_fields

    try:
        reject_rail_fields({"left_rail": []})
    except RailFieldsRetired as exc:
        assert "sidebar_sections" in str(exc)
        assert "conversation_header" in str(exc)
