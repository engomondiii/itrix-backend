from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("result_page", "0003_result_page_readiness")]

    operations = [
        migrations.AddField(
            model_name="resultpage",
            name="problem_mirror_structured",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="resultpage",
            name="persona_context",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
