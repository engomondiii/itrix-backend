from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("conversations", "0005_thread_engagement_state")]

    operations = [
        migrations.AddField(
            model_name="thread",
            name="creation_idempotency_hash",
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="thread",
            name="creation_payload_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
