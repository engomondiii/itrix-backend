"""Result Page URLs (mounted under /api/v1/result-page/).

    GET  {lead_id}/   PUBLIC
    POST generate/    JWT
"""

from __future__ import annotations

from django.urls import path

from apps.result_page.views import ResultPageDetailView, ResultPageGenerateView

app_name = "result_page"

urlpatterns = [
    path("generate/", ResultPageGenerateView.as_view(), name="result-generate"),
    path("<str:lead_id>/", ResultPageDetailView.as_view(), name="result-detail"),
]
