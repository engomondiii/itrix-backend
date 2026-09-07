# Promote conversation provenance from meta["thread_id"] to a real column.
#
# `advance()` has always recorded which conversation drove a transition — but in the
# free-form `meta` blob, where it cannot be joined, indexed or followed. A Lead has many
# Threads, each with its own relationship_state and mirror_status, so "which conversation
# earned this stage?" is a question the data could already answer and the schema could not.
#
# The backfill reads the ids that are already there. It is deliberately conservative:
# only well-formed UUIDs that still resolve to a live Thread are linked. A malformed value,
# or one whose thread the visitor has since deleted, leaves the column NULL and the
# original `meta` untouched — the audit row keeps the id as text either way.
import django.db.models.deletion
from django.db import migrations, models


def link_threads_from_meta(apps, schema_editor):
    import uuid

    JourneyTransition = apps.get_model("journey", "JourneyTransition")
    Thread = apps.get_model("conversations", "Thread")

    rows = JourneyTransition.objects.filter(thread__isnull=True).exclude(meta={})
    wanted: dict[str, list] = {}
    for row in rows.iterator():
        raw = (row.meta or {}).get("thread_id")
        if not raw:
            continue
        try:
            key = str(uuid.UUID(str(raw)))
        except (ValueError, AttributeError, TypeError):
            continue  # not a uuid — leave NULL rather than guess
        wanted.setdefault(key, []).append(row)

    if not wanted:
        return

    live = set(
        str(t)
        for t in Thread.objects.filter(id__in=list(wanted)).values_list("id", flat=True)
    )
    updated = []
    for key, transitions in wanted.items():
        if key not in live:
            continue  # thread deleted: SET_NULL is the honest state
        for row in transitions:
            row.thread_id = key
            updated.append(row)

    if updated:
        JourneyTransition.objects.bulk_update(updated, ["thread_id"], batch_size=500)


def unlink(apps, schema_editor):
    """Reverse is a no-op on data: dropping the column removes the link anyway."""


class Migration(migrations.Migration):

    dependencies = [
        ("conversations", "0006_thread_creation_idempotency"),
        ("journey", "0005_drop_engaged_alias"),
    ]

    operations = [
        migrations.AddField(
            model_name="journeytransition",
            name="thread",
            field=models.ForeignKey(
                blank=True,
                help_text="The conversation that drove this transition, when one did.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="journey_transitions",
                to="conversations.thread",
            ),
        ),
        migrations.RunPython(link_threads_from_meta, unlink),
    ]
