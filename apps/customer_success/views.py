"""
Customer-success views (Backend v6.0 §7.1).

    GET  portal/success/overview/     the standing summary
    GET  portal/success/outcomes/     the customer's agreed outcomes
    GET  portal/success/deployments/  health, versions, known limitations
    GET  portal/success/support/      open requests
    POST portal/success/support/      open a request
    GET  portal/success/plan/         the shared 30/60/90 plan
    GET  portal/success/changes/      what changed since the last visit
    GET  portal/success/team/         named humans
    GET  portal/success/knowledge/    release notes
    POST portal/success/feedback/     private pulse — WRITE ONLY

── THE FEEDBACK ENDPOINT IS WRITE-ONLY, AND THAT IS DELIBERATE ──────────────
There is no GET on feedback. A customer can submit a pulse and cannot read one back. If
they could, the score would exist in a client-plane payload — and once it exists there,
some future surface renders it. §12I promises the pulse is private; write-only is the
only version of that promise which survives refactoring.

── EVERY VIEW IS GATED BY THE OVERLAY, NOT BY THE CONTRACT ──────────────────
``HasSuccessOverlay`` activates at FIRST PAYMENT (R16). A paid Assessment customer
reaches support and a named owner immediately — waiting for license-out would leave the
riskiest period of the relationship as the one with the least support.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clients.permissions import IsAuthenticatedClient
from apps.customer_success.permissions import HasSuccessOverlay
from apps.customer_success.serializers import (
    ChangeLogEntrySerializer,
    DeploymentHealthSerializer,
    FeedbackPulseSubmitSerializer,
    OutcomeSerializer,
    RelationshipTeamMemberSerializer,
    ReleaseNoteSerializer,
    SuccessPlanSerializer,
    SupportRequestCreateSerializer,
    SupportRequestSerializer,
)
from apps.customer_success.services import (
    change_digest,
    feedback_pulse,
    outcome_tracker,
    success_plan,
    success_review,
    support_router,
)

logger = logging.getLogger("itrix")


class _SuccessView(APIView):
    """Shared base: client-JWT plus the overlay gate."""

    permission_classes = [IsAuthenticatedClient, HasSuccessOverlay]

    @property
    def client(self):
        return self.request.user


class SuccessOverviewView(_SuccessView):
    """GET portal/success/overview/ — 'Welcome back. Here is where things stand.'"""

    def get(self, request):
        from apps.customer_success.models import (
            DeploymentHealth,
            RelationshipTeamMember,
            SupportRequest,
        )

        client = self.client
        review = success_review.upcoming(client)
        return Response(
            {
                "welcome": "Welcome back. Here is where things stand.",
                "composerLabel": "What can we improve for you?",
                "outcomes": OutcomeSerializer(
                    outcome_tracker.for_client(client)[:10], many=True
                ).data,
                "deployments": DeploymentHealthSerializer(
                    DeploymentHealth.objects.filter(client=client), many=True
                ).data,
                "openSupport": SupportRequest.objects.filter(
                    client=client, resolved_at__isnull=True
                ).count(),
                "team": RelationshipTeamMemberSerializer(
                    RelationshipTeamMember.objects.filter(client=client), many=True
                ).data,
                "nextReview": review.scheduled_at.isoformat() if review else None,
            }
        )


class OutcomesView(_SuccessView):
    """GET portal/success/outcomes/ — 'These are the outcomes we agreed together.'"""

    def get(self, request):
        return Response(
            {
                "intro": "These are the outcomes we agreed together, and where each one stands.",
                "outcomes": OutcomeSerializer(
                    outcome_tracker.for_client(self.client), many=True
                ).data,
            }
        )


class DeploymentsView(_SuccessView):
    def get(self, request):
        from apps.customer_success.models import DeploymentHealth

        return Response(
            {
                "intro": (
                    "Current operational status, when we last checked, anything that has "
                    "gone wrong, the versions you are running, and the limitations we "
                    "know about."
                ),
                "knownLimitationsFraming": (
                    "These are the limitations we already know about. We would rather "
                    "you hear them from us."
                ),
                "deployments": DeploymentHealthSerializer(
                    DeploymentHealth.objects.filter(client=self.client), many=True
                ).data,
            }
        )


class SupportView(_SuccessView):
    """GET / POST portal/success/support/."""

    def get(self, request):
        from apps.customer_success.models import SupportRequest

        return Response(
            {
                "intro": "Your open requests, who owns each one, and when you can expect a response.",
                "placeholder": "Describe what is not working, or what you need help with.",
                "requests": SupportRequestSerializer(
                    SupportRequest.objects.filter(client=self.client), many=True
                ).data,
            }
        )

    def post(self, request):
        serializer = SupportRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        support = support_router.route(
            self.client,
            serializer.validated_data["body"],
            subject=serializer.validated_data.get("subject", ""),
        )
        return Response(
            {
                "acknowledgement": support_router.acknowledge_copy(support),
                "request": SupportRequestSerializer(support).data,
            },
            status=status.HTTP_201_CREATED,
        )


class SuccessPlanView(_SuccessView):
    def get(self, request):
        from apps.customer_success.models import SuccessPlan

        plan = SuccessPlan.objects.filter(client=self.client, is_active=True).first()
        return Response(
            {
                "intro": (
                    "The goals we agreed for the next 30, 60 and 90 days, who owns each "
                    "one on both sides, and what we are measuring."
                ),
                "dependencyFraming": (
                    "These items need something from your side. We have flagged them "
                    "early so they do not surprise anyone."
                ),
                "plan": SuccessPlanSerializer(plan).data if plan else None,
                "awaitingYou": success_plan.pending_customer_actions(self.client).count(),
            }
        )


class ChangesView(_SuccessView):
    def get(self, request):
        digest = change_digest.build(self.client)
        return Response(
            {
                "intro": (
                    "Work we completed, issues we resolved, updates we shipped, and "
                    "anything waiting on a decision from you."
                ),
                **digest,
            }
        )


class RelationshipTeamView(_SuccessView):
    def get(self, request):
        from apps.customer_success.models import RelationshipTeamMember

        return Response(
            {
                "intro": (
                    "These are the people who own your relationship. You can reach any "
                    "of them directly."
                ),
                "team": RelationshipTeamMemberSerializer(
                    RelationshipTeamMember.objects.filter(client=self.client), many=True
                ).data,
            }
        )


class KnowledgeView(_SuccessView):
    def get(self, request):
        from apps.customer_success.models import ReleaseNote

        notes = ReleaseNote.objects.filter(is_published=True).filter(
            customer_scope__in=["", str(self.client.id)]
        )
        return Response(
            {
                "intro": (
                    "Training for each role on your team, documentation, release notes, "
                    "and the practices we recommend."
                ),
                "releaseNotes": ReleaseNoteSerializer(notes, many=True).data,
            }
        )


class FeedbackView(_SuccessView):
    """
    POST portal/success/feedback/ — WRITE ONLY.

    There is deliberately no ``get``. The response carries an acknowledgement and
    NOTHING about the pulse itself — not the score, not an id, not a timestamp that
    could be correlated.
    """

    def post(self, request):
        serializer = FeedbackPulseSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        feedback_pulse.submit(
            self.client,
            score=serializer.validated_data.get("score"),
            comment=serializer.validated_data.get("comment", ""),
            wants_follow_up=serializer.validated_data.get("wants_follow_up", False),
        )
        return Response(
            {"detail": feedback_pulse.ACKNOWLEDGEMENT, "prompt": feedback_pulse.PROMPT},
            status=status.HTTP_201_CREATED,
        )
