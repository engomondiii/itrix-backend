from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("knowledge_core", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="knowledgedocument", name="disclosure_level",
            field=models.CharField(
                choices=[
                    ("public", "Public"),
                    ("controlled_public", "Controlled public"),
                    ("authorized", "Authorized"),
                    ("nda_only", "Agreement-gated / NDA"),
                    ("customer_contract", "Private workspace / customer contract"),
                    ("internal_only", "Role-restricted / internal"),
                    ("prohibited", "Prohibited — never embed or retrieve"),
                ], default="public", max_length=24,
            ),
        ),
        migrations.AlterField(
            model_name="knowledgechunk", name="disclosure_level",
            field=models.CharField(
                choices=[
                    ("public", "Public"),
                    ("controlled_public", "Controlled public"),
                    ("authorized", "Authorized"),
                    ("nda_only", "Agreement-gated / NDA"),
                    ("customer_contract", "Private workspace / customer contract"),
                    ("internal_only", "Role-restricted / internal"),
                    ("prohibited", "Prohibited — never embed or retrieve"),
                ], default="public", max_length=24,
            ),
        ),
        migrations.AlterField(
            model_name="claimrecord", name="disclosure_level",
            field=models.CharField(
                choices=[
                    ("public", "Public"),
                    ("controlled_public", "Controlled public"),
                    ("authorized", "Authorized"),
                    ("nda_only", "Agreement-gated / NDA"),
                    ("customer_contract", "Private workspace / customer contract"),
                    ("internal_only", "Role-restricted / internal"),
                    ("prohibited", "Prohibited — never embed or retrieve"),
                ], default="public", max_length=24,
            ),
        ),
        migrations.AddField(model_name="knowledgedocument", name="source_authority", field=models.CharField(choices=[("authoritative", "Authoritative register / executed record"), ("governing", "Current approved governing document"), ("working", "Working technical document"), ("legacy", "Legacy / superseded material")], db_index=True, default="working", max_length=20)),
        migrations.AddField(model_name="knowledgedocument", name="is_current", field=models.BooleanField(db_index=True, default=True)),
        migrations.AddField(model_name="knowledgedocument", name="verified_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="knowledgedocument", name="canonical_rule", field=models.CharField(blank=True, default="", max_length=512)),
        migrations.AddField(model_name="knowledgedocument", name="approved_audience", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="knowledgedocument", name="allowed_journey_stages", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="knowledgedocument", name="approval_owner", field=models.CharField(blank=True, default="", max_length=255)),
        migrations.AddField(model_name="knowledgedocument", name="approval_date", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="knowledgedocument", name="review_after", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="knowledgedocument", name="permitted_paraphrase", field=models.CharField(choices=[("none", "No external paraphrase"), ("summary", "Approved summary only"), ("approved", "Approved wording / bounded paraphrase"), ("full", "Full-source paraphrase within disclosure ceiling")], default="approved", max_length=16)),
        migrations.AddField(model_name="knowledgedocument", name="technology_family", field=models.CharField(choices=[("general", "General / cross-cutting"), ("axiom", "AXIOM"), ("cre", "CRE"), ("fqnm", "FQNM"), ("alpha_compute", "ALPHA Compute"), ("alpha_core", "ALPHA Core"), ("cross_cutting", "Boundary-aware / cross-cutting")], db_index=True, default="general", max_length=20)),
        migrations.AddField(model_name="knowledgedocument", name="claim_ceiling", field=models.PositiveSmallIntegerField(default=0)),
    ]
