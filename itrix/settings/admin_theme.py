"""
Django admin theme — Jazzmin configuration.

Everything visual about the admin lives here plus ``static/admin_itrix/css/itrix-admin.css``.
The palette, type and radii follow **itriX Brand Manual v2.0** (Deep Navy Slate
``#1F2937`` on Soft Signal White ``#F8FAFC``; Inter / Space Grotesk / IBM Plex Mono)
and, where the manual is silent (dark mode, sidebar rail), the Staff console
(``itrix-dashboard/app/globals.css``) is the precedent.

The two dicts below are imported by ``base.py``. Keep them data-only — no Django
imports — so settings stay side-effect free.

Reference: https://django-jazzmin.readthedocs.io/configuration/
"""

from __future__ import annotations

import os

_WEB_URL = os.environ.get("FRONTEND_WEB_URL", "http://localhost:3000")
_DASHBOARD_URL = os.environ.get("FRONTEND_DASHBOARD_URL", "http://localhost:3001")

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar: app order + icons
# ─────────────────────────────────────────────────────────────────────────────
# The order tells the story of the funnel top-to-bottom: what visitors do,
# what qualifies, the CRM, the client plane, customer success, then the
# machinery (knowledge, AI, governance, uploads), then the team and settings.
_APP_ORDER = [
    # people & pipeline
    "leads",
    "clients",
    "customer_success",
    "follow_up",
    "nda",
    "evaluations",
    "pocs",
    # conversation surface
    "conversations",
    "journey",
    "attachments",
    "review",
    "visitors",
    "result_page",
    # intelligence & governance
    "knowledge_core",
    "ai_engine",
    "agents",
    "governance",
    "personas",
    "legal",
    # operations
    "emails",
    "notifications",
    "templates_library",
    "analytics",
    "reporting",
    # team & system
    "authentication",
    "auth",
    "itrix_settings",
    "admin",
    "token_blacklist",
]

