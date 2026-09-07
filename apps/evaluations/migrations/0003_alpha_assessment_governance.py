from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("evaluations", "0002_evaluation_fee_evaluation_scope_evaluation_timeline")]
    operations = [
        migrations.AddField(model_name="evaluation", name="separate_workload", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="evaluation", name="technical_route", field=models.CharField(choices=[("none", "None / not yet selected"), ("axiom", "AXIOM"), ("axiom_tensor", "AXIOM-TENSOR"), ("cre", "CRE"), ("fqnm", "FQNM"), ("qnta", "QNTA")], default="none", max_length=24)),
        migrations.AddField(model_name="evaluation", name="eligibility_status", field=models.CharField(blank=True, default="unassessed", max_length=24)),
        migrations.AddField(model_name="evaluation", name="proof_status", field=models.CharField(blank=True, default="pending", max_length=24)),
        migrations.AddField(model_name="evaluation", name="standard_assessment_fee", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name="evaluation", name="ai_waiver_decision", field=models.CharField(choices=[("none", "No waiver"), ("full", "Full waiver"), ("partial", "Partial waiver")], default="none", max_length=16)),
        migrations.AddField(model_name="evaluation", name="waiver_type", field=models.CharField(choices=[("none", "No waiver"), ("full", "Full waiver"), ("partial", "Partial waiver")], default="none", max_length=16)),
        migrations.AddField(model_name="evaluation", name="waiver_percentage_or_amount", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="evaluation", name="waiver_reason", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="evaluation", name="waiver_scope", field=models.CharField(blank=True, default="assessment_fee_only", max_length=255)),
        migrations.AddField(model_name="evaluation", name="waiver_expiry", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="evaluation", name="iwl_override_status", field=models.CharField(blank=True, default="none", max_length=24)),
        migrations.AddField(model_name="evaluation", name="iwl_override_applied", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="evaluation", name="iwl_override_reason", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="evaluation", name="final_assessment_fee", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name="evaluation", name="final_authority", field=models.CharField(blank=True, default="", max_length=24)),
        migrations.AddField(model_name="evaluation", name="fee_finalized_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="evaluation", name="customer_fee_status", field=models.CharField(blank=True, default="paid_default_pending_quote", max_length=64)),
        migrations.AddField(model_name="evaluation", name="hardware_value_case", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="evaluation", name="hardware_target", field=models.CharField(blank=True, default="", max_length=120)),
        migrations.AddField(model_name="evaluation", name="hardware_economics", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="evaluation", name="hardware_sponsor", field=models.CharField(blank=True, default="", max_length=255)),
    ]
