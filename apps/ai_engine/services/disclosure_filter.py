"""Disclosure authorization filter.

Truth, model-readability, account state and NDA state are separate concerns.  For every
non-team caller the baseline ceiling is public/controlled-public.  Content in the
``authorized``, agreement-gated (``nda_only``), or private customer-contract tiers is
visible only when the *specific document* has an active ContentAuthorization for the
current subject.  An NDA is a prerequisite for agreement-gated content; it is never an
authorization by itself.
"""
from __future__ import annotations

DISCLOSURE_ORDER = [
    "public", "controlled_public", "authorized", "nda_only", "customer_contract",
    "internal_only", "prohibited",
]

# Baseline levels.  Deliberately, ``nda`` and ``customer_contract`` do not automatically
# add a restricted tier. Explicit authorization below is the second, mandatory gate.
CONTEXT_ALLOWED = {
    "public": {"public"},
    "controlled": {"public", "controlled_public"},
    "authorized": {"public", "controlled_public"},
    "nda": {"public", "controlled_public"},
    "customer_contract": {"public", "controlled_public"},
    "internal": {
        "public", "controlled_public", "authorized", "nda_only", "customer_contract", "internal_only",
    },
}
NEVER_PUBLIC = {"internal_only", "prohibited"}
RESTRICTED = {"authorized", "nda_only", "customer_contract"}


def allowed_levels(context: str) -> set[str]:
    return CONTEXT_ALLOWED.get(context, {"public"})


def authorized_levels(*, nda_signed: bool = False, contract_executed: bool = False) -> set[str]:
    levels = {"authorized"}
    if nda_signed or contract_executed:
        levels.add("nda_only")
    if contract_executed:
        levels.add("customer_contract")
    return levels


def query_candidate_levels(
    context: str, *, has_explicit_authorization: bool = False,
    nda_signed: bool = False, contract_executed: bool = False,
) -> set[str]:
    levels = set(allowed_levels(context))
    if context != "internal" and has_explicit_authorization:
        levels |= authorized_levels(nda_signed=nda_signed, contract_executed=contract_executed)
    return levels - {"prohibited"}


def is_allowed(level: str, *, context: str = "public") -> bool:
    level = (level or "public").lower()
    if level == "prohibited":
        return False
    return level in allowed_levels(context)


def filter_chunks(
    chunks: list[dict], *, context: str = "public", customer_scope: str = "",
    authorized_document_ids: set[str] | None = None,
    nda_signed: bool = False, contract_executed: bool = False,
) -> list[dict]:
    """Fail-closed response authorization for retrieved chunks."""
    baseline = allowed_levels(context)
    explicit = {str(x) for x in (authorized_document_ids or set())}
    explicit_levels = authorized_levels(
        nda_signed=nda_signed, contract_executed=contract_executed
    ) if explicit else set()
    kept: list[dict] = []
    for chunk in chunks:
        metadata = chunk.get("metadata", {}) or {}
        level = (chunk.get("disclosure_level") or metadata.get("disclosure_level") or "public").lower()
        doc_id = str(chunk.get("document_id") or metadata.get("document_id") or "")
        if level == "prohibited":
            continue
        if level in NEVER_PUBLIC and context != "internal":
            continue
        if context != "internal" and level in RESTRICTED:
            if doc_id not in explicit or level not in explicit_levels:
                continue
        elif level not in baseline:
            continue

        if level == "customer_contract" and context != "internal":
            chunk_scope = str(chunk.get("customer_scope") or metadata.get("customer_scope") or "")
            caller_scope = str(customer_scope or "")
            # Customer-contract material has two independent gates: explicit document
            # authorization above and exact customer scope here.  Missing scope on either
            # side is closed, not treated as a wildcard.
            if not caller_scope or not chunk_scope or chunk_scope != caller_scope:
                continue
            if not contract_executed:
                continue
        kept.append(chunk)
    return kept


def filter_proofs(
    proofs: list[dict], *, context: str = "public", authorized: bool = False,
    nda_signed: bool = False, contract_executed: bool = False,
) -> list[dict]:
    baseline = allowed_levels(context)
    extra = authorized_levels(nda_signed=nda_signed, contract_executed=contract_executed) if authorized else set()
    permitted = baseline | extra
    return [
        p for p in proofs
        if (p.get("disclosure") or "public").lower() in permitted
        and ((p.get("disclosure") or "public").lower() != "prohibited")
    ]
