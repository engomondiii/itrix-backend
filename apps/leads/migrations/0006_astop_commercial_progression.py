import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("leads", "0005_lead_lead_source")]
    operations = [
        migrations.AddField(model_name="lead", name="legal_entity", field=models.CharField(blank=True, default="", max_length=255)),
        migrations.AddField(model_name="lead", name="corporate_domain", field=models.CharField(blank=True, default="", max_length=255)),
        migrations.AddField(model_name="lead", name="business_unit", field=models.CharField(blank=True, default="", max_length=255)),
        migrations.AddField(model_name="lead", name="sponsor", field=models.CharField(blank=True, default="", max_length=255)),
        migrations.AddField(model_name="lead", name="acquisition_context", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="lead", name="trust_screening", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="lead", name="trust_status", field=models.CharField(choices=[("unreviewed", "Unreviewed"), ("pass", "Pass"), ("review", "Human review"), ("reject", "Sensitive access blocked")], db_index=True, default="unreviewed", max_length=16)),
        migrations.AddField(model_name="lead", name="current_marketing_stage", field=models.CharField(choices=[("discovery", "Discovery"), ("sales_platform", "AI-Powered Sales Platform"), ("astop", "ASTOP"), ("alpha_compute", "ALPHA Compute"), ("alpha_core", "ALPHA Core")], db_index=True, default="discovery", max_length=24)),
        migrations.AddField(model_name="lead", name="commercial_progress", field=models.JSONField(blank=True, default=dict)),
        migrations.CreateModel(
            name="ASTOPEngagement",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("stage", models.CharField(choices=[("identify_qualify", "Identify & Qualify"), ("nda_briefing", "NDA & Briefing"), ("controlled_evaluation", "Controlled Evaluation"), ("lo_deployment", "License-Out & Deployment"), ("verify_expand", "Verify & Expand"), ("closed", "Closed")], db_index=True, default="identify_qualify", max_length=32)),
                ("qualification_context", models.JSONField(blank=True, default=dict)),
                ("evaluation_agreement", models.CharField(blank=True, default="", max_length=255)),
                ("evaluation_scope", models.JSONField(blank=True, default=dict)),
                ("baseline", models.JSONField(blank=True, default=dict)),
                ("decision_fidelity", models.JSONField(blank=True, default=dict)),
                ("measured_savings", models.JSONField(blank=True, default=dict)),
                ("estimated_savings", models.JSONField(blank=True, default=dict)),
                ("evaluation_result", models.JSONField(blank=True, default=dict)),
                ("security_result", models.JSONField(blank=True, default=dict)),
                ("integration_feasibility", models.JSONField(blank=True, default=dict)),
                ("controlled_build_id", models.CharField(blank=True, default="", max_length=255)),
                ("attribution_id", models.CharField(blank=True, default="", max_length=255)),
                ("lo_scope", models.JSONField(blank=True, default=dict)),
                ("lo_executed_at", models.DateTimeField(blank=True, null=True)),
                ("entitlement_status", models.CharField(blank=True, default="", max_length=32)),
                ("entitlement_expires_at", models.DateTimeField(blank=True, null=True)),
                ("revocation_status", models.CharField(blank=True, default="", max_length=32)),
                ("authorized_install_at", models.DateTimeField(blank=True, null=True)),
                ("reproducible_value_at", models.DateTimeField(blank=True, null=True)),
                ("verified_value", models.JSONField(blank=True, default=dict)),
                ("expansion", models.JSONField(blank=True, default=dict)),
                ("lead", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="astop_engagement", to="leads.lead")),
            ],
            options={"ordering": ["-updated_at"]},
        ),
    ]
