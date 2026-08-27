from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("review", "0002_phase3")]

    operations = [
        migrations.AddField(
            model_name="reviewsession",
            name="access_binding_hash",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64),
        ),
    ]
