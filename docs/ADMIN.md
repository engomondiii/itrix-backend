# Django admin — itriX

The Django admin at **`/admin/`** is the data-level operations surface for the
team: every model in every `apps.*` app is registered, hub records (Lead,
Client, Thread) are laid out as dossiers with their satellites as inline tabs,
and the whole thing is themed to the itriX brand so it reads as one system
with the Staff console.

It is **not** the Staff console (`itrix-dashboard`, Surface 2). The console is
where the team *works* — approvals, conversations, cockpit. The admin is where
the team *inspects and corrects data*, runs the knowledge-core ingestion, and
manages team members and settings.

## Where things live

| Piece | Path |
|---|---|
| Theme config (branding, sidebar order, icons, tabs) | `itrix/settings/admin_theme.py` → `JAZZMIN_SETTINGS`, `JAZZMIN_UI_TWEAKS` |
| Theme stylesheet (tokens, light + dark, sidebar rail, forms, tables) | `static/admin_itrix/css/itrix-admin.css` |
| Brand marks & favicons | `static/admin_itrix/brand/` (copied from `itrix-web/public/brand` and `itrix-web/src/app`) |
| Self-hosted fonts (Inter, Space Grotesk, IBM Plex Mono — SIL OFL) | `static/admin_itrix/fonts/` |
| Shared admin toolkit (bases, badges, JSON renderer, links) | `apps/core/admin.py` |
| Per-app admins | `apps/<app>/admin.py` |
| Smoke tests (every changelist / add / change page, secrets, collectstatic) | `tests/test_admin/` |

`jazzmin` is listed before `django.contrib.admin` in `INSTALLED_APPS`
(`itrix/settings/base.py`) — that ordering is what makes it override the admin
templates. `STATICFILES_DIRS = [BASE_DIR / "static"]` serves the theme assets.

## Design rules the theme follows

Source of truth: **itriX Brand Manual v2.0** (`02_Brand/` in the spec folder;
see `itrix-docs/_chains/CHAIN_brand.md`). Where the manual is silent, the Staff
console (`itrix-dashboard/app/globals.css`) is the precedent.

- **Type**: Inter for UI, Space Grotesk for headings, IBM Plex Mono for ids /
  hashes / JSON. Fonts are self-hosted — no Google Fonts call from an internal
  tool, and the build stays hermetic (same rule the dashboard follows).
- **Colour**: Deep Navy Slate `#1F2937` ink and primary button on Soft Signal
  White `#F8FAFC`; Mist `#EAF0FF` / Ice `#D6E6FF` for table heads and borders;
  `#8FA8EA` accent used sparingly (dark-mode links and focus). Semantic
  colours only on badges, lines and short text — never as large fills.
- **Dark mode**: the manual defines none; the theme uses the dashboard's
  structure-ramp derivation (`#161C26` ground, `#1F2937` cards, `#3C4A5E`
  borders). Toggle is Jazzmin's own Light / Dark / Auto control (top bar,
  palette icon); default follows the OS.
- **Sidebar**: light rail in light mode (like the console), one 20px gutter
  for the brand tile / avatar / icons, one 56px column for labels, model links
  indented without icons. Brand lockup is the inverse X on an ink tile — the
  console's 28px mark.
- **Logo**: the solid-X mark only (Brand Manual v1.5+). The old outline-X is
  retired; do not reintroduce it.

## Admin postures (apps/core/admin.py)

Every `ModelAdmin` extends one of three bases so the editing posture is
explicit and consistent:

| Base | Meaning | Used for |
|---|---|---|
| `ItrixModelAdmin` | editable; `id` / `created_at` / `updated_at` read-only; sane list defaults | operational records (Lead, Client, ClaimCard, …) |
| `AppendOnlyAdmin` | system-created; staff inspect, superusers may delete, nobody edits | activity / transition / audit rows |
| `ReadOnlyAdmin` | inspect only | telemetry, evidence, generated artefacts (AgentRun, AssentRecord, ResultPage, tokens) |

Inline bases: `ReadOnlyTabularInline`, `ReadOnlyStackedInline`,
`EditableTabularInline`, `EditableStackedInline`.

Rendering helpers: `badge()` (one shared status → colour vocabulary in
`STATUS_TONES`, so *approved* is the same green everywhere), `tier_badge()`,
`claim_level_badge()`, `bool_badge()`, `pretty_json()`, `link_to()`,
`count_link()`, `truncate()`, `bullet_list()`.

Secrets never render: credential hashes and token hashes are excluded from
every form and list (covered by `test_secrets_never_render`).

## Adding a model

1. Register it in `apps/<app>/admin.py` on the right base. `list_display`,
   `list_filter`, `search_fields`, `fieldsets` (tabs), inlines for its
   satellites.
2. Give it an icon in `_ICONS` in `itrix/settings/admin_theme.py`
   (Font Awesome 5 free) and, if it is a new app, add the app to `_APP_ORDER`.
3. Run `pytest tests/test_admin` — it fails loudly if any model in an
   `apps.*` app is unregistered, or any page 500s.

## Running / testing

```bash
python manage.py runserver          # http://127.0.0.1:8000/admin/
python manage.py seed_demo          # demo@itrix.ai / demo12345 (is_staff)
pytest tests/test_admin -q          # ~330 rendered-page checks, ~2 min
```

Production serves the theme through WhiteNoise's manifest storage, so
`collectstatic` must succeed — `test_collectstatic_succeeds` proves the static
tree (fonts referenced by relative URL from the CSS) collects cleanly.
