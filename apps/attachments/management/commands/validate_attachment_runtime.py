from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.attachments.runtime_validation import validate_attachment_runtime


class Command(BaseCommand):
    help = "Validate production attachment storage and malware-scanner runtime safely."

    def handle(self, *args, **options):
        try:
            report = validate_attachment_runtime()
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Attachment runtime validation failed: {exc}") from exc

        if not report.get("enabled"):
            self.stdout.write(self.style.WARNING("Attachments are disabled; runtime probe skipped."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Attachment runtime validation passed: "
                f"storage={report.get('storage_backend')} "
                "write/read integrity=ok malware-scan=clean probe-delete=ok"
            )
        )
