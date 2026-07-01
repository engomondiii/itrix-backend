"""
Client factory for tests.

Builds a ``Client`` (+ its ``ClientCredential``) linked 1:1 to a Lead. Defaults to an
active client with a password set. Use ``ClientFactory(credential__password=None)`` to
simulate a first-time client that still needs to set a password.
"""

from __future__ import annotations

import factory

from apps.clients.models import Client, ClientCredential
from tests.factories.lead_factory import LeadFactory


class ClientFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Client
        skip_postgeneration_save = True

    lead = factory.SubFactory(LeadFactory)
    email = factory.Sequence(lambda n: f"client{n}@example.com")
    full_name = factory.Sequence(lambda n: f"Client {n}")
    organization = "Acme Corp"
    role = "Decision maker"
    nda_signed = False
    is_active = True

    @factory.post_generation
    def credential(self, create, extracted, **kwargs):  # noqa: D401
        if not create:
            return
        cred = ClientCredential(client=self)
        password = kwargs.get("password", "s3cure-pass-123")
        if password:
            cred.set_password(password)
        cred.save()
