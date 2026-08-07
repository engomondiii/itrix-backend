"""
Undo the ingestion run of 2026-08-07 and keep the original one.

    python manage.py shell -c "exec(open('revert_last_ingestion.py').read())"

DRY RUN BY DEFAULT — prints the plan and changes nothing. Set APPLY = True below
and run it again to actually apply.

── WHAT THIS DOES ──────────────────────────────────────────────────────────
Today's run registered every file a SECOND time, because it ran on Windows and
the registrar keys documents on the raw string form of their path:

    Windows   knowledge_docs\\public\\x.md
    Linux     knowledge_docs/public/x.md

Different strings, so nothing matched and a duplicate row was created for each
file — with its own UUID and therefore its own full set of Pinecone vectors.

This removes ONLY today's copies. It keeps:

  * every document from the original (Linux/Railway) ingestion, untouched
  * any file that has no earlier copy at all — which is exactly the new
    `itrix_company_overview_public.md`, since it did not exist before today

So the end state is: your original ingestion, plus the one new itriX document.
Nothing is re-embedded and nothing is re-uploaded.

── HOW A ROW IS CLASSIFIED ─────────────────────────────────────────────────
By the separator in its stored path. A backslash means it was written by a
Windows run — today's. That is a reliable marker here because the original
ingestion ran in the Railway container, where paths cannot contain backslashes.

A file with only ONE row is always kept, whatever its separator. That is what
protects the new document.

── ORDER MATTERS ───────────────────────────────────────────────────────────
Vectors are deleted BEFORE the database rows. The vector id is
`f"{document.id}:{chunk.index}"` and the only record of it is the chunk row, so
deleting rows first would leave the vectors permanently unreachable — with
nothing left that knows their ids.
"""

from collections import defaultdict

from django.conf import settings

from apps.knowledge_core.models import KnowledgeChunk, KnowledgeDocument

# ── Set to True to apply. Read the dry run first. ───────────────────────────
APPLY = False


def norm(path: str) -> str:
    """Both spellings of one file collapse to the same key."""
    return (path or "").replace("\\", "/").lower()


def is_from_todays_run(doc) -> bool:
    """A backslash in the stored path means a Windows run — i.e. today's."""
    return "\\" in (doc.file_path or "")


print()
print("=" * 78)
print(f"REVERT — {'APPLYING' if APPLY else 'DRY RUN (nothing will change)'}")
print("=" * 78)
print(f"  database : {settings.DATABASES['default'].get('HOST')}")
print(f"  index    : {settings.PINECONE_INDEX}")

groups = defaultdict(list)
for doc in KnowledgeDocument.objects.all().order_by("created_at"):
    groups[norm(doc.file_path)].append(doc)

to_delete = []
kept_new = []
kept_original = 0

for key, rows in groups.items():
    if len(rows) == 1:
        # No earlier copy. Genuinely new — keep it whatever its separator.
        if is_from_todays_run(rows[0]):
            kept_new.append(rows[0])
        else:
            kept_original += 1
        continue

    # Duplicated. Drop today's copies, keep the originals.
    todays = [r for r in rows if is_from_todays_run(r)]
    originals = [r for r in rows if not is_from_todays_run(r)]

    if not originals:
        # Every copy is from today — keep the newest, drop the rest.
        todays.sort(key=lambda r: r.created_at)
        to_delete.extend(todays[:-1])
        kept_new.append(todays[-1])
    else:
        to_delete.extend(todays)
        kept_original += len(originals)

print()
print("=" * 78)
print("PLAN")
print("=" * 78)
print(f"  documents now              : {KnowledgeDocument.objects.count()}")
print(f"  distinct files             : {len(groups)}")
print()
print(f"  KEEP  original ingestion   : {kept_original}")
print(f"  KEEP  new (no earlier copy): {len(kept_new)}")
for d in kept_new:
    print(f"          + {d.disclosure_level:<18} {d.title}")
print()
print(f"  DELETE today's duplicates  : {len(to_delete)}")

drop_chunks = KnowledgeChunk.objects.filter(document__in=[d.id for d in to_delete])
n_chunks = drop_chunks.count()
print(f"  chunks / vectors to remove : {n_chunks}")
print()
print(f"  documents after            : {KnowledgeDocument.objects.count() - len(to_delete)}")
print(f"  chunks after               : {KnowledgeChunk.objects.count() - n_chunks}")

if not to_delete:
    print()
    print("  Nothing to revert.")
elif not APPLY:
    print()
    print("  DRY RUN. Set APPLY = True at the top of this file and re-run to apply.")
else:
    print()
    print("  Applying…")

    # Vectors first — see the note at the top of this file.
    try:
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
        id__in=[d.id for d in to_delete]
    ).delete()
    print(f"    removed {len(to_delete)} documents ({deleted} rows including chunks)")

    print()
    print("  Done. Re-run pinecone_audit.py to confirm each file appears once.")

print()
