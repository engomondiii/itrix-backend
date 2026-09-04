from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("visitors", "0001_initial")]
    operations = [
        migrations.AddField(model_name="visitorsession", name="source_channel", field=models.CharField(blank=True, db_index=True, default="", max_length=64)),
        migrations.AddField(model_name="visitorsession", name="campaign_content", field=models.CharField(blank=True, default="", max_length=160)),
        migrations.AddField(model_name="visitorsession", name="referral_or_intro", field=models.CharField(blank=True, default="", max_length=255)),
        migrations.AddField(model_name="visitorsession", name="problem_topic", field=models.CharField(blank=True, default="", max_length=160)),
    ]
