"""
Team serializers.

Produces the dashboard's ``TeamMember`` shape
(``itrix-dashboard/src/types/team.ts``):

    { id, name, email, role, avatarUrl?, active, openLeads? }

``role`` is the friendly display label (``team_role``). ``openLeads`` is the count of
leads currently owned by the member; in Phase 1 the ``leads`` app does not exist yet,
so it resolves to 0 via a guarded lookup that lights up automatically in Phase 2.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


def _open_lead_count(user) -> int:
    """Open leads owned by ``user`` — safe before the leads app exists (Phase 2)."""
    related = getattr(user, "owned_leads", None)
    if related is None:
        return 0
    try:
        # "open" = not in a terminal state. Leads model (Phase 2) exposes is_open;
        # fall back to a plain count if that helper isn't present yet.
        qs = related.all()
        return qs.exclude(status__in=["WON", "LOST", "CLOSED"]).count()
    except Exception:  # noqa: BLE001 - never let the team list 500 on this
        try:
            return related.count()
        except Exception:  # noqa: BLE001
            return 0


class TeamMemberSerializer(serializers.ModelSerializer):
    role = serializers.CharField(source="team_role")
    avatarUrl = serializers.SerializerMethodField()
    active = serializers.BooleanField(source="is_active")
    openLeads = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "email", "role", "avatarUrl", "active", "openLeads"]
        read_only_fields = ["id", "email", "openLeads"]

    def get_avatarUrl(self, obj) -> str | None:
        return obj.avatar_url or None

    def get_openLeads(self, obj) -> int:
        return _open_lead_count(obj)


class TeamMemberUpdateSerializer(serializers.ModelSerializer):
    """Writable subset for PATCH /team/{id}/ (name, display role, avatar, active)."""

    role = serializers.ChoiceField(
        source="team_role", choices=User.TeamRole.choices, required=False
    )
    avatarUrl = serializers.URLField(
        source="avatar_url", required=False, allow_blank=True
    )
    active = serializers.BooleanField(source="is_active", required=False)

    class Meta:
        model = User
        fields = ["name", "role", "avatarUrl", "active"]
