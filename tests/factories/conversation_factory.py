"""
Conversation factory for tests.

Builds a ``Conversation`` (review context by default) linked to a Lead. Use the message
helpers on the services for turns; this just seeds the thread.
"""

from __future__ import annotations

import factory

from apps.conversations.models import Conversation
from tests.factories.lead_factory import LeadFactory


class ConversationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Conversation
        skip_postgeneration_save = True

    context = "review"
    lead = factory.SubFactory(LeadFactory)
    title = "Test conversation"
