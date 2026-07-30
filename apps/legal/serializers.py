"""Legal serializers — the two shapes the assent endpoint accepts and returns."""

from __future__ import annotations

from rest_framework import serializers

from apps.legal.constants import INSTRUMENT_SLUGS


class AssentInstrumentSerializer(serializers.Serializer):
    """
    One instrument the client claims to have shown.

    ── WHY THE CLIENT'S VERSION IS ACCEPTED AND THEN IGNORED ───────────────
    The frontend sends the versions it RENDERED. That is the honest thing for it to send,
    and it is exactly what we want to know — but it is not what gets stored.

    The record stores the SERVER's current versions, because the client is untrusted and a
    request could claim any version at all. What the client's copy is used for is the
    MISMATCH CHECK: if it disagrees with the server, the visitor was shown something other
    than what is in force, and that is worth a loud log rather than a silent write.
    """

    slug = serializers.ChoiceField(choices=INSTRUMENT_SLUGS)
    version = serializers.CharField(max_length=32, required=False, allow_blank=True)
    effective = serializers.CharField(max_length=32, required=False, allow_blank=True)


class AssentRequestSerializer(serializers.Serializer):
    """Body for ``POST portal/legal/assent/``."""

    instruments = AssentInstrumentSerializer(many=True, required=False)
    acceptedAt = serializers.DateTimeField(required=False, allow_null=True)
    # Present when assent is taken during an invite redemption from a cold start.
    token = serializers.CharField(required=False, allow_blank=True, max_length=2048)


class AssentReceiptSerializer(serializers.Serializer):
    """
    What comes back.

    Echoes the versions ACTUALLY RECORDED, not the ones sent. A client that sent stale
    versions can therefore see, in the response, that what was stored differs from what it
    displayed — which is the fastest way for that bug to be noticed.
    """

    recorded = serializers.BooleanField()
    acceptedAt = serializers.DateTimeField(allow_null=True, required=False)
    instruments = AssentInstrumentSerializer(many=True)
