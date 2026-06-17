"""
Scoring views.

Scoring runs *internally* inside the review flow. This JWT-only preview endpoint lets
internal tools score an answer set without creating a lead. Not mounted in
api/v1/urls.py for Phase 2 (no endpoint in the spec map); provided for internal use.
"""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsDashboardUser
from apps.scoring.serializers import ScorePreviewSerializer
from apps.scoring.services.scorer import score_answers


class ScorePreviewView(APIView):
    permission_classes = [IsAuthenticated, IsDashboardUser]

    def post(self, request):
        serializer = ScorePreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = score_answers(serializer.validated_data["answers"])
        return Response(result.to_dict())
