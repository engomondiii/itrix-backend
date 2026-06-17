"""
Renderers.

``ITrixJSONRenderer`` is a thin subclass of DRF's ``JSONRenderer``. Successful
responses are passed through unchanged (the frontends consume plain JSON DTOs and,
for lists, the ``{results,count,page,pageSize}`` pagination envelope). Error bodies
are already normalised by ``apps.core.exceptions.itrix_exception_handler`` to the
``{error:{detail,...}}`` envelope, so the renderer must not re-wrap them.

Keeping success payloads un-enveloped is deliberate: the dashboard's typed fetchers
(``lib/api/*``) and the web proxies read fields directly off the JSON, and the mock
layer returns the same bare shapes.
"""

from __future__ import annotations

from rest_framework.renderers import JSONRenderer


class ITrixJSONRenderer(JSONRenderer):
    """Standard JSON output; charset pinned to utf-8."""

    charset = "utf-8"
    media_type = "application/json"
