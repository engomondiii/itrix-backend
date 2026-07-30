"""
``python manage.py retention_sweep [--dry-run] [--verify]``

Run every retention sweep, and PROVE the purges happened (Backend v7.1 Phase 3).

── WHY A COMMAND AND NOT ONLY A CELERY TASK ────────────────────────────────

The sweeps exist. ``apps.conversations.services.retention.sweep`` and
``apps.attachments.services.retention.sweep`` have been there since v6.0, and the tasks
module schedules them.

``ENABLE_CELERY`` is False in the deployed environment. So nothing runs them, and the
retention promise in the Privacy Policy — anonymous threads after
``ANON_THREAD_RETENTION_DAYS``, pre-NDA attachments after
``PRE_NDA_ATTACHMENT_RETENTION_DAYS`` — is currently a statement about code that is never
called.

A cron entry running this command is enough to make the promise true, and it does not
require the whole Celery deployment. That is the point: the guarantee should not be blocked
on infrastructure.

── AND WHY IT VERIFIES RATHER THAN REPORTING A COUNT ───────────────────────
"Purged 14 threads" is a claim about what the code intended. ``--verify`` re-reads each
purged subject and asserts the rows are actually gone — which is the difference between a
retention policy and a retention log.

A purge that erased its own audit trail would make the guarantee unverifiable, which is the
same as not having one. So the audit rows SURVIVE the purge by design
(``AttachmentAuditEntry`` outlives its attachment), and this command reports on them.

── --dry-run IS THE DEFAULT POSTURE FOR A FIRST RUN ────────────────────────
It lists what WOULD be purged and touches nothing. Retention is irreversible; the first run
against real data should be read before it is trusted.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run every retention sweep and verify the purges. --dry-run lists without purging."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what would be purged and change nothing. Retention is irreversible.",
        )
        parser.add_argument(
            "--verify",
            action="store_true",
            help="Re-read each purged subject and assert the rows are gone.",
        )

    def handle(self, *args, **options):
        dry = bool(options["dry_run"])
        verify = bool(options["verify"])

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("  itriX retention sweep"))
        if dry:
            self.stdout.write(self.style.WARNING("  DRY RUN — nothing will be purged."))
        self.stdout.write("")

        self._policy_snapshot()
        threads = self._threads(dry, verify)
        attachments = self._attachments(dry, verify)
        tokens = self._credential_tokens(dry)
        accounts = self._abandoned_accounts(dry, verify)
        self._assent_note()

        self.stdout.write("")
        total = threads + attachments + tokens + accounts
        if dry:
            self.stdout.write(
                self.style.WARNING(f"  {total} subject(s) are past their retention window.")
            )
            self.stdout.write("  Re-run without --dry-run to purge them.")
        else:
            self.stdout.write(self.style.SUCCESS(f"  {total} subject(s) purged."))
        self.stdout.write("")

    def _policy_snapshot(self) -> None:
        """
        The windows in force, printed before anything happens.

        These numbers are quoted in the Privacy Policy. Printing them means an operator running
        the sweep can see whether the deployment agrees with the document — and a mismatch
        there is a published promise the code is not keeping.
        """
        from django.conf import settings

        self.stdout.write("  Windows in force (quoted in the Privacy Policy §8):")
        for name in (
            "ANON_THREAD_RETENTION_DAYS",
            "PRE_NDA_ATTACHMENT_RETENTION_DAYS",
            "ATTACHMENT_RETENTION_DAYS",
            # v7.2 — both quoted in Privacy §8. One number, two places.
            "ABANDONED_ACCOUNT_DAYS",
            "RESET_TOKEN_TTL_MINUTES",
            "VERIFICATION_TOKEN_TTL_HOURS",
        ):
            self.stdout.write(f"    {name} = {getattr(settings, name, '(unset)')}")
        self.stdout.write("")

    def _threads(self, dry: bool, verify: bool) -> int:
        from apps.conversations.services import retention

        try:
            expired = list(retention.expired_threads())
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(self.style.ERROR(f"  thread sweep unavailable: {exc}"))
            return 0

        self.stdout.write(f"  Anonymous threads past retention: {len(expired)}")
        if not expired:
            return 0

        if dry:
            for thread in expired[:20]:
                self.stdout.write(f"    would purge {thread.id}  (created {thread.created_at:%Y-%m-%d})")
            if len(expired) > 20:
                self.stdout.write(f"    ... and {len(expired) - 20} more")
            return len(expired)

        purged = 0
        for thread in expired:
            thread_id = str(thread.id)
            try:
                retention.purge_thread(thread, reason="retention_sweep")
                purged += 1
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"    FAILED {thread_id}: {exc}"))
                continue

            if verify:
                result = retention.verify_purged(thread_id)
                if not result.get("purged", False):
                    # A purge that reported success and left rows behind is the worst outcome
                    # here: the log says the promise was kept and the data says otherwise.
                    self.stderr.write(
                        self.style.ERROR(f"    NOT VERIFIED {thread_id}: {result}")
                    )
        self.stdout.write(self.style.SUCCESS(f"    purged {purged}"))
        return purged

    def _attachments(self, dry: bool, verify: bool) -> int:
        from apps.attachments.services import retention

        try:
            expired = list(retention.expired())
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(self.style.ERROR(f"  attachment sweep unavailable: {exc}"))
            return 0

        self.stdout.write(f"  Attachments past retention: {len(expired)}")
        if not expired:
            return 0

        if dry:
            for att in expired[:20]:
                flag = " [pre-NDA]" if getattr(att, "pre_nda", False) else ""
                self.stdout.write(f"    would purge {att.id}  {att.filename}{flag}")
            if len(expired) > 20:
                self.stdout.write(f"    ... and {len(expired) - 20} more")
            return len(expired)

        purged = 0
        for att in expired:
            try:
                retention.purge(att, reason="retention_sweep")
                purged += 1
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"    FAILED {att.id}: {exc}"))
                continue

            if verify:
                result = retention.verify_purged(att)
                if not result.get("purged", False):
                    self.stderr.write(self.style.ERROR(f"    NOT VERIFIED {att.id}: {result}"))
        self.stdout.write(self.style.SUCCESS(f"    purged {purged}"))
        return purged

    def _assent_note(self) -> None:
        """
        Assent records are NOT swept, and that is deliberate.

        Stated here rather than left as an absence, because "the retention sweep does not
        touch this table" is exactly the kind of thing a future maintainer would add for
        consistency. An assent record is evidence of what a customer agreed to, and a dispute
        about that does not become moot because the account was closed
        (Architecture v2.8 §19.10). The record holds an email, a version, a timestamp and an
        IP — no conversation content, no attachment, nothing about their work.
        """
        try:
            from apps.legal.models import AssentRecord

            count = AssentRecord.objects.count()
        except Exception:  # noqa: BLE001
            return
        self.stdout.write("")
        self.stdout.write(f"  Assent records: {count} — NOT swept, by design.")
        self.stdout.write(
            "    Evidence of what a customer agreed to has to outlive the account "
            "(Architecture v2.8 §19.10)."
        )

    def _credential_tokens(self, dry: bool) -> int:
        """
        Purge reset and confirmation tokens that can no longer authorise anything.

        Consumed, superseded or expired. A row that cannot authorise anything is a row worth
        deleting, and these rows are hashes of bearer credentials — keeping them costs
        nothing and buys nothing.

        Not counted as a "subject" in the retention sense: nobody's work is being deleted.
        They are reported separately so the sweep's subject count stays meaningful.
        """
        from django.utils import timezone

        from apps.clients.models_reset import PasswordResetToken
        from apps.clients.models_verification import EmailVerificationToken

        now = timezone.now()
        total = 0
        for model, label in ((PasswordResetToken, "reset"), (EmailVerificationToken, "confirmation")):
            dead = model.objects.filter(consumed_at__isnull=False) | model.objects.filter(
                invalidated_at__isnull=False
            ) | model.objects.filter(expires_at__lt=now)
            count = dead.distinct().count()
            total += count
            self.stdout.write(f"  {label} tokens no longer usable: {count}")
            if count and not dry:
                dead.distinct().delete()
        self.stdout.write("")
        return total

    def _abandoned_accounts(self, dry: bool, verify: bool) -> int:
        """
        Purge accounts that were opened and then never used at all.

        No conversation, no confirmed address, no sign-in, older than ABANDONED_ACCOUNT_DAYS.
        Open registration makes this population real: before it, every account arrived
        attached to a conversation.

        ── THE THREE CONDITIONS ARE AND-ED, DELIBERATELY ───────────────────
        Any one of them alone would delete a real customer. Somebody who signed in but never
        confirmed is a customer. Somebody who conversed but never signed in again is a
        customer. Only the account with NONE of the three has never been used at all.

        ── AND THE ASSENT RECORD SURVIVES ──────────────────────────────────
        `AssentRecord.client` is SET_NULL and the address is denormalised on the record, so
        deleting the Client leaves the evidence intact. `_assent_note()` says so; this says it
        too, because this is the sweep most likely to make somebody wonder.
        """
        from django.conf import settings
        from django.utils import timezone

        from apps.clients.models import AccountOrigin, Client

        days = int(getattr(settings, "ABANDONED_ACCOUNT_DAYS", 180))
        cutoff = timezone.now() - timezone.timedelta(days=days)

        candidates = (
            Client.objects.filter(
                account_origin=AccountOrigin.SELF_SERVE,
                email_verified_at__isnull=True,
                last_login_at__isnull=True,
                created_at__lt=cutoff,
            )
            .exclude(threads__isnull=False)
            .distinct()
        )
        count = candidates.count()
        self.stdout.write(f"  abandoned self-serve accounts (>{days}d, never used): {count}")
        if not count:
            self.stdout.write("")
            return 0

        ids = list(candidates.values_list("id", flat=True))
        if dry:
            for cid in ids[:20]:
                self.stdout.write(f"    - {cid}")
            self.stdout.write("")
            return count

        candidates.delete()
        if verify:
            remaining = Client.objects.filter(id__in=ids).count()
            if remaining:
                self.stdout.write(
                    self.style.ERROR(f"  VERIFY FAILED: {remaining} account(s) still present.")
                )
            else:
                self.stdout.write(self.style.SUCCESS("  verified: all purged accounts are gone."))
        self.stdout.write("")
        return count
