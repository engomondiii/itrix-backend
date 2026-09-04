from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("conversations", "0004_thread_current_state_thread_questions_asked")]

    operations = [
        migrations.AddField(model_name="thread", name="relationship_state", field=models.CharField(blank=True, db_index=True, default="visitor", max_length=32)),
        migrations.AddField(model_name="thread", name="engagement_stage", field=models.CharField(blank=True, default="exploration", max_length=48)),
        migrations.AddField(model_name="thread", name="selected_stage_label", field=models.CharField(blank=True, default="", max_length=80)),
        migrations.AddField(model_name="thread", name="selected_action", field=models.CharField(blank=True, default="", max_length=80)),
        migrations.AddField(model_name="thread", name="mode_change_target", field=models.CharField(blank=True, default="", max_length=32)),
        migrations.AddField(model_name="thread", name="mode_change_status", field=models.CharField(blank=True, db_index=True, default="none", max_length=24)),
        migrations.AddField(model_name="thread", name="mirror_status", field=models.CharField(blank=True, db_index=True, default="not_required", max_length=24)),
        migrations.AddField(model_name="thread", name="identity_needed_action", field=models.CharField(blank=True, default="", max_length=48)),
        migrations.AddField(model_name="thread", name="cta_declined", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="thread", name="evaluation_type", field=models.CharField(blank=True, default="", max_length=48)),
        migrations.AddField(model_name="thread", name="contract_stage", field=models.CharField(blank=True, default="no_discussion", max_length=32)),
        migrations.AddField(model_name="thread", name="consent_history", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="thread", name="conversation_commitments", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="thread", name="locale", field=models.CharField(blank=True, default="en", max_length=12)),
    ]
