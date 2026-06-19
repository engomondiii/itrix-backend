"""
Lead serializers.

These produce the exact camelCase shapes the dashboard consumes
(``itrix-dashboard/src/types/lead.ts``): ``Lead``, ``LeadListItem``, ``LeadNote``,
``LeadActivity``. ``productRoute`` / ``commercialPath`` are emitted as the dashboard's
display strings; ``status`` and ``specialRights`` are stored as display labels already.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.leads.models import Lead, LeadActivity, LeadMeeting, LeadNote


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
            "qualification",
            "notes",
            "activity",
            "meetings",
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
