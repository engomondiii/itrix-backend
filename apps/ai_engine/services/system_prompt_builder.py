"""
System-prompt builder.

Assembles the system prompt for the result-generation call: the itriX brand voice and
positioning, the claims-discipline rules (no guarantees / superlatives; defer quantitative
claims to a validated PoC), the disclosure context, and the retrieved knowledge as grounding
context. Keeping prompt construction here makes the AI's behaviour auditable and consistent.
"""

from __future__ import annotations

_BRAND_CORE = (
    "You are the itriX representation-and-runtime advisor. itriX commercialises patented "
    "computation-substrate technology. Core thesis: don't scale inefficient computation — "
    "make computation worth scaling first. The Knowledge Core triad is AXIOM, CRE, and FQNM. "
    "Products: ALPHA Compute (representation diagnosis — the adoption wedge) and ALPHA Core "
    "(runtime/execution). Pricing is one-third value participation."
)

_CLAIMS_DISCIPLINE = (
    "CLAIMS DISCIPLINE (strict):\n"
    "- Never guarantee specific savings, speedups, accuracy, or universal results.\n"
    "- Never use absolutes ('always', '100%', 'every workload', 'replaces your hardware').\n"
    "- Defer all quantitative performance claims to a validated proof-of-concept.\n"
    "- Prefer hedged, conditional language ('may', 'in eligible cases', 'subject to validation').\n"
    "- Only use facts supported by the provided knowledge context; if unsure, stay qualitative."
)


_RESULT_PAGE_TASK = (
    "TASK: Produce a personalised, honest diagnosis of the visitor's computation "
    "bottleneck and how ALPHA could help, suitable for a public result page. Keep it "
    "concrete but qualitative, and consistent with the claims discipline above."
)

_CONVERSATION_TASK = (
    "TASK: You are in a live conversation. ANSWER THE QUESTION THE VISITOR ACTUALLY "
    "ASKED.\n"
    "- If they ask what itriX is, what it sells, who is behind it, what AXIOM, CRE or "
    "FQNM are, how pricing works, or what an engagement involves — answer that "
    "directly and substantively from the knowledge context. These are fair questions "
    "and refusing them is not discretion, it is unhelpfulness.\n"
    "- Do NOT turn every question into a diagnosis of their workload. A question "
    "about the company is not a request to be qualified.\n"
    "- Do NOT ask for their workload details as a precondition for answering "
    "something general.\n"
    "- Where the knowledge context genuinely does not cover what they asked, say so "
    "plainly in one sentence and answer as much as you can. Never invent a figure, a "
    "customer, a benchmark or a capability.\n"
    "- Then, if it is natural, you may add one short sentence moving the conversation "
    "forward. One, not a paragraph.\n"
    "THE ENGAGEMENT PATH — so you never have to invent one: when a visitor is ready "
    "to move forward, what happens next is a personalised itriX page generated in "
    "THIS conversation, and the system will instruct you at the right moment to ask "
    "for the one detail it needs. Until that instruction arrives, do not ask for "
    "contact details on your own. NEVER tell a visitor that the team 'has been "
    "notified' or 'will reach out', never promise a human follow-up as the outcome, "
    "and never offer a 'contact form' — no notification has been sent, and no such "
    "form exists. If a visitor says they want to proceed, acknowledge it and "
    "continue the conversation; the system handles what comes next.\n"
    "Warm, precise, and within the claims discipline above."
)


def _format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "(no specific knowledge retrieved — stay general and qualitative)"
    lines = []
    for i, c in enumerate(chunks, 1):
        heading = c.get("heading") or "Context"
        text = (c.get("text") or "").strip()
        if text:
            lines.append(f"[{i}] {heading}\n{text}")
    return "\n\n".join(lines) if lines else "(no usable knowledge text)"


