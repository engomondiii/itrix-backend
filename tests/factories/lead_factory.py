"""
Lead factory for tests.

Builds ``Lead`` rows directly (bypassing the review flow) for tests that just need a lead
to act on. Defaults to a Tier 2, ALPHA Compute, non-exclusive lead.
"""

from __future__ import annotations

import factory

from apps.leads.models import Lead


class LeadFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Lead

    visitor_name = factory.Sequence(lambda n: f"Visitor {n}")
    company = factory.Sequence(lambda n: f"Company {n}")
    email = factory.Sequence(lambda n: f"lead{n}@example.com")
    industry = "Enterprise R&D / engineering"
    role = "Influencer"
    product_route = "alpha_compute"
    commercial_path = "non_exclusive"
    special_rights = "None"
    compute_bottleneck = "Visitor reports a compute bottleneck."
    primary_pain = "Speed"
    workload_type = "Dense / complex linear algebra"
    current_stack = factory.LazyFunction(lambda: ["Python / SciPy / NumPy"])
    commercial_intent = "Non-exclusive"
    timeline = "This quarter"
    score = 65
    tier = 2
    score_breakdown = factory.LazyFunction(
        lambda: {
            "strategic_fit": 18,
            "technical_fit": 17,
            "urgency": 14,
            "budget_authority": 10,
            "license_potential": 6,
        }
    )
    recommended_next_step = "Start a focused ALPHA evaluation."
    status = "New"
    qualification = factory.LazyFunction(dict)
