"""Client-plane ASTOP projection inside the existing Customer Success subsystem."""
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clients.backends import ClientJWTAuthentication
from apps.clients.permissions import IsAuthenticatedClient
from apps.customer_success.permissions import HasSuccessOverlay
from apps.customer_success.services.astop_integration import snapshot


class ASTOPSuccessView(APIView):
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient, HasSuccessOverlay]

    def get(self, request):
        return Response(snapshot(request.user))
