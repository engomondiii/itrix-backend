"""
Legal routes.

``legal/instruments/`` is PUBLIC and mounted at the API root. ``portal/legal/assent/`` is
CLIENT-plane and mounted under the portal prefix — the two are deliberately separate
modules' worth of routing because they sit on different planes, and a single include would
make it easy to move one behind the other's permissions by accident.
"""

from __future__ import annotations

from django.urls import path

from apps.legal.views import LegalInstrumentsView, PortalAssentView

app_name = "legal"

public_urlpatterns = [
    path("legal/instruments/", LegalInstrumentsView.as_view(), name="instruments"),
]

portal_urlpatterns = [
    path("portal/legal/assent/", PortalAssentView.as_view(), name="portal-assent"),
]

urlpatterns = public_urlpatterns + portal_urlpatterns
