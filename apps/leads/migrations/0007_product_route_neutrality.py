from django.db import migrations, models


def neutralize_safe_self_serve_defaults(apps, schema_editor):
    Lead = apps.get_model("leads", "Lead")
    # Only rows whose provenance and empty qualification fields make the old ``general``
    # value deterministically a signup default are rewritten. Ambiguous historical general
    # rows are preserved rather than fabricating a route.
    candidates = Lead.objects.filter(
        product_route="general",
        lead_source="self_serve",
        score=0,
        current_marketing_stage="discovery",
    )
    for lead in candidates.iterator():
        if any(
            [
                (lead.workload_type or "").strip(),
                (lead.primary_pain or "").strip(),
                (lead.compute_bottleneck or "").strip(),
                (lead.commercial_intent or "").strip(),
                bool(lead.qualification or {}),
            ]
        ):
            continue
        lead.product_route = "undetermined"
        lead.save(update_fields=["product_route"])


class Migration(migrations.Migration):
    dependencies = [("leads", "0006_astop_commercial_progression")]

    operations = [
        migrations.AlterField(
            model_name="lead",
            name="product_route",
            field=models.CharField(
                choices=[
                    ("undetermined", "Not yet assessed"),
                    ("astop", "ASTOP"),
                    ("alpha_compute", "ALPHA Compute"),
                    ("alpha_core", "ALPHA Core"),
                    ("both", "Multiple products (legacy)"),
                    ("general", "General / legacy"),
                ],
                default="undetermined",
                max_length=20,
            ),
        ),
        migrations.RunPython(neutralize_safe_self_serve_defaults, migrations.RunPython.noop),
    ]
