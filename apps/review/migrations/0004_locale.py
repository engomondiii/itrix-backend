from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("review", "0003_review_access_binding")]

    operations = [
        migrations.AddField(
            model_name="reviewsession",
            name="locale",
            field=models.CharField(blank=True, default="en", max_length=12),
        ),
    ]
