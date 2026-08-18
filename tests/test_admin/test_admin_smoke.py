"""
Admin smoke tests — every registered model's changelist, add form and change
form must render for a superuser.

Why this exists: an admin misconfiguration (a typo in ``list_display``, a
``fieldsets`` entry that is not a field, an inline whose ``fk_name`` is wrong,
a display method that raises on a null FK) is only ever discovered by
*rendering the page*. ``manage.py check`` catches the declarative mistakes;
this catches the runtime ones — and it does so for all 60-odd models at once,
so nobody has to click through the whole admin after a change.

Instances are synthesised generically (required fields filled by type, foreign
keys built recursively) so the test does not depend on per-model factories.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from django.apps import apps
from django.contrib import admin
from django.db import models
from django.test import Client as HttpClient
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db

# ─────────────────────────────────────────────────────────────────────────────
# Generic instance builder
# ─────────────────────────────────────────────────────────────────────────────


def _value_for(field: models.Field, cache: dict) -> object:
    if field.choices:
        return field.choices[0][0]
    if isinstance(field, (models.ForeignKey, models.OneToOneField)):
        return _make(field.remote_field.model, cache)
    if isinstance(field, models.EmailField):
        return "smoke@example.com"
    if isinstance(field, models.URLField):
        return "https://example.com/x"
    if isinstance(field, models.SlugField):
        return f"smoke-{uuid.uuid4().hex[:6]}"
    if isinstance(field, models.UUIDField):
        return uuid.uuid4()
    if isinstance(field, models.GenericIPAddressField):
        return "127.0.0.1"
    if isinstance(field, (models.CharField, models.TextField)):
        return "smoke"
    if isinstance(field, models.BooleanField):
        return False
    if isinstance(field, models.DateTimeField):
        return timezone.now()
    if isinstance(field, models.DateField):
        return dt.date.today()
    if isinstance(field, models.DecimalField):
        return 1
    if isinstance(field, (models.IntegerField, models.FloatField)):
        return 1
    if isinstance(field, models.JSONField):
        return {}
    return None


#: Values a model's own ``save()`` validation insists on (the type-based defaults
#: would otherwise fail model validation).
EXTRA_KWARGS: dict[str, dict] = {
    "journey.Artifact": {"type": "document"},
}


def _make(model: type[models.Model], cache: dict) -> models.Model:
    """Return one persisted instance of ``model`` (memoised per test)."""
    if model in cache:
        return cache[model]
    existing = model._default_manager.first()
    if existing is not None:
        cache[model] = existing
        return existing

    kwargs: dict = {}
    for field in model._meta.concrete_fields:
        if field.primary_key or not field.editable and not isinstance(field, (models.ForeignKey, models.OneToOneField)):
            continue
        if field.has_default() or field.null or (field.blank and not isinstance(field, (models.ForeignKey, models.OneToOneField))):
            # Optional / defaulted: leave it. (Nullable FKs stay null on purpose —
            # that exercises every "obj.fk is None" branch in the display methods.)
            continue
        value = _value_for(field, cache)
        if value is not None:
            kwargs[field.name] = value

    # Model-specific required extras that the type-based defaults cannot infer.
    label = model._meta.label
    kwargs.update(EXTRA_KWARGS.get(label, {}))
    if label == "authentication.User":
        instance = model.objects.create_user(email=f"smoke-{uuid.uuid4().hex[:6]}@example.com", password="x", name="Smoke")
    else:
        instance = model._default_manager.create(**kwargs)
    cache[model] = instance
    return instance


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def superuser_client(db):
    from apps.authentication.models import User

    user = User.objects.create_superuser(email="smoke-admin@example.com", password="x", name="Smoke Admin")
    client = HttpClient()
    client.force_login(user)
    return client


REGISTERED = sorted(admin.site._registry.keys(), key=lambda m: m._meta.label)
LOCAL = [m for m in REGISTERED if m._meta.app_config.name.startswith("apps.")]
IDS = [m._meta.label for m in REGISTERED]


def _url(model, view, *args):
    return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_{view}", args=args)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_every_local_model_is_registered():
    """Every concrete model in an ``apps.*`` app has an admin. New models must opt in."""
    missing = [
        m._meta.label
        for ac in apps.get_app_configs()
        if ac.name.startswith("apps.")
        for m in ac.get_models()
        if m not in admin.site._registry
    ]
    assert not missing, f"models without an admin: {missing}"


def test_admin_index_renders(superuser_client):
    resp = superuser_client.get(reverse("admin:index"))
    assert resp.status_code == 200
    assert b"itriX" in resp.content


def test_login_page_renders_branding():
    resp = HttpClient().get(reverse("admin:login"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "admin_itrix/brand/itrix-logo-primary.svg" in body
    assert "admin_itrix/css/itrix-admin.css" in body
    assert "fonts.googleapis.com" not in body, "fonts must be self-hosted"


@pytest.mark.parametrize("model", REGISTERED, ids=IDS)
def test_changelist_renders(superuser_client, model):
    resp = superuser_client.get(_url(model, "changelist"))
    assert resp.status_code == 200, f"{model._meta.label} changelist -> {resp.status_code}"


@pytest.mark.parametrize("model", REGISTERED, ids=IDS)
def test_changelist_search_renders(superuser_client, model):
    """A search hits every ``search_fields`` join — the cheapest way to catch a bad lookup."""
    model_admin = admin.site._registry[model]
    if not model_admin.search_fields:
        pytest.skip("no search_fields")
    resp = superuser_client.get(_url(model, "changelist"), {"q": "smoke"})
    assert resp.status_code == 200, f"{model._meta.label} search -> {resp.status_code}"


@pytest.mark.parametrize("model", REGISTERED, ids=IDS)
def test_add_form_renders_or_is_forbidden(superuser_client, model):
    model_admin = admin.site._registry[model]
    resp = superuser_client.get(_url(model, "add"))
    if model_admin.has_add_permission(resp.wsgi_request):
        assert resp.status_code == 200, f"{model._meta.label} add -> {resp.status_code}"
    else:
        assert resp.status_code == 403, f"{model._meta.label} add should be forbidden, got {resp.status_code}"


@pytest.mark.parametrize("model", LOCAL, ids=[m._meta.label for m in LOCAL])
def test_change_form_renders(superuser_client, model):
    """Render the change/detail page for a synthesised instance of every itriX model."""
    cache: dict = {}
    obj = _make(model, cache)
    resp = superuser_client.get(_url(model, "change", obj.pk))
    assert resp.status_code == 200, f"{model._meta.label} change -> {resp.status_code}"


@pytest.mark.parametrize("model", LOCAL, ids=[m._meta.label for m in LOCAL])
def test_changelist_with_rows_renders(superuser_client, model):
    """The changelist again, but with at least one row so every column callable runs."""
    cache: dict = {}
    _make(model, cache)
    resp = superuser_client.get(_url(model, "changelist"))
    assert resp.status_code == 200, f"{model._meta.label} changelist(rows) -> {resp.status_code}"


def test_read_only_admins_reject_writes(superuser_client):
    """The evidence / telemetry postures must hold even for a superuser."""
    from apps.core.admin import ReadOnlyAdmin
    from apps.legal.models import AssentRecord

    for model, model_admin in admin.site._registry.items():
        if isinstance(model_admin, ReadOnlyAdmin):
            resp = superuser_client.get(_url(model, "add"))
            assert resp.status_code == 403, f"{model._meta.label} is ReadOnlyAdmin but add returned {resp.status_code}"
    # AssentRecord is the strictest: nobody deletes.
    ar_admin = admin.site._registry[AssentRecord]
    req = superuser_client.get(reverse("admin:index")).wsgi_request
    assert not ar_admin.has_delete_permission(req)
    assert not ar_admin.has_change_permission(req)


def test_secrets_never_render(superuser_client):
    """Credential and token hashes must not appear on any admin page."""
    from apps.clients.models import Client, ClientCredential, PasswordResetToken

    cache: dict = {}
    client = _make(Client, cache)
    cred, _ = ClientCredential.objects.get_or_create(client=client)
    cred.set_password("Sup3r-secret-pw!")
    cred.save()
    tok = PasswordResetToken.objects.create(client=client, token_hash="deadbeef" * 8, expires_at=timezone.now())

    for url in (
        _url(ClientCredential, "change", cred.pk),
        _url(ClientCredential, "changelist"),
        _url(PasswordResetToken, "change", tok.pk),
        _url(Client, "change", client.pk),
    ):
        body = superuser_client.get(url).content.decode()
        assert cred.password_hash not in body, f"password hash leaked on {url}"
        assert "deadbeef" * 8 not in body, f"token hash leaked on {url}"


def test_jazzmin_settings_reference_real_things(settings):
    """Every icon key / order entry / changeform override names an installed app or model."""
    from django.apps import apps as django_apps

    labels = {ac.label for ac in django_apps.get_app_configs()}
    models_lc = {m._meta.label_lower for m in django_apps.get_models()}
    js = settings.JAZZMIN_SETTINGS
    for key in js["icons"]:
        if "." in key:
            assert key.lower() in models_lc, f"icon for unknown model {key}"
        else:
            assert key in labels, f"icon for unknown app {key}"
    for app_label in js["order_with_respect_to"]:
        assert app_label in labels, f"order entry for unknown app {app_label}"
    for key in js["changeform_format_overrides"]:
        assert key in models_lc, f"changeform override for unknown model {key}"
    for app_label in js["hide_apps"]:
        assert app_label in labels
    for key in js["search_model"]:
        assert key.lower() in models_lc


def test_collectstatic_succeeds(tmp_path, settings):
    """The production image runs collectstatic under the manifest storage; the
    theme's CSS references fonts by relative URL, and a broken reference fails
    post-processing. Prove the whole static tree collects cleanly."""
    from django.core.management import call_command

    settings.STATIC_ROOT = tmp_path / "static"
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    call_command("collectstatic", interactive=False, verbosity=0)
    assert (tmp_path / "static" / "admin_itrix" / "css" / "itrix-admin.css").exists()
    assert (tmp_path / "static" / "admin_itrix" / "brand" / "itrix-x.svg").exists()
    assert (tmp_path / "static" / "staticfiles.json").exists()
