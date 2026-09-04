from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("knowledge_core", "0003_hard_facts_and_content_authorization")]
    operations = [
        migrations.AddField(
            model_name="knowledgedocument",
            name="entity_type",
            field=models.CharField(choices=[("product", "Product"), ("technology", "Technology"), ("platform", "Commercialization platform"), ("research", "Research"), ("governance", "Governance"), ("mixed", "Mixed")], db_index=True, default="mixed", max_length=20),
        ),
        migrations.AddField(
            model_name="knowledgedocument",
            name="evidence_status",
            field=models.CharField(choices=[("mathematical", "Mathematical"), ("experimental", "Experimental"), ("implemented", "Implemented"), ("validated", "Validated"), ("value_verified", "Value-Verified"), ("licensable", "Licensable"), ("governance", "Governance / policy"), ("mixed", "Mixed")], db_index=True, default="mixed", max_length=24),
        ),
    ]
