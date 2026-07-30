"""
v7.1 Phase 3 — the assent record.

``client`` is SET_NULL rather than CASCADE, deliberately: the record is EVIDENCE and has to
outlive the account. A dispute about what someone agreed to does not become moot because
they closed their workspace.
"""

from __future__ import annotations

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("clients", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssentRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("client_email_at_assent", models.EmailField(blank=True, default="", max_length=254)),
                ("instruments", models.JSONField(default=list)),
                (
                    "path",
                    models.CharField(
                        choices=[
                            ("invite_claim", "Invite claim (emailed capability link)"),
                            ("invite_code", "Invite redemption (code entered)"),
                            ("open_registration", "Open registration"),
                            ("reprompt", "Re-prompted after a version change"),
                        ],
                        db_index=True,
                        default="invite_claim",
                        max_length=24,
                    ),
                ),
                ("accepted_at_client", models.DateTimeField(blank=True, null=True)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, default="", max_length=300)),
                (
                    "client",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assent_records",
                        to="clients.client",
                    ),
                ),
            ],
            options={
                "verbose_name": "Assent record",
                "verbose_name_plural": "Assent records",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="assentrecord",
            index=models.Index(fields=["client", "-created_at"], name="legal_assen_client__d510ca_idx"),
        ),
        migrations.AddIndex(
            model_name="assentrecord",
            index=models.Index(fields=["client_email_at_assent"], name="legal_assen_client__b60686_idx"),
        ),
    ]
