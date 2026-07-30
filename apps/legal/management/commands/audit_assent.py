"""
``python manage.py audit_assent``

Assert the invariant against PRODUCTION DATA: no Client exists without an assent record
(Architecture v2.8 §19.10, Backend v7.1 §11.6).

── WHY THIS EXISTS ALONGSIDE THE TEST ──────────────────────────────────────
``tests/test_legal/test_no_client_without_assent.py`` asserts the invariant across all three
Client-creating paths, which catches a fourth door added later.

It cannot catch an account created BEFORE the invariant existed, or one created by a data
migration, a shell session, or a fixture load. Those accounts exist without a recorded basis,
and no amount of later work can reconstruct what they read — so the honest thing is to be
able to count them and say so, rather than to discover the number during a dispute.

A non-empty result is a governance defect, not a backlog item. It is also not fixable by
writing records now: a record created today attesting to versions the customer never saw
would be worse than the gap it papered over.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Report active Clients with no assent record, and version drift among those that have one."

    def handle(self, *args, **options):
        from apps.legal.constants import ASSENT_REQUIRED_SLUGS
        from apps.legal.services import assent as assent_svc
        from apps.legal.services import instruments as instruments_svc

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("  itriX assent audit"))
        self.stdout.write("")

        self.stdout.write("  Versions in force:")
        for slug in ASSENT_REQUIRED_SLUGS:
            version = instruments_svc.version_of(slug) or "(unset)"
            self.stdout.write(f"    {slug}: {version}")
        if not instruments_svc.published():
            self.stdout.write(
                self.style.WARNING(
                    "    LEGAL_PUBLISHED is false — the instruments are served as DRAFTS."
                )
            )
        self.stdout.write("")

        missing = list(assent_svc.clients_without_assent()[:200])
        if missing:
            self.stdout.write(
                self.style.ERROR(f"  {len(missing)} active Client(s) with NO assent record:")
            )
            for client in missing[:40]:
                self.stdout.write(f"    {client.id}  {client.email}  created {client.created_at:%Y-%m-%d}")
            if len(missing) > 40:
                self.stdout.write(f"    ... and {len(missing) - 40} more")
            self.stdout.write("")
            self.stdout.write(
                self.style.ERROR(
                    "  This is a GOVERNANCE DEFECT. These accounts exist without a recorded "
                    "basis.\n"
                    "  Do NOT backfill records: one created today attesting to versions the "
                    "customer never saw\n"
                    "  would be worse than the gap. Escalate to Governance with this list."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("  Every active Client has an assent record."))

        self._version_drift(assent_svc, instruments_svc)

    def _version_drift(self, assent_svc, instruments_svc) -> None:
        """
        Clients whose latest assent predates the versions now in force.

        NOT a defect — it is the expected state after a Terms revision, and it is what drives
        the re-prompt at next sign-in (§19.10). It is reported so the size of that re-prompt
        population is known before the revision ships rather than after.
        """
        from apps.clients.models import Client

        stale = [
            client
            for client in Client.objects.filter(is_active=True, assent_records__isnull=False)
            .distinct()[:500]
            if not assent_svc.has_current_assent(client)
        ]
        self.stdout.write("")
        if stale:
            self.stdout.write(
                self.style.WARNING(
                    f"  {len(stale)} Client(s) accepted an EARLIER version and will be "
                    "re-prompted at next sign-in."
                )
            )
            self.stdout.write("    Expected after a revision. Not a defect.")
        else:
            self.stdout.write("  No version drift: every record matches the versions in force.")
        self.stdout.write("")
