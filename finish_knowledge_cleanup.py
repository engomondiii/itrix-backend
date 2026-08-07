"""
Finish the cleanup: one row per file, at the path the file is actually at.

    python manage.py shell -c "exec(open('finish_knowledge_cleanup.py').read())"

DRY RUN BY DEFAULT. To apply:

    python manage.py shell -c "exec(open('finish_knowledge_cleanup.py').read().replace('APPLY = False','APPLY = True'))"

── WHAT IS LEFT, AND WHY THE FIRST PASS COULD NOT SEE IT ───────────────────
The first pass matched documents by path, so it only caught pairs that named the
same location. 19 pairs name DIFFERENT locations, because the files themselves
were moved between tier folders after the original ingestion:

    old row   knowledge_docs/public/Master_Thesis_2026_Feb.pdf     <- file is gone
    new row   knowledge_docs\\nda_only\\Master_Thesis_2026_Feb.pdf  <- file is here

Same document, two rows, two full sets of vectors. `public/` holds 13 files today;
19 rows still claim to live there.

That also explains the tier disagreement seen earlier — the old rows were tiered
`public` because that is genuinely where those files sat when they were registered.
Nothing was mis-assigned; the folder layout simply moved on and the rows did not.

── THE DISK DECIDES ────────────────────────────────────────────────────────
Rather than guessing which copy is the good one, this checks whether each row's
file still exists. A row pointing at a file that is not there describes something
that no longer exists and cannot be re-ingested, so it goes. Nothing is hard-coded
and nothing depends on my reading of your history.

── AND THE PATHS ARE NORMALISED ────────────────────────────────────────────
Surviving rows are rewritten to POSIX form. This matters because you just deployed
the `as_posix()` fix: the next `register_knowledge_docs` run will look for
`knowledge_docs/nda_only/Master_Thesis_2026_Feb.pdf`. A row still holding the
Windows spelling would not match it, and you would get a THIRD copy. Normalising
now is what makes that command idempotent from here on.

End state: 41 documents, one per file on disk, every path matching what the
registrar will look for.
"""

import os
from pathlib import Path

from django.conf import settings

from apps.knowledge_core.models import KnowledgeChunk, KnowledgeDocument

# ── Set to True to apply, or use the .replace() form in the docstring. ──────
APPLY = False

BASE = Path(settings.BASE_DIR) if hasattr(settings, "BASE_DIR") else Path.cwd()


def posix(path: str) -> str:
    return (path or "").replace("\\", "/")


def exists_on_disk(path: str) -> bool:
    """Resolved against the project root, with the separator normalised first."""
    rel = posix(path)
    return (BASE / rel).exists() or Path(rel).exists()


print()
print("=" * 78)
print(f"FINISH CLEANUP — {'APPLYING' if APPLY else 'DRY RUN (nothing will change)'}")
print("=" * 78)
print(f"  database  : {settings.DATABASES['default'].get('HOST')}")
print(f"  index     : {settings.PINECONE_INDEX}")
print(f"  base dir  : {BASE}")

docs = list(KnowledgeDocument.objects.all().order_by("file_path"))
missing = [d for d in docs if not exists_on_disk(d.file_path)]
present = [d for d in docs if exists_on_disk(d.file_path)]

print()
print(f"  documents        : {len(docs)}")
print(f"  file still there : {len(present)}")
print(f"  file is GONE     : {len(missing)}")

if missing:
    print()
    print("=" * 78)
    print("TO DELETE — the file these rows name is not on disk")
    print("=" * 78)
    for d in missing:
        n = KnowledgeChunk.objects.filter(document=d).count()
        print(f"  [{d.disclosure_level:<18}] {n:>4} chunks  {d.file_path}")

# Surviving rows whose stored spelling is not what the registrar will look for.
needs_norm = [d for d in present if d.file_path != posix(d.file_path)]

if needs_norm:
    print()
    print("=" * 78)
    print("TO NORMALISE — so the next register_knowledge_docs run matches them")
    print("=" * 78)
    for d in needs_norm:
        print(f"  {d.file_path}")
        print(f"    -> {posix(d.file_path)}")

drop_chunks = KnowledgeChunk.objects.filter(document__in=[d.id for d in missing])
n_chunks = drop_chunks.count()

print()
print("=" * 78)
print("RESULT")
print("=" * 78)
print(f"  documents after : {len(docs) - len(missing)}")
print(f"  chunks after    : {KnowledgeChunk.objects.count() - n_chunks}")
print(f"  vectors removed : {n_chunks}")

if not missing and not needs_norm:
    print()
    print("  Already clean. Nothing to do.")
elif not APPLY:
    print()
    print("  DRY RUN. Re-run with the .replace() form in this file's docstring to apply.")
else:
    print()
    print("  Applying…")

    # Vectors first, while the chunk rows that name them still exist.
    if missing:
        try:
            from collections import defaultdict

            from pinecone import Pinecone

            pc = Pinecone(api_key=settings.PINECONE_API_KEY)
            index = pc.Index(settings.PINECONE_INDEX)

            by_ns = defaultdict(list)
            for c in drop_chunks.only("vector_id", "namespace"):
                if c.vector_id:
                    by_ns[c.namespace].append(c.vector_id)

            for ns, ids in by_ns.items():
                for i in range(0, len(ids), 500):
                    index.delete(ids=ids[i:i + 500], namespace=ns)
                print(f"    removed {len(ids):>5} vectors from namespace '{ns}'")
        except Exception as exc:  # noqa: BLE001
            print(f"    STOPPED: Pinecone delete failed — {type(exc).__name__}: {exc}")
            print("    No database rows were touched. Fix the connection and re-run.")
            raise SystemExit(1)

        deleted, _ = KnowledgeDocument.objects.filter(
            id__in=[d.id for d in missing]
        ).delete()
        print(f"    removed {len(missing)} documents ({deleted} rows including chunks)")

    for d in needs_norm:
        d.file_path = posix(d.file_path)
        d.save(update_fields=["file_path"])
    if needs_norm:
        print(f"    normalised {len(needs_norm)} paths to POSIX form")

    print()
    print("  Done. To confirm, this should now report every file as already present:")
    print("      python manage.py register_knowledge_docs --dry-run")

print()