# Font Awesome 5 free — https://fontawesome.com/v5/search?m=free
_ICONS = {
    # people & pipeline
    "leads": "fas fa-bullseye",
    "leads.Lead": "fas fa-user-tag",
    "leads.LeadNote": "fas fa-sticky-note",
    "leads.LeadMeeting": "fas fa-calendar-check",
    "leads.LeadActivity": "fas fa-stream",
    "clients": "fas fa-id-badge",
    "clients.Client": "fas fa-user-tie",
    "clients.ClientCredential": "fas fa-key",
    "clients.ClientTeamInvite": "fas fa-user-plus",
    "clients.ConsumedInvite": "fas fa-envelope-open",
    "clients.PasswordResetToken": "fas fa-unlock-alt",
    "clients.EmailVerificationToken": "fas fa-envelope-open-text",
    "customer_success": "fas fa-hands-helping",
    "customer_success.Outcome": "fas fa-flag-checkered",
    "customer_success.SuccessPlan": "fas fa-route",
    "customer_success.SuccessPlanMilestone": "fas fa-map-signs",
    "customer_success.DeploymentHealth": "fas fa-heartbeat",
    "customer_success.SupportRequest": "fas fa-life-ring",
    "customer_success.FeedbackPulse": "fas fa-comment-dots",
    "customer_success.RelationshipTeamMember": "fas fa-user-friends",
    "customer_success.ReleaseNote": "fas fa-scroll",
    "customer_success.ChangeLogEntry": "fas fa-history",
    "customer_success.SuccessReview": "fas fa-clipboard-check",
    "follow_up": "fas fa-tasks",
    "follow_up.FollowUpTask": "fas fa-tasks",
    "nda": "fas fa-file-signature",
    "nda.NDARecord": "fas fa-file-signature",
    "evaluations": "fas fa-vial",
    "evaluations.Evaluation": "fas fa-vial",
    "pocs": "fas fa-flask",
    "pocs.PoC": "fas fa-flask",
    # conversation surface
    "conversations": "fas fa-comments",
    "conversations.Thread": "fas fa-comments",
    "conversations.Conversation": "fas fa-comment-alt",
    "conversations.Message": "fas fa-comment",
    "conversations.Participant": "fas fa-user-circle",
    "conversations.ThreadParticipant": "fas fa-user-circle",
    "conversations.MessageAttachment": "fas fa-paperclip",
    "journey": "fas fa-shoe-prints",
    "journey.JourneyTransition": "fas fa-exchange-alt",
    "journey.Artifact": "fas fa-cube",
    "journey.QuestionSuggestion": "fas fa-question-circle",
    "journey.CoverageSnapshot": "fas fa-chart-pie",
    "attachments": "fas fa-paperclip",
    "attachments.Attachment": "fas fa-file-upload",
    "attachments.AttachmentScan": "fas fa-shield-virus",
    "attachments.AttachmentExtraction": "fas fa-file-alt",
    "attachments.AttachmentExcerpt": "fas fa-quote-right",
    "attachments.AttachmentAuditEntry": "fas fa-clipboard-list",
    "review": "fas fa-search",
    "review.ReviewSession": "fas fa-search",
    "visitors": "fas fa-walking",
    "visitors.VisitorSession": "fas fa-walking",
    "visitors.RoomEntry": "fas fa-door-open",
    "result_page": "fas fa-file-invoice",
    "result_page.ResultPage": "fas fa-file-invoice",
    # intelligence & governance
    "knowledge_core": "fas fa-book",
    "knowledge_core.KnowledgeDocument": "fas fa-book",
    "knowledge_core.KnowledgeChunk": "fas fa-puzzle-piece",
    "knowledge_core.ClaimRecord": "fas fa-check-double",
    "ai_engine": "fas fa-microchip",
    "ai_engine.GenerationLog": "fas fa-microchip",
    "agents": "fas fa-robot",
    "agents.AgentRun": "fas fa-robot",
    "governance": "fas fa-gavel",
    "governance.ClaimCard": "fas fa-certificate",
    "governance.ApprovalRequest": "fas fa-user-check",
    "governance.StreamGuardHit": "fas fa-shield-alt",
    "personas": "fas fa-theater-masks",
    "personas.Persona": "fas fa-theater-masks",
    "personas.PitchRoom": "fas fa-chalkboard",
    "legal": "fas fa-balance-scale",
    "legal.AssentRecord": "fas fa-balance-scale",
    # operations
    "emails": "fas fa-envelope",
    "emails.EmailLog": "fas fa-envelope",
    "notifications": "fas fa-bell",
    "notifications.Notification": "fas fa-bell",
    "templates_library": "fas fa-file-code",
    "templates_library.Template": "fas fa-file-code",
    "analytics": "fas fa-chart-line",
    "analytics.MetricSnapshot": "fas fa-chart-line",
    "reporting": "fas fa-chart-bar",
    "reporting.MonthlyReport": "fas fa-chart-bar",
    # team & system
    "authentication": "fas fa-users",
    "authentication.User": "fas fa-user",
    "auth": "fas fa-users-cog",
    "auth.Group": "fas fa-users",
    "itrix_settings": "fas fa-sliders-h",
    "itrix_settings.SlaThresholds": "fas fa-stopwatch",
    "itrix_settings.NotificationPreference": "fas fa-bell-slash",
    "admin": "fas fa-clipboard-list",
    "admin.LogEntry": "fas fa-clipboard-list",
    "token_blacklist": "fas fa-ban",
    "token_blacklist.OutstandingToken": "fas fa-ticket-alt",
    "token_blacklist.BlacklistedToken": "fas fa-ban",
}

