"""
Pinecone <-> database audit. READ ONLY — deletes nothing, writes nothing.

Run from the repo root with the venv active:

    python manage.py shell < pinecone_audit.py

Answers three questions:

  1. How many vectors are actually in the index, per namespace?
  2. How many SHOULD be there, according to the KnowledgeChunk rows?
  3. Is anything in the index that the database no longer knows about
     (orphans from an earlier ingestion under different document UUIDs)?

Question 3 is the one that matters. Vector IDs are `f"{document.id}:{chunk.index}"`,
so if the KnowledgeDocument rows were ever recreated, the new ingest wrote a SECOND
copy under new IDs and the old copies are unreferenced — still returned by retrieval,
via their `preview` metadata, competing for the same top_k slots.
"""

from collections import Counter

from django.conf import settings

from apps.knowledge_core.models import KnowledgeChunk, KnowledgeDocument

print()
print("=" * 78)
print("CONFIG")
print("=" * 78)
print(f"  index            : {settings.PINECONE_INDEX}")
print(f"  ENABLE_AI_ENGINE : {settings.ENABLE_AI_ENGINE}")
print(f"  api key present  : {bool(settings.PINECONE_API_KEY)}")
print(f"  database         : {settings.DATABASES['default'].get('HOST')}")

# ── 1 · what the DB expects ────────────────────────────────────────────────
print()
print("=" * 78)
print("DATABASE — what SHOULD be in the index")
print("=" * 78)

db_by_ns = Counter()
for row in KnowledgeChunk.objects.values("namespace"):
    db_by_ns[row["namespace"] or "(none)"] += 1

db_total = sum(db_by_ns.values())
for ns in sorted(db_by_ns):
    print(f"  {ns:<18} {db_by_ns[ns]:>6} chunks")
print(f"  {'TOTAL':<18} {db_total:>6} chunks")

print()
print(f"  documents        : {KnowledgeDocument.objects.count()}")
for status, n in Counter(
    KnowledgeDocument.objects.values_list("ingestion_status", flat=True)
).items():
    print(f"    {status:<16} {n}")

# ── 2 · what the index actually holds ──────────────────────────────────────
print()
print("=" * 78)
print("PINECONE — what IS in the index")
print("=" * 78)

try:
    from pinecone import Pinecone

    pc = Pinecone(api_key=settings.PINECONE_API_KEY)
    index = pc.Index(settings.PINECONE_INDEX)
    stats = index.describe_index_stats()

    namespaces = stats.get("namespaces") or {}
    pc_total = stats.get("total_vector_count", 0)

    print(f"  dimension        : {stats.get('dimension')}")
    print(f"  total vectors    : {pc_total}")
    print()
    for ns in sorted(namespaces):
        print(f"  {ns:<18} {namespaces[ns].get('vector_count', 0):>6} vectors")

    # ── 3 · the verdict ────────────────────────────────────────────────────
    print()
    print("=" * 78)
    print("COMPARISON — index vs database, per namespace")
    print("=" * 78)
    print(f"  {'namespace':<18} {'pinecone':>9} {'database':>9} {'orphans':>9}")
    print(f"  {'-' * 18} {'-' * 9} {'-' * 9} {'-' * 9}")

    total_orphans = 0
    for ns in sorted(set(namespaces) | set(db_by_ns)):
        in_pc = (namespaces.get(ns) or {}).get("vector_count", 0)
        in_db = db_by_ns.get(ns, 0)
        gap = in_pc - in_db
        total_orphans += max(0, gap)
        flag = "  <-- STALE" if gap > 0 else ("  <-- MISSING" if gap < 0 else "")
        print(f"  {ns:<18} {in_pc:>9} {in_db:>9} {gap:>9}{flag}")

    print()
    if total_orphans > 0:
        print(f"  ~{total_orphans} vectors in the index have NO database row.")
        print("  These are almost certainly from an earlier ingestion under different")
        print("  document UUIDs. Retrieval still returns them — using the truncated")
        print("  `preview` metadata instead of full text — so they take top_k slots")
        print("  away from the current chunks.")
        print()
        print("  purge_vectors CANNOT remove them: it looks chunk ids up from the DB,")
        print("  and there are no rows pointing at these. Use reingest_namespace,")
        print("  which clears the whole namespace before re-upserting:")
        print()
        for ns in sorted(set(namespaces) | set(db_by_ns)):
            in_pc = (namespaces.get(ns) or {}).get("vector_count", 0)
            if in_pc - db_by_ns.get(ns, 0) > 0:
                print(f"      python manage.py reingest_namespace --namespace {ns}")
    else:
        print("  CLEAN — every vector in the index has a live database row.")
        print("  Nothing to purge; the earlier ingestion was overwritten in place.")

    # ── 4 · spot-check a real retrieval ───────────────────────────────────
    print()
    print("=" * 78)
    print("SPOT CHECK — what 'what is itriX' actually retrieves")
    print("=" * 78)

    from apps.knowledge_core.services.embedder import Embedder

    vec = Embedder().embed_one("What is itriX and what does it do?")
    res = index.query(vector=vec, top_k=6, namespace="general", include_metadata=True)
    matches = res.get("matches") or []

    live = {c.vector_id for c in KnowledgeChunk.objects.filter(
        vector_id__in=[m["id"] for m in matches if m.get("id")]
    )}

    for m in matches:
        vid = m.get("id", "")
        md = m.get("metadata") or {}
        state = "live" if vid in live else "ORPHAN"
        print(f"  [{state:<6}] {m.get('score', 0):.3f}  {md.get('disclosure_level', '?'):<18} "
              f"{(md.get('document_title') or '?')[:38]}")

    orphan_hits = sum(1 for m in matches if m.get("id") not in live)
    print()
    print(f"  {orphan_hits} of {len(matches)} retrieved chunks are orphans.")
    if orphan_hits:
        print("  Each one is a slot that could have held current full text.")

    # ── 5 · tier isolation, the thing worth being sure about ──────────────
    print()
    print("=" * 78)
    print("TIER CHECK — is anything above public reachable in 'general'?")
    print("=" * 78)
    tiers = Counter()
    res2 = index.query(vector=vec, top_k=50, namespace="general", include_metadata=True)
    for m in (res2.get("matches") or []):
        tiers[((m.get("metadata") or {}).get("disclosure_level") or "(missing)")] += 1
    for tier in sorted(tiers):
        mark = "" if tier == "public" else "  <-- filtered at retrieval, not by namespace"
        print(f"  {tier:<20} {tiers[tier]:>4}{mark}")
    print()
    print("  Non-public tiers sharing this namespace is expected — isolation is the")
    print("  disclosure filter, not the namespace. Worth confirming an anonymous")
    print("  visitor cannot surface NDA content by asking for it directly.")

except Exception as exc:  # noqa: BLE001
    print()
    print(f"  Could not reach Pinecone: {type(exc).__name__}: {exc}")
    print("  Check PINECONE_API_KEY and that ENABLE_AI_ENGINE is True.")

print()