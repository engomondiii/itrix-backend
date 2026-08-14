"""Inspect the newest attachment's scan/extraction/context pipeline."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.attachments.models import Attachment
from apps.attachments.services import excerpts


class Command(BaseCommand):
    help = "Verify the latest attachment was scanned, extracted and is available to thread context."

    def add_arguments(self, parser):
        parser.add_argument(
            "--question",
            default="Summarise the important information in this document.",
        )

    def handle(self, *args, **opts):
        attachment = Attachment.objects.select_related("thread").order_by("-created_at").first()
        if attachment is None:
            raise CommandError("No attachments exist.")

        self.stdout.write(f"Attachment: {attachment.filename}")
        self.stdout.write(f"Status: {attachment.status}")
        self.stdout.write(f"Thread: {attachment.thread_id}")
        self.stdout.write(f"Detected MIME: {attachment.detected_mime}")
        scan = attachment.scans.first()
        self.stdout.write(f"Scan: {getattr(scan, 'verdict', 'NO SCAN')}")

        try:
            extraction = attachment.extraction
        except Exception:
            extraction = None
        if extraction is None:
            raise CommandError("Attachment has no extraction row.")

        self.stdout.write(f"Handler: {extraction.handler}")
        self.stdout.write(f"Characters: {extraction.char_count}")
        self.stdout.write(f"Metadata only: {extraction.metadata_only}")
        self.stdout.write(f"Truncated: {extraction.truncated}")
        self.stdout.write(f"Extraction error: {extraction.error or '(none)'}")

        if attachment.thread_id:
            selected = excerpts.for_context(attachment.thread, opts["question"])
            self.stdout.write(f"Context items selected: {len(selected)}")
            for item in selected:
                text = " ".join((item.get("text") or "").split())
                self.stdout.write(f"  {item.get('filename')}: {text[:500]}")
            if not selected and extraction.has_text:
                raise CommandError("Readable extraction exists but no context excerpt was selected.")
