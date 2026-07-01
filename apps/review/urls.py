"""Review URL routes (mounted under /api/v1/review/) — PUBLIC."""

from __future__ import annotations

from django.urls import path

from apps.review.views import (
    PromptSubmitView,
    QualifyView,
    ReviewChatView,
    ReviewSessionCreateView,
)

app_name = "review"

urlpatterns = [
    path("sessions/", ReviewSessionCreateView.as_view(), name="session-create"),
    path(
        "sessions/<uuid:session_id>/prompt/",
        PromptSubmitView.as_view(),
        name="prompt-submit",
    ),
    path(
        "sessions/<uuid:session_id>/qualify/",
        QualifyView.as_view(),
        name="qualify",
    ),
    path(
        "sessions/<uuid:session_id>/chat/",
        ReviewChatView.as_view(),
        name="review-chat",
    ),
]
