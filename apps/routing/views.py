"""
Routing views.

Routing runs *internally* inside the review flow (qualification_processor), so it is
not part of the public API surface. This small JWT-only preview endpoint lets the
dashboard / internal tools see how a given answer set would route, without creating a
lead. It is intentionally NOT mounted in api/v1/urls.py for Phase 2 (no endpoint in
the spec map); it exists for internal use and tests.
"""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsDashboardUser
from apps.routing.serializers import RoutingPreviewSerializer
from apps.routing.services.license_router import route_license
from apps.routing.services.product_router import route_product


class RoutingPreviewView(APIView):
    permission_classes = [IsAuthenticated, IsDashboardUser]

    def post(self, request):
        serializer = RoutingPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        answers = serializer.validated_data["answers"]
        return Response(
            {
                "product_route": route_product(answers),
                "license_pathway": route_license(answers),
            }
        )
