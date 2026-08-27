from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("result_page", "0002_secure_client_access")]

    operations = [
        migrations.AddField(
            model_name="resultpage",
            name="generation_status",
            field=models.CharField(
                choices=[("pending", "Pending"), ("ready", "Ready"), ("failed", "Failed")],
                db_index=True,
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="resultpage",
            name="generation_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="resultpage",
            name="artifact_family",
            field=models.CharField(blank=True, default="my_review", max_length=48),
        ),
        migrations.AddField(
            model_name="resultpage",
            name="artifact_version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="resultpage",
            name="locale",
            field=models.CharField(blank=True, default="en", max_length=12),
        ),
    ]
