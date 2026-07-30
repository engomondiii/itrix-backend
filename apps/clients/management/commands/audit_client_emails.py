"""
manage.py audit_client_emails  (Backend v7.2 §15.9)

── IT REPORTS. IT NEVER MERGES ─────────────────────────────────────────────
Merging two accounts that share an address means deciding whose conversations, whose
attachments and whose assent record survive. That is not a decision a management command
should make on somebody's behalf, and a `--fix` here would make it silently.

── WHY IT EXISTS AT ALL ────────────────────────────────────────────────────
`Client.email` had no uniqueness constraint, and `authenticate_client()` resolves a login
with `filter(email__iexact=...).first()`. With invite-only accounts that was a latent
defect; the moment anyone can register it becomes exploitable, so v7.2 adds a database
constraint.

A migration that fails in production at 3am because two rows share an address is worse
than a command somebody had to run first. RELEASE ORDER:

    1  manage.py audit_client_emails      must come back clean
    2  migrate clients                    adds the constraint
    3  ENABLE_OPEN_SIGNUP=True            only now
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand

from apps.clients.models import Client


class Command(BaseCommand):
    help = "Report active Clients that share an email address (case-insensitively)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help=(
                "Also report duplicates among inactive accounts. The constraint only binds "
                "active ones, so these are informational."
            ),
        )

    def handle(self, *args, **options):
        include_inactive = bool(options.get("include_inactive"))
        qs = Client.objects.all() if include_inactive else Client.objects.filter(is_active=True)

        buckets: dict[str, list[Client]] = defaultdict(list)
        blank = 0
        for client in qs.only("id", "email", "is_active", "created_at"):
            address = (client.email or "").strip().lower()
            if not address:
                blank += 1
                continue
            buckets[address].append(client)

        duplicates = {a: cs for a, cs in buckets.items() if len(cs) > 1}

        self.stdout.write(f"Checked {qs.count()} client(s).")
        if blank:
            # The constraint excludes empty addresses on purpose: the column permits '' and
            # several legacy rows may hold it, so a plain unique index would refuse the
            # second one.
            self.stdout.write(f"{blank} client(s) have no email address (excluded from the constraint).")

        if not duplicates:
            self.stdout.write(self.style.SUCCESS("No duplicate addresses. Safe to apply the constraint."))
            return

        self.stdout.write(self.style.ERROR(f"{len(duplicates)} duplicated address(es):"))
        for address, clients in sorted(duplicates.items()):
            self.stdout.write(f"  {address}")
            for c in sorted(clients, key=lambda x: x.created_at):
                flag = "" if c.is_active else "  (inactive)"
                self.stdout.write(f"    - {c.id}  created {c.created_at:%Y-%m-%d}{flag}")
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                "Resolve these BEFORE applying the uniqueness migration. Deciding which "
                "account survives is a human decision: it determines whose conversations, "
                "attachments and assent record are kept."
            )
        )
        raise SystemExit(1)
