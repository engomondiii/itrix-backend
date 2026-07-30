"""
The assent record (Architecture v2.8 §19.10).

── THE RECORD STORES VERSIONS, NOT A BOOLEAN ───────────────────────────────

That is the entire design, and the reason is one question: months from now, what exactly
did this customer agree to?

A boolean cannot answer it. The moment the Terms change, `accepted_terms = True` means
"agreed to whichever version was live at some point" — which is not a fact anyone can act
on in a dispute. So each accepted instrument is a row naming its SLUG and its VERSION, and
the answer is always quotable.

── AND THE RECORD OUTLIVES THE ACCOUNT ─────────────────────────────────────
`client` is SET_NULL on delete. A dispute about what someone agreed to does not become moot
because they closed their workspace, so the evidence has to survive the subject. The
denormalised `client_email_at_assent` is there for the same reason: after the Client row is
gone, an assent record with a null FK and no other identifier is evidence of nothing.

That is a deliberate exception to the platform's general "delete means delete" posture, and
it is narrow: the record holds an email, a version, a timestamp and an IP. It holds no
conversation content, no attachment, and nothing the customer told us about their work.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel
from apps.legal.constants import INSTRUMENT_SLUGS


class AssentRecord(BaseModel):
    """
    One act of assent: a person, a moment, and the instrument versions they were shown.

    ONE ROW PER ACT, not per instrument. The instruments accepted together are stored on
    `instruments` as a list of {slug, version, effective}, because they were accepted in a
    single action and splitting them into rows would invite a future query that finds
    someone accepted the Terms and not the Privacy Policy — a state the checkbox makes
    impossible and the schema should not suggest.
    """

    class Path(models.TextChoices):
        """Which door created the Client. All three record assent (§19.10)."""

        INVITE_CLAIM = "invite_claim", "Invite claim (emailed capability link)"
        INVITE_CODE = "invite_code", "Invite redemption (code entered)"
        OPEN_REGISTRATION = "open_registration", "Open registration"
        REPROMPT = "reprompt", "Re-prompted after a version change"

    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assent_records",
    )
    # Denormalised ON PURPOSE. After the Client is deleted, a null FK and nothing else is
    # evidence of nothing.
    client_email_at_assent = models.EmailField(blank=True, default="")

    # [{"slug": "terms", "version": "1.1", "effective": "2026-08-01"}, ...]
    # THE VERSIONS THE VISITOR WAS SHOWN — not the versions current at query time.
    instruments = models.JSONField(default=list)

    path = models.CharField(
        max_length=24, choices=Path.choices, default=Path.INVITE_CLAIM, db_index=True
    )
    # The client's own timestamp, alongside `created_at` which is the server's. Both are
    # kept because a clock skew between them is itself worth being able to see.
    accepted_at_client = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Assent record"
        verbose_name_plural = "Assent records"
        indexes = [
            models.Index(fields=["client", "-created_at"]),
            models.Index(fields=["client_email_at_assent"]),
        ]

    def __str__(self) -> str:
        slugs = ", ".join(i.get("slug", "?") for i in (self.instruments or []))
        return f"AssentRecord({self.client_email_at_assent or self.client_id}: {slugs})"

    def version_of(self, slug: str) -> str | None:
        """The version of ``slug`` this record attests to, or None."""
        for entry in self.instruments or []:
            if entry.get("slug") == slug:
                return entry.get("version")
        return None

    @property
    def accepted_slugs(self) -> list[str]:
        return [
            entry.get("slug")
            for entry in (self.instruments or [])
            if entry.get("slug") in INSTRUMENT_SLUGS
        ]
