from __future__ import annotations

from django.apps import AppConfig


class CockpitConfig(AppConfig):
    """
    Row-level cockpit resources (Backend v7.1 §Phase 1).

    ── WHY THIS IS AN APP AND NOT MORE VIEWS IN apps.analytics ─────────────
    Because the naming rule is the whole point of this phase:

        AGGREGATES under analytics/     distributions, counts, trends
        ROW-LEVEL RESOURCES under cockpit/   individual threads, customers, files, halts

    v6.0 mounted the four ANALYTICS views at ``cockpit/`` as well, which is how the two
    ideas got confused: ``cockpit/threads/`` returned thread *metrics* while the dashboard
    was asking it for a thread *list*, and the resulting 501 guards were read as "the
    backend has not built this yet" when in fact the name was taken.

    Keeping the resources in their own app makes the rule structural. A future developer
    adding a distribution here has to notice they are in the wrong app.

    NO MODELS. This app reads existing ones. It has no migrations, and it should never
    acquire any: a cockpit resource that owned data would be a second source of truth for
    something another app already owns.
    """

    name = "apps.cockpit"
    label = "cockpit"
    verbose_name = "Cockpit (row-level resources)"
