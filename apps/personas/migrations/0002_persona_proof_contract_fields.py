from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("personas", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="persona",
            name="eligibility_gate",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="persona",
            name="proof_contract",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="persona",
            name="expansion_rule",
            field=models.TextField(blank=True, default=""),
        ),
    ]
