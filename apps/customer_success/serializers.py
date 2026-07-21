"""
Customer-success serializers (Backend v6.0 §Phase 2, Architecture §7.4).

── ALLOW-LISTS, NOT DENY-LISTS ──────────────────────────────────────────────
Customer-visible vs internal-only is enforced by SERIALIZER ALLOW-LISTS on the client
plane, not by the frontend omitting fields (§7.4).

The distinction matters because the two fail in opposite directions. A deny-list fails
OPEN: add a field to the model and it appears in the payload until somebody remembers to
exclude it. An allow-list fails CLOSED: add a field and it stays invisible until somebody
deliberately admits it.

── WHAT A CUSTOMER MUST NEVER SEE (§12J) ────────────────────────────────────
    internal license-out probability · deal score · tier · account priority
    persona label · department hypothesis · any internal classification of who they are
    churn-risk modelling · negotiation posture · competitor risk · objection classification
    coverage maps · question budgets · stop reasons · attachment risk flags
    an expansion CTA while an outcome is off plan, a critical support issue is open,
    adoption is below plan, or trust feedback is negative

Two of those live on models in this app — ``customer_health`` on Client and ``score`` on
FeedbackPulse. Neither appears in any serializer below. That is not an oversight to be
corrected later; it is the point.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.customer_success.models import (
    ChangeLogEntry,
    DeploymentHealth,
    FeedbackPulse,
    Outcome,
    RelationshipTeamMember,
    ReleaseNote,
    SuccessPlan,
    SuccessPlanMilestone,
    SuccessReview,
    SupportRequest,
)

# ═════════════════════════════════════════════════════════════════════════════
# CLIENT PLANE — what a contracted customer may see
# ═════════════════════════════════════════════════════════════════════════════


class OutcomeSerializer(serializers.ModelSerializer):
    """
    The customer's own outcomes.

    ``status`` is one of the four approved words and is rendered verbatim. There is no
    percentage, no RAG colour and no trend arrow — each of those invites a reader to
    interpret an outcome as better than "Off plan" says it is.
    """

    ownerSide = serializers.CharField(source="owner_side", read_only=True)
    ownerName = serializers.CharField(source="owner_name", read_only=True)
    statusNote = serializers.CharField(source="status_note", read_only=True)
    targetDate = serializers.DateField(source="target_date", read_only=True)
    achievedAt = serializers.DateTimeField(source="achieved_at", read_only=True)
    statusLabel = serializers.SerializerMethodField()

    class Meta:
        model = Outcome
        fields = [
            "id", "title", "description", "measure", "status", "statusLabel",
            "statusNote", "ownerSide", "ownerName", "targetDate", "achievedAt",
        ]
        read_only_fields = fields

    def get_statusLabel(self, obj) -> str:
        return obj.get_status_display()


class SuccessPlanMilestoneSerializer(serializers.ModelSerializer):
    ownerSide = serializers.CharField(source="owner_side", read_only=True)
    ownerName = serializers.CharField(source="owner_name", read_only=True)
    needsCustomerAction = serializers.BooleanField(source="needs_customer_action", read_only=True)
    dueOn = serializers.DateField(source="due_on", read_only=True)

    class Meta:
        model = SuccessPlanMilestone
        fields = [
            "id", "horizon", "title", "status", "ownerSide", "ownerName",
            "needsCustomerAction", "dueOn",
        ]
        read_only_fields = fields


class SuccessPlanSerializer(serializers.ModelSerializer):
    milestones = SuccessPlanMilestoneSerializer(many=True, read_only=True)

    class Meta:
        model = SuccessPlan
        fields = ["id", "title", "summary", "milestones"]
        read_only_fields = fields


class DeploymentHealthSerializer(serializers.ModelSerializer):
    """
    Deployment status, INCLUDING the limitations we already know about.

    ``known_limitations`` is customer-visible on purpose: "We would rather you hear them
    from us." Omitting it would make the panel look better and the relationship worse.
    """

    lastCheckedAt = serializers.DateTimeField(source="last_checked_at", read_only=True)
    incidentNote = serializers.CharField(source="incident_note", read_only=True)
    knownLimitations = serializers.CharField(source="known_limitations", read_only=True)
    statusLabel = serializers.SerializerMethodField()

    class Meta:
        model = DeploymentHealth
        fields = [
            "id", "environment", "status", "statusLabel", "version",
            "lastCheckedAt", "incidentNote", "knownLimitations",
        ]
        read_only_fields = fields

    def get_statusLabel(self, obj) -> str:
        return obj.get_status_display()


class SupportRequestSerializer(serializers.ModelSerializer):
    """
    A support request as the CUSTOMER sees it.

    ``blocking`` is included — they already know whether they are blocked, and showing
    it confirms we understood. What is absent is any internal triage signal that would
    let them infer how we rank them against other customers.
    """

    ownerName = serializers.CharField(source="owner_name", read_only=True)
    slaDueAt = serializers.DateTimeField(source="sla_due_at", read_only=True)
    resolvedAt = serializers.DateTimeField(source="resolved_at", read_only=True)
    resolutionNote = serializers.CharField(source="resolution_note", read_only=True)
    at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = SupportRequest
        fields = [
            "id", "subject", "body", "status", "urgency", "blocking",
            "ownerName", "slaDueAt", "resolvedAt", "resolutionNote", "at",
        ]
        read_only_fields = fields


class RelationshipTeamMemberSerializer(serializers.ModelSerializer):
    """
    A named human.

    R30 is an absolute: a customer can always reach a named human without first
    negotiating with an agent. ``contact_email`` is therefore customer-visible — a
    "named" contact you cannot actually contact is not a contact.
    """

    displayName = serializers.CharField(source="display_name", read_only=True)
    helpsWith = serializers.CharField(source="helps_with", read_only=True)
    contactEmail = serializers.EmailField(source="contact_email", read_only=True)
    roleLabel = serializers.SerializerMethodField()

    class Meta:
        model = RelationshipTeamMember
        fields = ["id", "displayName", "role", "roleLabel", "helpsWith", "contactEmail", "is_primary"]
        read_only_fields = fields

    def get_roleLabel(self, obj) -> str:
        return obj.get_role_display()


class ReleaseNoteSerializer(serializers.ModelSerializer):
    releasedAt = serializers.DateTimeField(source="released_at", read_only=True)

    class Meta:
        model = ReleaseNote
        fields = ["id", "version", "title", "body", "releasedAt"]
        read_only_fields = fields


class ChangeLogEntrySerializer(serializers.ModelSerializer):
    occurredAt = serializers.DateTimeField(source="occurred_at", read_only=True)
    kindLabel = serializers.SerializerMethodField()

    class Meta:
        model = ChangeLogEntry
        fields = ["id", "kind", "kindLabel", "title", "detail", "occurredAt"]
        read_only_fields = fields

    def get_kindLabel(self, obj) -> str:
        return obj.get_kind_display()


class SuccessReviewSerializer(serializers.ModelSerializer):
    scheduledAt = serializers.DateTimeField(source="scheduled_at", read_only=True)

    class Meta:
        model = SuccessReview
        fields = ["id", "scheduledAt", "agenda"]
        read_only_fields = fields


class FeedbackPulseSubmitSerializer(serializers.Serializer):
    """
    WRITE-ONLY. There is no read serializer for a pulse on the client plane, and adding
    one would break the privacy promise in §12I.

    Note what this is NOT: a ModelSerializer. A ModelSerializer would return the created
    instance's fields — including ``score`` — straight back in the response body.
    """

    score = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True)
    wants_follow_up = serializers.BooleanField(required=False, default=False)


class SupportRequestCreateSerializer(serializers.Serializer):
    body = serializers.CharField()
    subject = serializers.CharField(required=False, allow_blank=True, max_length=300)


# ═════════════════════════════════════════════════════════════════════════════
# TEAM PLANE — the success team's view
# ═════════════════════════════════════════════════════════════════════════════
# These carry the internal signals. They are mounted ONLY behind team-JWT views and must
# never be imported by a client-plane view.


class TeamFeedbackPulseSerializer(serializers.ModelSerializer):
    """
    TEAM ONLY. Carries ``score``.

    Visible to the SUCCESS TEAM and to no one else — not to the customer, and not on any
    analytics surface that could be filtered down to a single customer.
    """

    wantsFollowUp = serializers.BooleanField(source="wants_follow_up", read_only=True)
    acknowledgedAt = serializers.DateTimeField(source="acknowledged_at", read_only=True)
    isNegative = serializers.BooleanField(source="is_negative", read_only=True)
    at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = FeedbackPulse
        fields = ["id", "score", "comment", "wantsFollowUp", "isNegative", "acknowledgedAt", "at"]
        read_only_fields = fields


class TeamSupportRequestSerializer(SupportRequestSerializer):
    """TEAM. Adds the owning client and the SLA state."""

    clientId = serializers.CharField(source="client_id", read_only=True)
    threadId = serializers.CharField(source="thread_id", read_only=True)
    firstResponseAt = serializers.DateTimeField(source="first_response_at", read_only=True)
    customerConfirmedResolved = serializers.BooleanField(
        source="customer_confirmed_resolved", read_only=True
    )

    class Meta(SupportRequestSerializer.Meta):
        fields = [
            *SupportRequestSerializer.Meta.fields,
            "clientId", "threadId", "firstResponseAt", "customerConfirmedResolved",
        ]
        read_only_fields = fields


class TeamCustomerHealthSerializer(serializers.Serializer):
    """
    TEAM ONLY. The health board row.

    ``customer_health`` is on the §10.5 internal-only list. It appears here and nowhere
    else.
    """

    clientId = serializers.CharField()
    organization = serializers.CharField()
    health = serializers.CharField()
    reasons = serializers.ListField(child=serializers.CharField())
    blockingSupport = serializers.BooleanField()
    outcomesOffPlan = serializers.IntegerField()
    negativePulse = serializers.BooleanField()
    degradedDeployments = serializers.IntegerField()
    expansionAllowed = serializers.BooleanField()
