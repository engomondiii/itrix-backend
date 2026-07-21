#!/usr/bin/env python
"""
Verifiable attachment retention purge (Backend v6.0 §1.1).

    python scripts/purge_attachments.py --report      what is due, change nothing
    python scripts/purge_attachments.py --sweep       purge everything due
    python scripts/purge_attachments.py --verify      prove past purges are complete

── WHY A SCRIPT AS WELL AS A TASK ───────────────────────────────────────────
The nightly sweep runs in Celery. This script exists so retention can be run and AUDITED
by a human without a broker — during an incident, during a migration, or when somebody
has to answer "prove this customer's pre-NDA document is gone."

``--verify`` is the one that matters. It re-checks that for every purged attachment the
blob, the extraction AND the excerpts are all actually absent. A purge nobody can verify
is a claim, not a control.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "itrix.settings.development")

import django  # noqa: E402

django.setup()

from apps.attachments.models import Attachment  # noqa: E402
from apps.attachments.services import retention  # noqa: E402


def report() -> int:
    due = retention.expired()
    total = due.count()
    print(f"{total} attachment(s) past their retention window\n")
    for attachment in due[:50]:
        tier = "pre-NDA" if attachment.pre_nda else "post-NDA"
        print(f"  {attachment.id}  [{tier}]  {attachment.filename[:50]}")
        print(f"      expired {attachment.retention_expires_at:%Y-%m-%d}  "
              f"thread={attachment.thread_id}")
    if total > 50:
        print(f"  ... and {total - 50} more")
    return 0


def sweep() -> int:
    summary = retention.sweep()
    print(f"Purged {summary['purged']}, failed {summary['failed']}.")
    return 1 if summary["failed"] else 0


def verify() -> int:
    """Re-check every purged attachment. Non-zero exit on any incomplete purge."""
    purged = Attachment.objects.filter(purged_at__isnull=False)
    total = purged.count()
    incomplete = []
    for attachment in purged.iterator():
        result = retention.verify_purged(attachment)
        if not result["verified"]:
            incomplete.append(result)

    print(f"Checked {total} purged attachment(s).")
    if not incomplete:
        print("  All purges verified: blob, extraction and excerpts absent.")
        return 0

    print(f"  {len(incomplete)} INCOMPLETE purge(s):")
    for row in incomplete:
        missing = [k for k in ("blob_gone", "extraction_gone", "excerpts_gone") if not row[k]]
        print(f"    {row['attachment_id']}: still present -> {', '.join(missing)}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Attachment retention purge.")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    if args.report:
        return report()
    if args.sweep:
        return sweep()
    if args.verify:
        return verify()
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
