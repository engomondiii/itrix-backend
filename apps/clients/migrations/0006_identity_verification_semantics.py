from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("clients", "0005_client_nda_requested_at")]
    operations = [
        migrations.AddField(
            model_name="client",
            name="claimed_identity",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="client",
            name="identity_verified_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="client",
            name="organization_verified_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
