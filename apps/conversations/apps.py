"""AppConfig for the conversations app (durable, governed chat)."""

from __future__ import annotations

from django.apps import AppConfig


class ConversationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.conversations"
    label = "conversations"
    verbose_name = "Conversations"
