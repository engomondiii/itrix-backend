"""AppConfig for the emails app."""

from __future__ import annotations

from django.apps import AppConfig


class EmailsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.emails"
    label = "emails"
    verbose_name = "Emails"

    def ready(self) -> None:
        """
        Say out loud, once at boot, whether this deployment can actually send mail.

        ── WHY THIS EXISTS ─────────────────────────────────────────────────
        The two ways this configuration fails are both silent. Credentials present but
        ENABLE_EMAIL_DELIVERY off logs every send as `stubbed` — which is correct
        behaviour and indistinguishable from a broken mailbox. Delivery on but no
        provider configured logs every send as `failed` — in a table nobody reads until
        a customer says the link never arrived.
        
        A line in the boot log turns both into something you can see before a visitor
        does. It is a log statement rather than a Django system check on purpose: a
        check that WARNS makes `manage.py check` non-clean, and a deployment that
        intends not to send mail is not misconfigured.
        """
        import logging

        from django.conf import settings

        logger = logging.getLogger("itrix")
        provider = (getattr(settings, "EMAIL_PROVIDER", "none") or "none").lower()
        delivering = bool(getattr(settings, "ENABLE_EMAIL_DELIVERY", False))

        if not delivering:
            logger.info(
                "[email-config] delivery OFF (ENABLE_EMAIL_DELIVERY=False). "
                "Provider would be '%s'. Every send is logged as stubbed.",
                provider,
            )
            return

        if provider == "none":
            logger.warning(
                "[email-config] ENABLE_EMAIL_DELIVERY is ON but NO PROVIDER is "
                "configured. Set EMAIL_HOST_USER + EMAIL_HOST_PASSWORD for SMTP, or "
                "RESEND_API_KEY. Until then every send is recorded as failed."
            )
            return

        if provider == "smtp":
            logger.info(
                "[email-config] delivery ON via SMTP %s:%s as %s, from '%s'.",
                getattr(settings, "EMAIL_HOST", "?"),
                getattr(settings, "EMAIL_PORT", "?"),
                getattr(settings, "EMAIL_HOST_USER", "?"),
                getattr(settings, "DEFAULT_FROM_EMAIL", "?"),
            )
            ignored = getattr(settings, "EMAIL_FROM_IGNORED", "")
            if ignored:
                logger.warning(
                    "[email-config] EMAIL_FROM=%s is set but IGNORED: SMTP sends as the "
                    "authenticated mailbox %s, because Gmail refuses a From address the "
                    "credential does not own. Set EMAIL_FROM to %s (or unset it) to make "
                    "the environment agree with what is actually sent.",
                    ignored,
                    getattr(settings, "EMAIL_HOST_USER", "?"),
                    getattr(settings, "EMAIL_HOST_USER", "?"),
                )
        else:
            logger.info(
                "[email-config] delivery ON via Resend, from '%s'.",
                getattr(settings, "DEFAULT_FROM_EMAIL", "?"),
            )
