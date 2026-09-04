from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [("result_page", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="ClientPageAccessGrant",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("code_hash", models.CharField(db_index=True, max_length=64, unique=True)),
                ("visitor_session_hash", models.CharField(blank=True, default="", max_length=64)),
                ("client_id", models.CharField(blank=True, db_index=True, default="", max_length=128)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("lead", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="client_page_access_grants", to="leads.lead")),
            ],
            options={"abstract": False},
        ),
        migrations.CreateModel(
            name="ClientPageAccessSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("token_hash", models.CharField(db_index=True, max_length=64, unique=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("grant", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="access_session", to="result_page.clientpageaccessgrant")),
            ],
            options={"abstract": False},
        ),
        migrations.AddIndex(
            model_name="clientpageaccessgrant",
            index=models.Index(fields=["lead", "expires_at"], name="result_page_lead_id_exp_idx"),
        ),
    ]
