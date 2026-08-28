from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("personas", "0002_persona_proof_contract_fields")]

    operations = [
        migrations.AddField(
            model_name="persona", name="strategic_lane",
            field=models.CharField(blank=True, choices=[
                ("executive_compute_economics", "Executive Compute Economics"),
                ("infrastructure_capacity_strategy", "Infrastructure Capacity Strategy"),
                ("architecture_platform_fit", "Architecture & Platform Fit"),
                ("technical_validation_delivery_risk", "Technical Validation & Delivery Risk"),
                ("strategic_partnership_commercial_transfer", "Strategic Partnership & Commercial Transfer"),
            ], db_index=True, default="", max_length=64),
        ),
        migrations.AddField(model_name="persona", name="strategic_lane_code", field=models.CharField(blank=True, default="", max_length=16)),
        migrations.AddField(model_name="persona", name="reference_person", field=models.CharField(blank=True, default="", max_length=200)),
        migrations.AddField(model_name="persona", name="reference_role", field=models.CharField(blank=True, default="", max_length=240)),
    ]
