"""
The target-account persona registry (Backend v6.0 §1.3, Architecture v2.6 §13.3).

Seeded from the 60-persona workbook: 12 strategic accounts x 5 functional families.
Joined to the Lead by a nullable ``persona`` FK.

── THIS ENTIRE APP IS INTERNAL-ONLY ─────────────────────────────────────────
Not "internal by convention" — internal by serializer allow-list, enforced on the team
plane only. ``persona_id`` and ``pitch_room_id`` appear in the §10.5 list of fields that
must NOT appear in ANY payload on the anonymous or client plane, at any state, in any
turn, artifact or card.

The reason is in §4:

    PERSONALIZATION WITHOUT PROFILING
    Personalization means the framing, the emphasis and the chosen pathway are tailored.
    It never means telling the visitor what we think we know about them. The most
    tailored pitch and the safest pitch must be the same pitch.

So a persona match changes WHICH pitch room is rendered. It never produces a sentence
that names the match.

── DEPARTMENT NAMES ARE EXPLICITLY HYPOTHESES ───────────────────────────────
``validation_status`` defaults to ``hypothesis`` and ``department_confidence`` carries
the researcher's own caveat. A hypothesis that gets rendered as an assertion is exactly
the failure mode this field exists to prevent.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class FunctionalFamily(models.TextChoices):
    """
    The five functional families. These map ONE-TO-ONE onto the five example prompts on
    the landing page (Architecture v2.6 §2.2), so the example a visitor selects is the
    first self-classification signal and becomes a prior on family.
    """

    AI_MODEL_SYSTEMS = "ai_model_systems", "AI & Model Systems"
    CLOUD_INFRASTRUCTURE = "cloud_infrastructure", "Cloud & Infrastructure"
    SILICON_MEMORY_HARDWARE = "silicon_memory_hardware", "Silicon, Memory & Hardware"
    RUNTIME_HPC_SIMULATION = "runtime_hpc_simulation", "Runtime, HPC & Simulation"
    STRATEGIC_PRODUCT_PARTNERSHIPS = (
        "strategic_product_partnerships",
        "Strategic Product & Partnerships",
    )


class ValidationStatus(models.TextChoices):
    HYPOTHESIS = "hypothesis", "Hypothesis"
    VALIDATED = "validated", "Validated"
    REJECTED = "rejected", "Rejected"


class DisclosureCeiling(models.TextChoices):
    PUBLIC = "public", "Public"
    CONTROLLED_PUBLIC = "controlled_public", "Controlled public"
    NDA_ONLY = "nda_only", "NDA only"


class Persona(BaseModel):
    """One department-level persona at one strategic account."""

    persona_id = models.CharField(max_length=16, unique=True, db_index=True)
    company = models.CharField(max_length=120, db_index=True)
    department = models.CharField(max_length=200, blank=True, default="")
    primary_persona = models.CharField(max_length=200, blank=True, default="")

    functional_family = models.CharField(
        max_length=40, choices=FunctionalFamily.choices, db_index=True
    )
    pitch_archetype = models.CharField(max_length=120, blank=True, default="")

    # How this buyer decides.
    buying_role = models.CharField(max_length=200, blank=True, default="")
    decision_lens = models.CharField(max_length=300, blank=True, default="")
    department_mandate = models.TextField(blank=True, default="")
    trigger_event = models.TextField(blank=True, default="")

    # What they measure.
    primary_kpi = models.CharField(max_length=200, blank=True, default="")
    supporting_kpis = models.JSONField(default=list, blank=True)

    # The technical hypothesis.
    workload_environment = models.TextField(blank=True, default="")
    boundary_waste_hypothesis = models.TextField(blank=True, default="")
    desired_gain = models.TextField(blank=True, default="")

    # Room preparation — used to PREPARE the room, never to score the person.
    likely_champion = models.CharField(max_length=200, blank=True, default="")
    likely_blocker = models.CharField(max_length=200, blank=True, default="")
    likely_objection = models.TextField(blank=True, default="")
    response_angle = models.TextField(blank=True, default="")

    # Commercial routing.
    first_value_artifact = models.CharField(max_length=200, blank=True, default="")
    personalized_cta = models.CharField(max_length=200, blank=True, default="")
    commercial_route = models.CharField(max_length=200, blank=True, default="")
    product_route = models.CharField(max_length=200, blank=True, default="")

    disclosure_ceiling = models.CharField(
        max_length=24,
        choices=DisclosureCeiling.choices,
        default=DisclosureCeiling.CONTROLLED_PUBLIC,
    )
    priority = models.PositiveSmallIntegerField(default=3)
    validation_status = models.CharField(
        max_length=16, choices=ValidationStatus.choices, default=ValidationStatus.HYPOTHESIS
    )
    # The researcher's own caveat about the reporting line. Kept verbatim so nobody
    # downstream mistakes a hypothesis for a verified org chart.
    department_confidence = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["persona_id"]
        verbose_name = "Persona"
        verbose_name_plural = "Personas"
        indexes = [
            models.Index(fields=["functional_family", "priority"]),
            models.Index(fields=["company", "functional_family"]),
        ]

    def __str__(self) -> str:
        return f"{self.persona_id} {self.company} / {self.department}"

    @property
    def is_hypothesis(self) -> bool:
        return self.validation_status == ValidationStatus.HYPOTHESIS


class PitchRoom(BaseModel):
    """
    The 5-7 slide personalized brief for one persona.

    Each slide carries its own disclosure level, so per-slide governance is possible: a
    room can render its first four slides publicly while holding the proof slide behind
    an NDA (Architecture v2.6 §4).
    """

    pitch_room_id = models.CharField(max_length=24, unique=True, db_index=True)
    persona = models.OneToOneField(
        Persona, on_delete=models.CASCADE, related_name="pitch_room"
    )
    title = models.CharField(max_length=300, blank=True, default="")
    # [{key, title, body, disclosure}] — ordered.
    slides = models.JSONField(default=list, blank=True)

    review_status = models.CharField(max_length=40, blank=True, default="draft")

    class Meta:
        ordering = ["pitch_room_id"]
        verbose_name = "Pitch room"
        verbose_name_plural = "Pitch rooms"

    def __str__(self) -> str:
        return f"{self.pitch_room_id} ({self.persona.persona_id})"

    @property
    def slide_count(self) -> int:
        return len(self.slides or [])
