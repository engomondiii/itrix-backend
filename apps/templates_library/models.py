"""
Template model.

Reusable templates (email / follow-up / evaluation / poc / handoff) with ``{{variable}}``
placeholders. Matches the dashboard's ``Template`` type
(``{id, kind, name, body, variables[], updatedAt}``). ``variables`` is auto-derived from the
body on save, so it always reflects the placeholders actually present.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class TemplateKind(models.TextChoices):
    EMAIL = "email", "Email"
    FOLLOW_UP = "follow-up", "Follow-up"
    EVALUATION = "evaluation", "Evaluation"
    POC = "poc", "PoC"
    HANDOFF = "handoff", "Handoff"


class Template(BaseModel):
    kind = models.CharField(max_length=16, choices=TemplateKind.choices, default=TemplateKind.EMAIL)
    name = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    variables = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["kind", "name"]
        verbose_name = "Template"
        verbose_name_plural = "Templates"

    def save(self, *args, **kwargs):
        # Keep variables in sync with the body's {{placeholders}}.
        from apps.emails.services.template_renderer import extract_variables

        self.variables = extract_variables(self.body)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Template({self.kind}: {self.name})"
