"""
v7.1 Phase 2 — ``StreamGuardHit.matcher_pass``.

Records WHICH matcher pass caught a halt: the raw buffer, or the marker-normalised copy
(Architecture v2.8 §19.9 rule 5).

Additive and non-destructive. Every existing row defaults to ``raw``, which is not a
convenient fiction — it is the truth. The normalised pass did not exist when those rows
were written, so every one of them came from the raw matcher.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("governance", "0003_phase3"),
    ]

    operations = [
        migrations.AddField(
            model_name="streamguardhit",
            name="matcher_pass",
            field=models.CharField(
                choices=[("raw", "Raw buffer"), ("normalised", "Marker-normalised buffer")],
                db_index=True,
                default="raw",
                max_length=16,
            ),
        ),
    ]
