"""
Persona matching (Backend v6.0 §1.3, Architecture v2.6 §12.3).

Resolve a Lead to a persona hypothesis so the Pitch Agent can key its room. The match
order is EXACT PERSONA -> FUNCTIONAL FAMILY -> GENERIC, and the chosen path is recorded
on the AgentRun so the cockpit can audit which route produced a given room.

── WHAT A MATCH IS AND IS NOT ───────────────────────────────────────────────
A match is a HYPOTHESIS about which framing will land, not a claim about who the visitor
is. It changes WHICH pitch room renders. It never produces a sentence that names the
match, the company, the department or the score.

    PERSONALIZATION WITHOUT PROFILING (Architecture v2.6 §4)
    The most tailored pitch and the safest pitch must be the same pitch.

── WHY THE FAMILY PRIOR IS DELIBERATELY WEAK ────────────────────────────────
The five landing examples map one-to-one onto the five functional families, so the
example a visitor taps is a real signal. But it is a signal about the PROBLEM SHAPE,
not about the organisation. So the family prior is used to pick a template; only a
strong, corroborated company signal can promote a match to an exact persona.

Confidence is returned alongside every match so callers can refuse to act on a weak one.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from apps.personas.models import FunctionalFamily, Persona

logger = logging.getLogger("itrix")

MATCH_EXACT = "exact"
MATCH_FAMILY = "family"
MATCH_GENERIC = "generic"

# Confidence floor below which a match must NOT be promoted to an exact persona.
EXACT_MATCH_MIN_CONFIDENCE = 0.75


@dataclass(frozen=True)
class PersonaMatch:
    """The result of one match attempt. Internal-only in its entirety."""

    persona: Persona | None
    path: str
    confidence: float
    family: str | None = None
    reason: str = ""

    @property
    def is_exact(self) -> bool:
        return self.path == MATCH_EXACT and self.persona is not None

    def digest(self) -> dict:
        """A loggable summary for the AgentRun (never visitor-facing)."""
        return {
            "persona_id": self.persona.persona_id if self.persona else None,
            "match_path": self.path,
            "confidence": round(self.confidence, 3),
            "family": self.family,
            "reason": self.reason,
        }


# The five landing examples map 1:1 onto the five families (Architecture v2.6 §2.2).
EXAMPLE_TO_FAMILY = {
    "ai_model_systems": FunctionalFamily.AI_MODEL_SYSTEMS,
    "cloud_infrastructure": FunctionalFamily.CLOUD_INFRASTRUCTURE,
    "silicon_memory_hardware": FunctionalFamily.SILICON_MEMORY_HARDWARE,
    "runtime_hpc_simulation": FunctionalFamily.RUNTIME_HPC_SIMULATION,
    "strategic_product_partnerships": FunctionalFamily.STRATEGIC_PRODUCT_PARTNERSHIPS,
}

# Keyword signals per family, used only when no example was selected. Deliberately
# coarse: this picks a TEMPLATE, so a wrong guess costs emphasis, not correctness.
_FAMILY_SIGNALS: dict[str, tuple[str, ...]] = {
    FunctionalFamily.AI_MODEL_SYSTEMS: (
        "training", "inference", "model", "token", "llm", "fine-tun", "attention",
        "embedding", "transformer", "serving", "checkpoint",
    ),
    FunctionalFamily.CLOUD_INFRASTRUCTURE: (
        "cloud", "data center", "datacenter", "power", "cooling", "capacity",
        "gpu-hour", "gpu hour", "fleet", "cluster", "utilization", "utilisation",
        "memory movement", "bandwidth", "tco",
    ),
    FunctionalFamily.SILICON_MEMORY_HARDWARE: (
        "silicon", "chip", "npu", "asic", "fpga", "accelerator", "sdk", "hbm",
        "memory controller", "wafer", "tape-out", "runtime path", "kernel",
    ),
    FunctionalFamily.RUNTIME_HPC_SIMULATION: (
        "solver", "simulation", "cfd", "cae", "pde", "hpc", "conservation",
        "reproducib", "numerical", "shock", "mesh", "finite volume", "finite element",
        "drift", "stability",
    ),
    FunctionalFamily.STRATEGIC_PRODUCT_PARTNERSHIPS: (
        "licens", "partnership", "strategic", "acquisition", "joint venture",
        "roadmap", "differentiat", "exclusiv", "term sheet",
    ),
}


def infer_family(*, example_key: str = "", prompt: str = "", pressures=None) -> tuple[str | None, float]:
    """
    Infer the functional family. Returns ``(family, confidence)``.

    A selected example is a STRONG prior (0.8) because the visitor chose it deliberately.
    Keyword inference is WEAK (max 0.55) because it is our reading of their words, not
    their own classification.
    """
    if example_key:
        family = EXAMPLE_TO_FAMILY.get(example_key)
        if family:
            return family.value, 0.8

    haystack = " ".join(filter(None, [prompt or "", " ".join(pressures or [])])).lower()
    if not haystack.strip():
        return None, 0.0

    scores: dict[str, int] = {}
    for family, signals in _FAMILY_SIGNALS.items():
        hits = sum(1 for signal in signals if signal in haystack)
        if hits:
            scores[family] = hits

    if not scores:
        return None, 0.0

    best = max(scores, key=lambda key: scores[key])
    total = sum(scores.values())
    # Confidence scales with dominance, capped well below the example prior.
    confidence = min(0.55, 0.25 + 0.3 * (scores[best] / max(total, 1)))
    return best, confidence


def _normalize_company(value: str) -> str:
    """Strip legal suffixes and punctuation so 'NVIDIA Corp.' matches 'NVIDIA'."""
    text = re.sub(r"[^a-z0-9 ]+", " ", (value or "").lower())
    text = re.sub(
        r"\b(inc|corp|corporation|co|ltd|limited|llc|plc|gmbh|sa|ag|holdings|group|technologies|technology)\b",
        " ",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def match_company(company: str) -> list[Persona]:
    """Personas at an account whose name matches ``company``. Empty when no match."""
    normalized = _normalize_company(company)
    if not normalized or len(normalized) < 2:
        return []
    candidates = []
    for persona in Persona.objects.exclude(validation_status="rejected"):
        if _normalize_company(persona.company) == normalized:
            candidates.append(persona)
    return candidates


def match(lead, *, example_key: str = "") -> PersonaMatch:
    """
    Resolve a Lead to a persona hypothesis.

    EXACT   the lead names a target account AND the family is confident enough to pick
            the right department within it
    FAMILY  we know the problem shape but not the organisation
    GENERIC we know neither — the safest, least-assuming room
    """
    session = getattr(lead, "review_session", None)
    prompt = (
        getattr(lead, "compute_bottleneck", "")
        or getattr(session, "prompt", "")
        or ""
    )
    pressures = list(getattr(session, "pressure_areas", []) or [])

    family, family_confidence = infer_family(
        example_key=example_key, prompt=prompt, pressures=pressures
    )

    company_personas = match_company(getattr(lead, "company", "") or "")

    if company_personas:
        # Narrow to the family when we have one; otherwise take the highest-priority
        # persona at the account. Never guess a department from a company alone.
        if family:
            in_family = [p for p in company_personas if p.functional_family == family]
            if in_family and family_confidence >= EXACT_MATCH_MIN_CONFIDENCE:
                persona = sorted(in_family, key=lambda p: (p.priority, p.persona_id))[0]
                return PersonaMatch(
                    persona=persona,
                    path=MATCH_EXACT,
                    confidence=min(0.95, 0.6 + family_confidence * 0.4),
                    family=family,
                    reason="company and family both matched",
                )
            if in_family:
                persona = sorted(in_family, key=lambda p: (p.priority, p.persona_id))[0]
                return PersonaMatch(
                    persona=persona,
                    path=MATCH_FAMILY,
                    confidence=max(family_confidence, 0.5),
                    family=family,
                    reason="company matched; family prior too weak for an exact match",
                )
        persona = sorted(company_personas, key=lambda p: (p.priority, p.persona_id))[0]
        return PersonaMatch(
            persona=persona,
            path=MATCH_FAMILY,
            confidence=0.45,
            family=persona.functional_family,
            reason="company matched; no family signal",
        )

    if family:
        persona = (
            Persona.objects.filter(functional_family=family)
            .exclude(validation_status="rejected")
            .order_by("priority", "persona_id")
            .first()
        )
        if persona is not None:
            return PersonaMatch(
                persona=persona,
                path=MATCH_FAMILY,
                confidence=family_confidence,
                family=family,
                reason="family inferred; no target-account match",
            )

    return PersonaMatch(
        persona=None,
        path=MATCH_GENERIC,
        confidence=0.0,
        family=None,
        reason="no company or family signal",
    )
