"""Static files storage for the itriX backend."""

from __future__ import annotations

from whitenoise.storage import CompressedManifestStaticFilesStorage


class AdminTolerantManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """Manifest storage that tolerates Jazzmin's one non-file ``{% static %}`` call.

    ``jazzmin/templates/admin/base.html`` renders::

        data-theme-base="{% static 'vendor/bootswatch' %}"

    That names a DIRECTORY, not a file. A staticfiles manifest only ever contains
    files, so a strict lookup raises ``ValueError: Missing staticfiles manifest
    entry for 'vendor/bootswatch'`` — and because every admin page extends that
    template, the entire production admin returns 500. Nothing about the
    deployment is wrong; the reference is unsatisfiable by construction.

    WhiteNoise offers ``WHITENOISE_MANIFEST_STRICT = False`` for exactly this
    situation, but that switch is global: it would also turn a typo in one of
    *our* ``{% static %}`` paths from a loud error into a silent 404. This
    allowlist keeps the manifest strict everywhere else and names the single
    vendor path we cannot fix without forking the template. If Jazzmin ever
    corrects it, this entry becomes dead weight rather than a hazard.
    """

    #: Paths Jazzmin hands to ``{% static %}`` that are directories, not files.
    #: Audited against jazzmin 3.0.5 — every other reference in its templates
    #: resolves to a real file.
    _VENDOR_DIRECTORY_REFS = frozenset({"vendor/bootswatch"})

    def stored_name(self, name: str) -> str:
        if name in self._VENDOR_DIRECTORY_REFS:
            return name
        return super().stored_name(name)
