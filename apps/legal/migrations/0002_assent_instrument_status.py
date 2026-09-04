from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("legal", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="assentrecord",
            name="instrument_status",
            field=models.CharField(
                choices=[
                    ("draft_acknowledgement", "Draft acknowledgement"),
                    ("published_assent", "Published-instrument assent"),
                ],
                db_index=True,
                default="published_assent",
                max_length=24,
            ),
        ),
    ]
