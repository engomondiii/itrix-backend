"""
Prove the mail configuration works, without registering an account.

    manage.py send_test_email you@example.com

── WHY THIS COMMAND EXISTS ─────────────────────────────────────────────────
The alternative way to test outbound mail is to register a real account, which mints a
Client, a Lead, an assent record and a verification token — real rows, on a real address,
that then have to be cleaned up. Debugging SMTP credentials is not a good reason to create
customer records.

It reports the resolved configuration first and sends second, so a failure tells you which
half is wrong. And it goes through `email_sender.send_email` rather than Django's
`send_mail` directly, because the point is to exercise THE PATH A VISITOR TAKES — the
provider dispatch, the EmailLog row and the confirmation gate included. A test that
bypasses the choke-point can pass while registration still fails.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.emails.models import EmailLog


class Command(BaseCommand):
    help = "Send a test email through the real sender path and report the outcome."

    def add_arguments(self, parser) -> None:
        parser.add_argument("address", help="Where to send the test message.")
        parser.add_argument(
            "--kind",
            default=EmailLog.Kind.EMAIL_VERIFICATION,
            choices=[c[0] for c in EmailLog.Kind.choices],
            help=(
                "The EmailLog kind to send as. Defaults to email_verification, which is "
                "transactional and therefore passes the R66 confirmation gate — the same "
                "kind a real sign-up sends."
            ),
        )

    def handle(self, *args, **options) -> None:
        address = (options["address"] or "").strip()
        if "@" not in address:
            raise CommandError("That does not look like an email address.")

        provider = (getattr(settings, "EMAIL_PROVIDER", "none") or "none").lower()
        delivering = bool(getattr(settings, "ENABLE_EMAIL_DELIVERY", False))

        self.stdout.write("Resolved email configuration")
        self.stdout.write(f"  ENABLE_EMAIL_DELIVERY  {delivering}")
        self.stdout.write(f"  EMAIL_PROVIDER         {provider}")
        self.stdout.write(f"  EMAIL_BACKEND          {getattr(settings, 'EMAIL_BACKEND', '?')}")
        if provider == "smtp":
            self.stdout.write(
                f"  SMTP                   {getattr(settings, 'EMAIL_HOST', '?')}:"
                f"{getattr(settings, 'EMAIL_PORT', '?')} "
                f"TLS={getattr(settings, 'EMAIL_USE_TLS', '?')} "
                f"SSL={getattr(settings, 'EMAIL_USE_SSL', '?')}"
            )
            self.stdout.write(f"  EMAIL_HOST_USER        {getattr(settings, 'EMAIL_HOST_USER', '')}")
            # Presence, never the value. A credential echoed to a terminal ends up in a
            # deploy log, and a deploy log is not where a password should be recoverable.
            self.stdout.write(
                f"  EMAIL_HOST_PASSWORD    {'set' if getattr(settings, 'EMAIL_HOST_PASSWORD', '') else 'NOT SET'}"
            )
        self.stdout.write(f"  From                   {getattr(settings, 'DEFAULT_FROM_EMAIL', '?')}")
        self.stdout.write("")

        if not delivering:
            self.stdout.write(
                self.style.WARNING(
                    "ENABLE_EMAIL_DELIVERY is False, so this will be logged and NOT sent. "
                    "Set it to True to deliver."
                )
            )
        if delivering and provider == "none":
            self.stdout.write(
                self.style.ERROR(
                    "No provider is configured. Set EMAIL_HOST_USER + EMAIL_HOST_PASSWORD "
                    "(SMTP) or RESEND_API_KEY."
                )
            )

        from apps.emails.services.email_sender import send_email

        log = send_email(
            kind=options["kind"],
            to_email=address,
            subject="itriX test message",
            body=(
                "This is a test message from the itriX platform.\n\n"
                "If you are reading it, outbound email works and a sign-up "
                "confirmation link will reach this mailbox.\n\n"
                "- itriX"
            ),
        )

        self.stdout.write(f"EmailLog #{log.id}  status={log.status}")
        if log.error:
            self.stdout.write(self.style.ERROR(f"  error: {log.error}"))

        if log.status == EmailLog.Status.SENT:
            self.stdout.write(self.style.SUCCESS("Sent. Check the mailbox (and spam)."))
        elif log.status == EmailLog.Status.STUBBED:
            self.stdout.write(
                self.style.WARNING("Stubbed — recorded but not delivered. See the flag above.")
            )
        else:
            raise CommandError("Delivery failed. The error above is the provider's own.")
