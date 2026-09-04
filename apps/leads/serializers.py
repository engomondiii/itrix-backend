"""
Lead serializers.

These produce the exact camelCase shapes the dashboard consumes
(``itrix-dashboard/src/types/lead.ts``): ``Lead``, ``LeadListItem``, ``LeadNote``,
``LeadActivity``. ``productRoute`` / ``commercialPath`` are emitted as the dashboard's
display strings; ``status`` and ``specialRights`` are stored as display labels already.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.leads.models import ASTOPEngagement, Lead, LeadActivity, LeadMeeting, LeadNote


class LeadNoteSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = LeadNote
        fields = ["id", "body", "author", "createdAt"]
        read_only_fields = fields

    def get_author(self, obj) -> str:
        return obj.author_name or (obj.author.display_name if obj.author else "")


class LeadActivitySerializer(serializers.ModelSerializer):
    at = serializers.DateTimeField(source="created_at", read_only=True)
    by = serializers.SerializerMethodField()

    class Meta:
        model = LeadActivity
        fields = ["id", "type", "label", "at", "by"]
        read_only_fields = fields

    def get_by(self, obj) -> str | None:
        return obj.by_name or (obj.by.display_name if obj.by else None)


class LeadMeetingSerializer(serializers.ModelSerializer):
    scheduledAt = serializers.DateTimeField(source="scheduled_at")
    durationMins = serializers.IntegerField(source="duration_mins")
    location = serializers.CharField(allow_blank=True)
    notes = serializers.CharField(allow_blank=True, required=False)
    bookedBy = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = LeadMeeting
        fields = ["id", "scheduledAt", "durationMins", "attendee", "location", "notes", "bookedBy", "createdAt"]
        read_only_fields = fields

    def get_bookedBy(self, obj) -> str | None:
        return obj.booked_by_name or (obj.booked_by.display_name if obj.booked_by else None)


class _LeadBaseSerializer(serializers.ModelSerializer):
    """Shared computed fields for list + detail."""

    visitorName = serializers.CharField(source="visitor_name", allow_blank=True)
    productRoute = serializers.SerializerMethodField()
    commercialPath = serializers.SerializerMethodField()
    primaryPain = serializers.CharField(source="primary_pain", allow_blank=True)
    specialRights = serializers.CharField(source="special_rights")
    submittedAt = serializers.DateTimeField(source="submitted_at", read_only=True)
    owner = serializers.SerializerMethodField()

    def get_productRoute(self, obj) -> str:
        return obj.product_route_display

    def get_commercialPath(self, obj) -> str:
        return obj.commercial_path_display

    def get_owner(self, obj) -> str | None:
        return obj.owner.display_name if obj.owner else None

    # v4.0 journey exposure
    journeyState = serializers.CharField(source="journey_state", read_only=True)
    clientId = serializers.SerializerMethodField()
    valueDelivered = serializers.SerializerMethodField()

    def get_clientId(self, obj) -> str | None:
        account = getattr(obj, "client_account", None)
        return str(account.id) if account else None

    def get_valueDelivered(self, obj) -> bool:
        return getattr(obj, "value_delivered_at", None) is not None


class LeadListSerializer(_LeadBaseSerializer):
    """Lightweight row for the leads table (``LeadListItem``)."""

    class Meta:
        model = Lead
        fields = [
            "id",
            "visitorName",
            "company",
            "industry",
            "role",
            "productRoute",
            "commercialPath",
            "primaryPain",
            "score",
            "tier",
            "status",
            "owner",
            "specialRights",
            "submittedAt",
            "journeyState",
        ]
        read_only_fields = fields


class LeadDetailSerializer(_LeadBaseSerializer):
    """Full lead record (``Lead``) including nested notes + activity."""

    computeBottleneck = serializers.CharField(source="compute_bottleneck", allow_blank=True)
    workloadType = serializers.CharField(source="workload_type", allow_blank=True)
    currentStack = serializers.ListField(source="current_stack", child=serializers.CharField())
    commercialIntent = serializers.CharField(source="commercial_intent", allow_blank=True)
    scoreBreakdown = serializers.JSONField(source="score_breakdown")
    recommendedNextStep = serializers.CharField(source="recommended_next_step", allow_blank=True)
    humanHandoffTrigger = serializers.BooleanField(source="human_handoff_trigger")
    ctaClicked = serializers.CharField(source="cta_clicked", allow_blank=True)
    documentsViewed = serializers.IntegerField(source="documents_viewed")
    qualification = serializers.JSONField()
    notes = LeadNoteSerializer(many=True, read_only=True)
    activity = LeadActivitySerializer(source="activities", many=True, read_only=True)
    meetings = LeadMeetingSerializer(many=True, read_only=True)
    legalEntity = serializers.CharField(source="legal_entity", read_only=True)
    corporateDomain = serializers.CharField(source="corporate_domain", read_only=True)
    businessUnit = serializers.CharField(source="business_unit", read_only=True)
    sponsor = serializers.CharField(read_only=True)
    acquisitionContext = serializers.JSONField(source="acquisition_context", read_only=True)
    trustScreening = serializers.JSONField(source="trust_screening", read_only=True)
    trustStatus = serializers.CharField(source="trust_status", read_only=True)
    currentMarketingStage = serializers.CharField(source="current_marketing_stage", read_only=True)
    commercialProgress = serializers.JSONField(source="commercial_progress", read_only=True)
    astop = serializers.SerializerMethodField()

    def get_astop(self, obj):
        record = ASTOPEngagement.objects.filter(lead=obj).first()
        if record is None:
            return None
        return {
            "stage": record.stage,
            "qualificationContext": record.qualification_context,
            "evaluationScope": record.evaluation_scope,
            "decisionFidelity": record.decision_fidelity,
            "measuredSavings": record.measured_savings,
            "estimatedSavings": record.estimated_savings,
            "evaluationResult": record.evaluation_result,
            "loScope": record.lo_scope,
            "loExecutedAt": record.lo_executed_at,
            "entitlementStatus": record.entitlement_status,
            "verifiedValue": record.verified_value,
            "ttfvSeconds": record.ttfv_seconds,
        }

    class Meta:
        model = Lead
        fields = [
            "id",
            "visitorName",
            "company",
            "email",
            "industry",
            "role",
            "productRoute",
            "commercialPath",
            "computeBottleneck",
            "primaryPain",
            "workloadType",
            "currentStack",
            "commercialIntent",
            "specialRights",
            "timeline",
            "score",
            "tier",
            "scoreBreakdown",
            "recommendedNextStep",
            "humanHandoffTrigger",
            "status",
            "owner",
            "ctaClicked",
            "documentsViewed",
            "submittedAt",
            "journeyState",
            "clientId",
            "valueDelivered",
            "qualification",
            "notes",
            "activity",
            "meetings",
            "legalEntity", "corporateDomain", "businessUnit", "sponsor",
            "acquisitionContext", "trustScreening", "trustStatus", "currentMarketingStage",
            "commercialProgress", "astop",
        ]
        read_only_fields = fields


class LeadUpdateSerializer(serializers.ModelSerializer):
    """Writable subset for PATCH /leads/{id}/ (status, owner handled via actions too)."""

    visitorName = serializers.CharField(source="visitor_name", required=False, allow_blank=True)
    primaryPain = serializers.CharField(source="primary_pain", required=False, allow_blank=True)
    ctaClicked = serializers.CharField(source="cta_clicked", required=False, allow_blank=True)
    documentsViewed = serializers.IntegerField(source="documents_viewed", required=False)

    class Meta:
        model = Lead
        fields = [
            "visitorName",
            "company",
            "email",
            "industry",
            "role",
            "primaryPain",
            "status",
            "ctaClicked",
            "documentsViewed",
        ]


# ── Action payload serializers ───────────────────────────────────────────────
class AssignSerializer(serializers.Serializer):
    owner = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    # Opt-in takeover. Absent means assign-if-unowned, so the safe behaviour is the
    # one you get by not thinking about it (see LeadViewSet.assign).
    force = serializers.BooleanField(required=False, default=False)


class StatusSerializer(serializers.Serializer):
    status = serializers.CharField()


class NoteSerializer(serializers.Serializer):
    body = serializers.CharField()


class EscalateSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    priority = serializers.ChoiceField(
        choices=["normal", "high", "urgent"], required=False, default="normal"
    )


class MeetingSerializer(serializers.Serializer):
    """Payload for the book-meeting action (dashboard ``BookMeetingDialog``)."""

    scheduledAt = serializers.DateTimeField(source="scheduled_at")
    durationMins = serializers.IntegerField(source="duration_mins", required=False, default=30)
    attendee = serializers.CharField(allow_blank=True, required=False, default="")
    location = serializers.CharField(allow_blank=True, required=False, default="")
    notes = serializers.CharField(allow_blank=True, required=False, default="")


class LeadEmailCaptureSerializer(serializers.Serializer):
    """Public lead-capture/email/ body sent by the web proxy."""

    lead_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    session_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    name = serializers.CharField(required=False, allow_blank=True, default="")
    company = serializers.CharField(required=False, allow_blank=True, default="")
    source = serializers.CharField(required=False, allow_blank=True, default="web")

class AcquisitionSerializer(serializers.Serializer):
    source_channel = serializers.CharField(required=False, allow_blank=True, default="")
    campaign_content = serializers.CharField(required=False, allow_blank=True, default="")
    referral_or_intro = serializers.CharField(required=False, allow_blank=True, default="")
    problem_topic = serializers.CharField(required=False, allow_blank=True, default="")
    anonymous_session_id = serializers.CharField(required=False, allow_blank=True, default="")


class TrustScreeningSerializer(serializers.Serializer):
    identity_confidence = serializers.CharField(required=False, allow_blank=True, default="")
    use_case_coherence = serializers.CharField(required=False, allow_blank=True, default="")
    protection_acceptance = serializers.BooleanField(required=False, default=False)
    copying_signal = serializers.BooleanField(required=False, default=False)
    extraction_signal = serializers.BooleanField(required=False, default=False)
    redistribution_signal = serializers.BooleanField(required=False, default=False)
    rationale = serializers.CharField(required=True, allow_blank=False)
    status = serializers.ChoiceField(choices=["pass", "review", "reject"])


class ASTOPProgressSerializer(serializers.Serializer):
    stage = serializers.ChoiceField(choices=["identify_qualify", "nda_briefing", "controlled_evaluation", "lo_deployment", "verify_expand", "closed"])
    qualification_context = serializers.JSONField(required=False)
    evaluation_agreement = serializers.CharField(required=False, allow_blank=True)
    evaluation_scope = serializers.JSONField(required=False)
    baseline = serializers.JSONField(required=False)
    decision_fidelity = serializers.JSONField(required=False)
    measured_savings = serializers.JSONField(required=False)
    estimated_savings = serializers.JSONField(required=False)
    evaluation_result = serializers.JSONField(required=False)
    security_result = serializers.JSONField(required=False)
    integration_feasibility = serializers.JSONField(required=False)
    controlled_build_id = serializers.CharField(required=False, allow_blank=True)
    attribution_id = serializers.CharField(required=False, allow_blank=True)
    lo_scope = serializers.JSONField(required=False)
    lo_executed_at = serializers.DateTimeField(required=False, allow_null=True)
    entitlement_status = serializers.CharField(required=False, allow_blank=True)
    authorized_install_at = serializers.DateTimeField(required=False, allow_null=True)
    reproducible_value_at = serializers.DateTimeField(required=False, allow_null=True)
    verified_value = serializers.JSONField(required=False)
    expansion = serializers.JSONField(required=False)


class AlphaAssessmentSerializer(serializers.Serializer):
    separate_workload = serializers.CharField()
    technical_route = serializers.ChoiceField(choices=["axiom", "axiom_tensor", "cre", "fqnm", "qnta"])
    scope = serializers.CharField(required=False, allow_blank=True, default="")
