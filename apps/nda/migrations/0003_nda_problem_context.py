from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("nda", "0002_ndarecord_body_ndarecord_decline_reason_and_more")]
    operations = [
        migrations.AddField(model_name="ndarecord", name="problem_context", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="ndarecord", name="workload_context", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="ndarecord", name="desired_outcome", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="ndarecord", name="discussion_reason", field=models.TextField(blank=True, default="")),
    ]
