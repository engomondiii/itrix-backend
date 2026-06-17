"""Review + visitor factories for tests."""

from __future__ import annotations

import factory

from apps.review.models import ReviewSession
from apps.visitors.models import VisitorSession


class VisitorSessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = VisitorSession

    client_id = factory.Sequence(lambda n: f"client-{n}")
    visitor_type = "problem_owner"


class ReviewSessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ReviewSession

    client_id = factory.Sequence(lambda n: f"client-{n}")
    visitor_type = "problem_owner"
    status = ReviewSession.Status.STARTED


# A representative high-scoring answer set (hardware/chip, urgent, decision-maker,
# budget allocated, exclusive interest) → should land Tier 1.
HIGH_SCORE_ANSWERS = {
    "Q1": "hardware",
    "Q2": ["hardware_utilization", "memory_data_movement", "energy"],
    "Q3": "conservation",
    "Q4": "now",
    "Q5": "critical",
    "Q6": "hardware_chip",
    "Q7": "decision_maker",
    "Q8": "allocated",
    "Q9": "exclusive",
}

# A low-scoring exploratory set → should land Tier 4.
LOW_SCORE_ANSWERS = {
    "Q1": "other",
    "Q2": [],
    "Q3": "unsure",
    "Q4": "exploring",
    "Q5": "minor",
    "Q6": "individual",
    "Q7": "curious",
    "Q8": "none_yet",
    "Q9": "unsure",
}
