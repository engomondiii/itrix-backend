from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge_core", "0005_alter_knowledgedocument_technology_family"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledgedocument",
            name="canonical_entities",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="knowledgedocument",
            name="related_products",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="knowledgedocument",
            name="technology_families",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
