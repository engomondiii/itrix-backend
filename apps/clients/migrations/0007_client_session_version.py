from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("clients", "0006_identity_verification_semantics")]

    operations = [
        migrations.AddField(
            model_name="client",
            name="session_version",
            field=models.PositiveBigIntegerField(default=0),
        ),
    ]
