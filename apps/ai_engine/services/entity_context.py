"""
NAMED ENTITIES, RESOLVED DETERMINISTICALLY.

── WHAT WAS MISSING ────────────────────────────────────────────────────────
Nothing anywhere in the retrieval path knew what a name was. "Elon Musk" was three
tokens embedded alongside everything else, so a question mentioning him retrieved on
generic similarity and the reply came back with no idea that SpaceX, Tesla and xAI
were the relevant ground — even though the itriX roadmap names SpaceX and xAI
explicitly as target accounts.

A visitor asking "would this be useful to Elon Musk?" is asking a real commercial
question: which of his organisations has the workload shape itriX addresses? The
answer is available and specific. The system just could not see the question.

── WHY A TABLE AND NOT A MODEL ─────────────────────────────────────────────
Two reasons, and the second is the important one.

First: an entity list is small, auditable and cheap. A person can read it and say
whether it is right.

Second, and this is the constraint that decides it — Layer 1 is deterministic and
LLM-free by design. If a model inferred which company a visitor "really" meant, an
inference would be steering what knowledge gets retrieved and what the visitor is
told about their own organisation. That is precisely the class of decision the
architecture keeps out of the model's hands. A table cannot hallucinate an
affiliation.

── WHAT THIS DOES AND DOES NOT ASSERT ──────────────────────────────────────
It attaches PUBLICLY KNOWN AFFILIATIONS and the workload families those
organisations are publicly associated with. It never asserts that the named person
or company is a customer, a prospect, in conversation with itriX, or has evaluated
anything. It never infers that the visitor works there — a visitor mentioning Elon
Musk is not a claim to be Elon Musk, and the enrichment says so explicitly so the
model does not quietly assume it.

The no-inference rule on titles and personas is untouched: nothing here is written to
a Lead, a thread title or a persona field. It only widens the retrieval query and
adds a short grounding note to the prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Entity:
    """One recognised name and the ground it should pull in."""

    canonical: str
    #: Lowercased spellings that resolve to this entity. Matched on word boundaries.
    aliases: tuple[str, ...]
    #: Publicly-known organisations, for a person. Empty for an organisation itself.
    organisations: tuple[str, ...] = ()
    #: Workload families these organisations are publicly associated with. Phrased as
    #: search terms, because that is what they are used for.
    workloads: tuple[str, ...] = field(default_factory=tuple)
    #: One sentence of honest grounding for the prompt. No claim of any relationship.
    note: str = ""


# ── People ──────────────────────────────────────────────────────────────────
# Deliberately short. A name earns a place here when its organisations have a
# workload shape itriX actually addresses — not because the name is famous.
_PEOPLE: tuple[Entity, ...] = (
    Entity(
        canonical="Elon Musk",
        aliases=("elon musk", "elon", "musk"),
        organisations=("SpaceX", "Tesla", "xAI"),
        workloads=(
            "aerospace and launch simulation",
            "computational fluid dynamics",
            "autonomous driving perception training and inference",
            "large language model training at scale",
            "energy and thermal constrained edge inference",
        ),
        note=(
            "Publicly associated with SpaceX (launch and re-entry simulation, "
            "computational fluid dynamics), Tesla (autonomy training and in-vehicle "
            "inference under strict power and thermal budgets) and xAI (large-scale "
            "model training). All three sit in workload families itriX addresses: "
            "conservation-heavy simulation, data-movement-bound training, and "
            "energy-constrained edge execution. SpaceX and xAI appear on the itriX "
            "commercial roadmap as target accounts, which is a statement about itriX's "
            "own intentions and NOT about any existing relationship."
        ),
    ),
    Entity(
        canonical="Jensen Huang",
        aliases=("jensen huang", "jensen"),
        organisations=("NVIDIA",),
        workloads=(
            "accelerator architecture",
            "tensor computation throughput",
            "memory bandwidth and data movement",
        ),
        note=(
            "Publicly associated with NVIDIA. Relevant because itriX operates one "
            "layer below the accelerator: representation decides how well a workload "
            "fits the hardware it runs on, whoever built that hardware. itriX is not "
            "a competitor to an accelerator vendor and should never be described as "
            "one."
        ),
    ),
    Entity(
        canonical="Sam Altman",
        aliases=("sam altman", "altman"),
        organisations=("OpenAI",),
        workloads=(
            "large language model training and inference at scale",
            "inference cost per token",
            "data centre power and cooling limits",
        ),
        note=(
            "Publicly associated with OpenAI. The relevant workload family is frontier "
            "model training and high-volume inference, where cost growth and power "
            "ceilings are the reported pressures — the case itriX addresses as "
            "structural rather than cyclical."
        ),
    ),
)

# ── Organisations ───────────────────────────────────────────────────────────
# The twelve accounts in the itriX target-persona set, plus the two named on the
# roadmap. Kept flat rather than nested, so a match is one lookup.
_ORGS: tuple[Entity, ...] = (
    Entity("SpaceX", ("spacex", "space x"),
           workloads=("launch and re-entry simulation", "computational fluid dynamics",
                      "conservation-heavy physics simulation"),
           note="Aerospace simulation is conservation-heavy, which is the workload family FQNM "
                "addresses. Named on the itriX commercial roadmap as a target account."),
    Entity("Tesla", ("tesla",),
           workloads=("autonomous driving perception", "in-vehicle inference",
                      "energy and thermal constrained edge inference"),
           note="Autonomy training at scale plus in-vehicle inference under strict power and "
                "thermal budgets — both families itriX addresses."),
    Entity("xAI", ("xai", "x.ai"),
           workloads=("large language model training at scale", "inference cost"),
           note="Frontier model training. Named on the itriX commercial roadmap as a target account."),
    Entity("Samsung Electronics", ("samsung", "samsung electronics"),
           workloads=("semiconductor design and verification", "memory subsystem design",
                      "on-device inference"),
           note="Semiconductor and memory design, and on-device inference. A primary licensing "
                "target in the itriX roadmap."),
    Entity("SK hynix", ("sk hynix", "hynix", "sk 하이닉스"),
           workloads=("memory subsystem design", "data movement and bandwidth"),
           note="Memory and data movement are where representation has the most direct leverage. "
                "A primary licensing target in the itriX roadmap."),
    Entity("NVIDIA", ("nvidia",),
           workloads=("accelerator architecture", "tensor computation", "memory bandwidth"),
           note="itriX sits one layer below the accelerator and is not a competitor to one."),
    Entity("OpenAI", ("openai", "open ai"),
           workloads=("large language model training and inference", "inference cost per token"),
           note="Frontier training and high-volume inference — cost growth and power ceilings."),
    Entity("Google", ("google", "alphabet", "deepmind", "google deepmind"),
           workloads=("large model training", "TPU accelerator workloads",
                      "climate and science simulation"),
           note="Spans frontier training, custom accelerators and scientific simulation."),
    Entity("Microsoft", ("microsoft", "azure"),
           workloads=("cloud inference at scale", "data centre power and cooling"),
           note="Cloud-scale inference, where power and cooling are often the binding constraint."),
    Entity("Amazon", ("amazon", "aws"),
           workloads=("cloud inference at scale", "custom silicon workloads"),
           note="Cloud-scale inference and custom silicon."),
    Entity("Meta", ("meta", "facebook"),
           workloads=("recommendation model training", "large model training",
                      "inference at scale"),
           note="Recommendation and frontier training, both data-movement heavy."),
    Entity("Apple", ("apple",),
           workloads=("on-device inference", "energy and thermal constrained execution"),
           note="On-device inference under tight power and thermal budgets."),
    Entity("Intel", ("intel",),
           workloads=("CPU architecture", "server CPU workloads"),
           note="Server-CPU workloads are growing as inference outweighs training — the trend the "
                "itriX public explainer opens on."),
    Entity("AMD", ("amd",),
           workloads=("CPU and GPU architecture", "server CPU workloads"),
           note="Server-CPU and accelerator workloads."),
    Entity("IBM", ("ibm",),
           workloads=("HPC and simulation", "quantum and scientific computing"),
           note="HPC and scientific simulation, where numerical stability matters."),
)

_ALL: tuple[Entity, ...] = _PEOPLE + _ORGS


def _pattern(alias: str) -> re.Pattern[str]:
    """
    Word-boundary match, so "meta" does not fire inside "metadata" and "amd" does
    not fire inside "amdahl".
    """
    return re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.IGNORECASE)


_COMPILED: tuple[tuple[re.Pattern[str], Entity], ...] = tuple(
    (_pattern(a), e) for e in _ALL for a in e.aliases
)


def recognise(text: str) -> list[Entity]:
    """
    Every entity named in ``text``, in the order the table declares them.

    Order is the table's, not the text's, so the result is stable for the same input
    regardless of how the visitor phrased it — a prompt that changes between
    identical questions is a prompt nobody can debug.

    Longest alias wins per entity, and each entity appears at most once.
    """
    if not text:
        return []
    seen: list[Entity] = []
    for entity in _ALL:
        if entity in seen:
            continue
        if any(pat.search(text) for pat, e in _COMPILED if e is entity):
            seen.append(entity)
    return seen


def expand_query(text: str, *, limit: int = 3) -> str:
    """
    Widen a retrieval query with the workload families a named entity implies.

    "Would this help Elon Musk?" embeds nothing about aerospace simulation or
    autonomy, so it retrieves on generic similarity and finds generic chunks.
    Appending the workload terms puts the query in the same region of the space as
    the material that actually answers it.

    The visitor's own words come FIRST and are never replaced — this appends, so a
    question that was already specific is not diluted by the table.
    """
    entities = recognise(text)[:limit]
    if not entities:
        return text
    terms: list[str] = []
    for e in entities:
        terms.extend(e.workloads)
    if not terms:
        return text
    # De-duplicated, order preserved.
    unique = list(dict.fromkeys(terms))
    return f"{text}\n\n{' · '.join(unique)}"


def grounding_note(text: str, *, limit: int = 3) -> str:
    """
    A short, honest grounding block for the system prompt, or "" when nothing matched.

    Every line is a public affiliation. Nothing here says the named party is a
    customer, a prospect, or in conversation with itriX, and the closing line stops
    the model assuming the visitor works there.
    """
    entities = recognise(text)[:limit]
    if not entities:
        return ""

    lines = ["RECOGNISED NAMES IN THE VISITOR'S MESSAGE (public affiliations only):"]
    for e in entities:
        orgs = f" — {', '.join(e.organisations)}" if e.organisations else ""
        lines.append(f"- {e.canonical}{orgs}: {e.note}")
    lines.append(
        "Use this to answer which itriX products and workload families are relevant. "
        "Do NOT state or imply that any named person or organisation is an itriX "
        "customer, prospect, partner or evaluator — none of that is asserted here. Do "
        "NOT assume the visitor works for, speaks for, or is the named party; they have "
        "only mentioned them."
    )
    return "\n".join(lines)