def build_system_prompt(
    *,
    product_route: str,
    license_pathway: str | None,
    tier: int,
    pressures: list[str],
    chunks: list[dict],
    context: str = "public",
    task: str | None = None,
) -> str:
    """
    Return the full system prompt.

    ``task`` overrides the closing instruction. It defaults to result-page
    generation, which is what every existing caller wants; the conversational
    concierge passes ``_CONVERSATION_TASK`` instead (see
    ``build_conversation_system_prompt``).
    """
    return "\n\n".join(
        [
            _BRAND_CORE,
            _CLAIMS_DISCIPLINE,
            (
                f"VISITOR CONTEXT:\n"
                f"- Routed product: {product_route}\n"
                f"- Commercial pathway: {license_pathway or 'product use / undecided'}\n"
                f"- Tier: {tier}\n"
                f"- Pressure areas: {', '.join(pressures) if pressures else 'unspecified'}\n"
                f"- Disclosure context: {context} (do not reveal anything above this tier)"
            ),
            f"KNOWLEDGE CONTEXT (grounding — cite only what's here):\n{_format_context(chunks)}",
            task or _RESULT_PAGE_TASK,
        ]
    )


def build_conversation_system_prompt(
    *,
    product_route: str,
    license_pathway: str | None,
    tier: int,
    pressures: list[str],
    chunks: list[dict],
    context: str = "public",
    question: str = "",
) -> str:
    """
    The system prompt for a CONVERSATIONAL turn, as distinct from page generation.

    ── WHY THIS EXISTS ──────────────────────────────────────────────────────
    There was one builder, and its TASK line read: "Produce a personalised, honest
    diagnosis of the visitor's computation bottleneck ... suitable for a public
    result page."

    The conversational concierge used that same builder for every turn. So when a
    visitor asked "what is itriX?", the model had just been instructed that its job
    was to diagnose their computation bottleneck for a result page — and it did the
    only thing that instruction allows: it turned an ordinary question about the
    company into bottleneck framing, or declined it.

    That is the whole of the reported "can't answer what is itriX". Retrieval was
    working and the knowledge was reachable; the model was simply told to be doing
    something else.

    Everything protective is unchanged and shared: the brand core, the claims
    discipline, the disclosure context, and grounding on retrieved chunks only. Only
    the TASK differs — and it has to, because answering a question and generating a
    page are not the same job.
    """
    base = build_system_prompt(
        product_route=product_route,
        license_pathway=license_pathway,
        tier=tier,
        pressures=pressures,
        chunks=chunks,
        context=context,
        task=_CONVERSATION_TASK,
    )

    # Named entities, resolved from a table rather than inferred by the model. See
    # entity_context for why that constraint is not negotiable.
    note = ""
    if question:
        try:
            from apps.ai_engine.services import entity_context

            note = entity_context.grounding_note(question)
        except Exception:  # noqa: BLE001 - enrichment is never load-bearing
            note = ""
    return f"{base}\n\n{note}" if note else base


# ─────────────────────────────────────────────────────────────────────────────
# v6.0: fenced untrusted attachment content (§4.5, §19.7 rule 5)
# ─────────────────────────────────────────────────────────────────────────────
def with_attachment_context(system_prompt: str, thread=None, query: str = "") -> str:
    """
    Append the visitor's attachment excerpts, FENCED as untrusted data.

    The fence carries a standing instruction that the enclosed content is DATA TO BE
    ANALYSED and never instructions to be followed.

    BE CLEAR ABOUT WHAT THIS BUYS. The fence is the weaker half of the pair. Injection
    defense is an ASSEMBLY-LAYER property: what actually holds is that the decisions
    worth attacking — disclosure ceiling, retrieval context, journey state, pricing,
    gating — are all made DETERMINISTICALLY OUTSIDE the model. An injected instruction
    has nothing to subvert because the model never held those decisions.
    """
    if thread is None:
        return system_prompt
    try:
        from apps.attachments.services import excerpts, fencing

        items = excerpts.for_context(thread, query)
        if not items:
            return system_prompt
        return f"{system_prompt}\n\n{fencing.fence_many(items)}"
    except Exception:  # noqa: BLE001 - attachments are flag-gated and optional
        return system_prompt
