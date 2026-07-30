from __future__ import annotations

from django.apps import AppConfig


class LegalConfig(AppConfig):
    """
    The four legal instruments and the assent record (Architecture v2.8 §19.10).

    ── WHY THIS IS ITS OWN APP ─────────────────────────────────────────────
    An assent record is EVIDENCE. It has to answer, months later, "what exactly did this
    customer agree to?" — and the only answer that survives a Terms revision is one that
    stored the VERSION they were shown.

    Putting that in `apps.clients` would tie its lifetime to the Client's, and the record
    has to outlive a deleted account: a dispute about what someone agreed to does not
    become moot because they closed their workspace. So the FK is nullable-on-delete and
    the app is separate, which makes the independence structural rather than a comment.
    """

    name = "apps.legal"
    label = "legal"
    verbose_name = "Legal instruments and assent"