JAZZMIN_SETTINGS = {
    # ── Branding ────────────────────────────────────────────────────────────
    "site_title": "itriX Admin",
    "site_header": "itriX",
    "site_brand": "itriX",
    # The X symbol (Brand Manual §2.2: symbol-only for favicon / app icon / small UI).
    "site_logo": "admin_itrix/brand/itrix-x-inverse.svg",
    "login_logo": "admin_itrix/brand/itrix-logo-primary.svg",
    "login_logo_dark": "admin_itrix/brand/itrix-logo-inverse.svg",
    "site_logo_classes": "itrix-brand-mark",
    "site_icon": "admin_itrix/brand/icon.png",
    "welcome_sign": "Sign in to the itriX admin",
    "copyright": "itriX",
    # Global search box in the top bar — the two hubs.
    "search_model": ["leads.Lead", "clients.Client"],
    "user_avatar": "avatar_url",
    # ── Top menu ────────────────────────────────────────────────────────────
    "topmenu_links": [
        {"name": "Home", "url": "admin:index", "permissions": ["auth.view_user"]},
        {"name": "Staff console", "url": _DASHBOARD_URL, "new_window": True, "icon": "fas fa-columns"},
        {"name": "Public site", "url": _WEB_URL, "new_window": True, "icon": "fas fa-globe"},
    ],
    "usermenu_links": [
        {"name": "Staff console", "url": _DASHBOARD_URL, "new_window": True, "icon": "fas fa-columns"},
        {"model": "authentication.User"},
    ],
    # ── Side menu ───────────────────────────────────────────────────────────
    "show_sidebar": True,
    "navigation_expanded": False,
    "hide_apps": ["token_blacklist"],
    "hide_models": [],
    "order_with_respect_to": _APP_ORDER,
    "custom_links": {
        "knowledge_core": [
            {
                "name": "Ingestion: run from a document's list",
                "url": "admin:knowledge_core_knowledgedocument_changelist",
                "icon": "fas fa-sync-alt",
                "permissions": ["knowledge_core.change_knowledgedocument"],
            }
        ],
    },
    "icons": _ICONS,
    "default_icon_parents": "fas fa-folder",
    "default_icon_children": "fas fa-circle",
    # ── Related modal / UI ──────────────────────────────────────────────────
    "related_modal_active": True,
    "custom_css": "admin_itrix/css/itrix-admin.css",
    "custom_js": None,
    # Fonts are self-hosted (static/admin_itrix/fonts) — no third-party CDN calls
    # from an internal tool, and the build stays hermetic (same rule as the dashboard).
    "use_google_fonts_cdn": False,
    "show_ui_builder": False,
    "show_theme_chooser": True,
    # ── Change form ─────────────────────────────────────────────────────────
    # Tabs: the hub models (Lead, Client, Thread) carry many inline sections and
    # read far better as tabs than as one long scroll.
    "changeform_format": "horizontal_tabs",
    "changeform_format_overrides": {
        # Short forms — one panel is enough.
        "auth.group": "single",
        "itrix_settings.slathresholds": "single",
        "itrix_settings.notificationpreference": "single",
        "templates_library.template": "single",
        "notifications.notification": "single",
        "governance.claimcard": "collapsible",
        # Evidence / telemetry detail views read best as one page.
        "legal.assentrecord": "collapsible",
        "journey.journeytransition": "single",
        "agents.agentrun": "collapsible",
        "ai_engine.generationlog": "collapsible",
        "emails.emaillog": "collapsible",
        "governance.streamguardhit": "collapsible",
        "analytics.metricsnapshot": "single",
        "reporting.monthlyreport": "single",
    },
    "language_chooser": False,
}

JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": True,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": False,
    "accent": "accent-primary",
    # Bootstrap classes are the base; the brand palette is applied on top in
    # itrix-admin.css, so these only need to be sane defaults.
    "navbar": "navbar-white navbar-light",
    "no_navbar_border": False,
    "navbar_fixed": True,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": True,
    "sidebar": "sidebar-light-primary",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": True,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": True,
    "theme": "default",
    # Follow the operator's OS preference; the toggle in the top bar overrides it.
    "default_theme_mode": "auto",
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-outline-secondary",
        "info": "btn-outline-info",
        "warning": "btn-outline-warning",
        "danger": "btn-outline-danger",
        "success": "btn-outline-success",
    },
}
