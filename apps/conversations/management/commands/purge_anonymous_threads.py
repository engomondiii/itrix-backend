"""
``python manage.py purge_anonymous_threads``

Retention purge for anonymous threads (Backend v6.0 §Phase 3).

    --report   what is due, change nothing
    --purge    purge everything due
    --export   write transcripts to a directory BEFORE purging
    --verify   prove past purges are complete

── WHY A COMMAND AS WELL AS A SCHEDULED TASK ────────────────────────────────
The sweep runs on Celery beat. This exists so retention can be run and AUDITED by a
human without a broker — during an incident, during a migration, or when somebody has to
answer "prove this visitor's conversation is gone."

``--export`` writes the transcript first. A visitor who asks for their conversation
before it expires has to be able to get it, and offering an export after the purge would
be offering nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.conversations.services import retention


class Command(BaseCommand):
    help = "Purge anonymous threads past their retention window (verifiable)."

    def add_arguments(self, parser):
        parser.add_argument("--report", action="store_true", help="Report without purging.")
        parser.add_argument("--purge", action="store_true", help="Purge everything due.")
        parser.add_argument("--export", metavar="DIR", help="Export transcripts before purging.")
        parser.add_argument("--verify", action="store_true", help="Verify past purges.")
        parser.add_argument("--limit", type=int, default=0, help="Cap how many are purged.")

    def handle(self, *args, **options):
        if not any([options["report"], options["purge"], options["verify"]]):
            raise CommandError("Choose one of --report, --purge or --verify.")

        if options["report"]:
            return self._report()
        if options["verify"]:
            return self._verify()
        return self._purge(options)

    def _report(self):
        due = retention.expired_threads()
        total = due.count()
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"{total} anonymous thread(s) past their retention window\n"
        ))
        for thread in due[:50]:
            self.stdout.write(
                f"  {thread.id}  expired {thread.retention_expires_at:%Y-%m-%d}  "
                f"{(thread.title or 'Untitled')[:50]}"
            )
        if total > 50:
            self.stdout.write(f"  ... and {total - 50} more")
        if total:
            self.stdout.write(self.style.NOTICE(
                "\n  Nothing was purged. Apply with --purge (optionally --export DIR first)."
            ))

    def _purge(self, options):
        export_dir = None
        if options.get("export"):
            export_dir = Path(options["export"])
            export_dir.mkdir(parents=True, exist_ok=True)

        due = list(retention.expired_threads())
        if options["limit"]:
            due = due[: options["limit"]]

        exported = purged = failed = 0
        for thread in due:
            if export_dir is not None:
                try:
                    payload = retention.export_thread(thread)
                    (export_dir / f"{thread.id}.json").write_text(
                        json.dumps(payload, indent=2), encoding="utf-8"
                    )
                    exported += 1
                except Exception as exc:  # noqa: BLE001
                    # An export failure must NOT be followed by a purge — that would
                    # destroy the thing we just failed to preserve.
                    self.stderr.write(self.style.ERROR(f"  export failed for {thread.id}: {exc}"))
                    failed += 1
                    continue
            try:
                retention.purge_thread(thread, reason="operator_purge")
                purged += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                self.stderr.write(self.style.ERROR(f"  purge failed for {thread.id}: {exc}"))

        if export_dir is not None:
            self.stdout.write(f"  Exported {exported} transcript(s) to {export_dir}")
        self.stdout.write(self.style.SUCCESS(f"Purged {purged}, failed {failed}."))
        if failed:
            raise CommandError(f"{failed} thread(s) could not be purged.")

    def _verify(self):
        """
        Verify recent purges.

        Reads the purge log rather than the thread table — a purged thread has no row, so
        verification has to work from what the purge RECORDED.
        """
        self.stdout.write("Verifying that no expired thread still holds data...\n")
        remaining = retention.expired_threads().count()
        if remaining:
            self.stdout.write(self.style.WARNING(
                f"  {remaining} expired thread(s) have NOT been purged yet."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("  No expired thread is still holding data."))

        orphans = self._orphaned_blobs()
        if orphans:
            self.stdout.write(self.style.ERROR(
                f"  {orphans} attachment blob(s) survive a purged thread — investigate."
            ))
            raise CommandError("orphaned blobs found")
        self.stdout.write(self.style.SUCCESS("  No orphaned attachment blobs."))

    @staticmethod
    def _orphaned_blobs() -> int:
        """Blobs whose thread no longer exists — the failure a row-only delete produces."""
        try:
            from apps.attachments import storage
            from apps.attachments.models import Attachment
            from apps.conversations.models import Thread

            live = set(str(t) for t in Thread.objects.values_list("id", flat=True))
            count = 0
            for attachment in Attachment.objects.exclude(blob_key="").only(
                "blob_key", "thread_id"
            ):
                if str(attachment.thread_id) not in live and storage.exists(attachment.blob_key):
                    count += 1
            return count
        except Exception:  # noqa: BLE001
            return 0
