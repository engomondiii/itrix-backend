from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("knowledge_core", "0002_governance_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="HardFact",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("key", models.SlugField(max_length=160, unique=True)),
                ("category", models.CharField(choices=[("patent", "Patent / IP"), ("corporate", "Corporate"), ("commercial", "Commercial"), ("benchmark", "Benchmark"), ("customer", "Customer"), ("transaction", "Transaction")], db_index=True, max_length=24)),
                ("public_statement", models.TextField(blank=True, default="")),
                ("jurisdiction", models.CharField(blank=True, default="", max_length=80)),
                ("internal_reference", models.CharField(blank=True, default="", max_length=120)),
                ("official_application_number", models.CharField(blank=True, default="", max_length=120)),
                ("filing_date", models.DateField(blank=True, null=True)),
                ("publication_status", models.CharField(blank=True, default="", max_length=120)),
                ("prosecution_status", models.CharField(blank=True, default="", max_length=120)),
                ("verified_grant_number", models.CharField(blank=True, default="", max_length=120)),
                ("ownership_assignment", models.CharField(blank=True, default="", max_length=255)),
                ("source_reference", models.CharField(blank=True, default="", max_length=512)),
                ("source_authority", models.CharField(choices=[("authoritative", "Authoritative register / executed record"), ("governing", "Current approved governing document"), ("working", "Working technical document"), ("legacy", "Legacy / superseded material")], db_index=True, default="authoritative", max_length=20)),
                ("is_current", models.BooleanField(db_index=True, default=True)),
                ("disclosure_level", models.CharField(choices=[("public", "Public"), ("controlled_public", "Controlled public"), ("authorized", "Authorized"), ("nda_only", "Agreement-gated / NDA"), ("customer_contract", "Private workspace / customer contract"), ("internal_only", "Role-restricted / internal"), ("prohibited", "Prohibited — never embed or retrieve")], default="internal_only", max_length=24)),
                ("approved_audience", models.JSONField(blank=True, default=list)),
                ("claim_ceiling", models.PositiveSmallIntegerField(default=1)),
                ("last_verified_at", models.DateTimeField(blank=True, null=True)),
                ("source_document", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="hard_facts", to="knowledge_core.knowledgedocument")),
            ],
            options={"ordering": ["category", "key"]},
        ),
        migrations.CreateModel(
            name="KnowledgeConflict",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("query_fingerprint", models.CharField(db_index=True, max_length=64)),
                ("topic", models.CharField(blank=True, default="", max_length=160)),
                ("authority", models.CharField(choices=[("authoritative", "Authoritative register / executed record"), ("governing", "Current approved governing document"), ("working", "Working technical document"), ("legacy", "Legacy / superseded material")], max_length=20)),
                ("document_ids", models.JSONField(blank=True, default=list)),
                ("detail", models.CharField(blank=True, default="", max_length=1024)),
                ("resolved", models.BooleanField(db_index=True, default=False)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="ContentAuthorization",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("subject_kind", models.CharField(choices=[("client", "Client"), ("lead", "Lead"), ("thread", "Thread")], db_index=True, max_length=16)),
                ("subject_id", models.CharField(db_index=True, max_length=64)),
                ("scope", models.CharField(blank=True, default="", max_length=255)),
                ("reason", models.CharField(blank=True, default="", max_length=512)),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("authorized_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="knowledge_authorizations", to=settings.AUTH_USER_MODEL)),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="content_authorizations", to="knowledge_core.knowledgedocument")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="contentauthorization",
            constraint=models.UniqueConstraint(fields=("document", "subject_kind", "subject_id"), name="uniq_knowledge_document_subject_authorization"),
        ),
    ]
