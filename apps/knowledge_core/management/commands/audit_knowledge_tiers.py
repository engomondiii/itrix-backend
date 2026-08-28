"""
``python manage.py audit_knowledge_tiers [--fix]``

Audit the ``knowledge_docs/`` tree against the FOLDER-IS-THE-DECISION rule
(Backend v7.1 §Phase 1, Architecture v2.8 §13.2).

── WHY THIS EXISTS ─────────────────────────────────────────────────────────
The folder a document sits in IS its disclosure level. That is a good design: it is
visible in a file listing, it survives a database restore, and it cannot be changed by a
prompt. Its weakness is that a file lands in the wrong folder by a single drag, and
nothing complains — the document is then retrievable by everyone the folder authorizes.

Backend v6.0 Phase 1 flagged this as urgent because a set of internal documents were
sitting in ``public/``. That has since been corrected: the master's thesis is in
``nda_only/`` and the pricing policy, the investor data-room list and the kickoff
documents are in ``internal_only/``.

THIS AUDIT FOUND THREE THAT ARE STILL WRONG, all at ``controlled_public`` — the level a
visitor reaches simply by describing their situation:

    itriX_AI_Sales_Engine_Master_Architecture_Flow_Document_v1.0     internal architecture
    itriX_AI_Sales_Engine_MVP_Execution_Milestone_Operations_Command internal delivery plan
    iTrix_Atelier_Indigo_Theme_System_v2                            a RETIRED design system

The first two are internal build documents. They describe how the platform is
constructed, which is not something a visitor who typed one sentence has earned, and the
architecture document in particular describes the governance boundaries themselves.

The third is a different problem and worth naming separately: Atelier Indigo was RETIRED
and is lint-banned in both frontends. It is not a disclosure risk, but a retrieval that
surfaced it would be quoting a design system that no longer exists — which is a
correctness failure rather than a security one, and just as worth removing from the
corpus.

── WHAT --fix DOES, AND WHAT IT REFUSES TO DO ──────────────────────────────
With ``--fix`` it MOVES a mis-tiered file to the correct folder and prints what it did.
It never moves a file to a LOOSER tier: an audit that could relax a boundary would be a
worse tool than no audit. Only tightening is automated; loosening requires a human who
can be asked why.

After a move, re-register and re-embed:

    python manage.py register_knowledge_docs
    python manage.py reingest_namespace --all  # clears stale vectors, then rebuilds current sources

Until re-registration runs, the DATABASE still records the old level. That is why this
command reports the drift between the folder and the ``KnowledgeDocument`` row: the two
disagreeing is its own class of bug, and the one that would keep a document retrievable
after the file had already been moved.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from django.core.management.base import BaseCommand

# Rank order, loosest first. A move is permitted only toward a HIGHER rank.
TIER_RANK: dict[str, int] = {
    "public": 0,
    "controlled_public": 1,
    "nda_only": 2,
    "customer_contract": 3,
    "internal_only": 4,
}

# Filename fragment -> the tier it belongs in, with the reason.
#
# Matched on a lowercased substring so a version bump in the filename does not silently
# stop the rule applying. Deliberately a small, explicit list rather than a heuristic: a
# classifier that guessed would eventually guess a real document into the wrong folder.
MISTIERED: tuple[tuple[str, str, str], ...] = (
    (
        "master_architecture_flow",
        "internal_only",
        "Internal architecture. Describes how the platform and its governance boundaries "
        "are built — not something a visitor earns by describing their situation.",
    ),
    (
        "execution_milestone_operations_command",
        "internal_only",
        "Internal delivery plan: milestones, owners and operational commands. No visitor "
        "audience at any level.",
    ),
    (
        "atelier_indigo",
        "internal_only",
        "A RETIRED design system, lint-banned in both frontends. Not a disclosure risk, "
        "but a retrieval that surfaced it would quote a design system that no longer "
        "exists — a correctness failure worth removing from the corpus.",
    ),
)


class Command(BaseCommand):
    help = "Audit knowledge_docs/ tiers against the folder-is-the-decision rule."

    def add_arguments(self, parser):
        parser.add_argument("--base", type=str, default="knowledge_docs")
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Move mis-tiered files. Only ever toward a stricter tier.",
        )

    def handle(self, *args, **options):
        base = Path(options["base"])
        if not base.is_dir():
            self.stderr.write(self.style.ERROR(f"No such directory: {base}"))
            return

        findings = 0
        moved = 0

        for tier_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            tier = tier_dir.name
            if tier not in TIER_RANK:
                self.stdout.write(
                    self.style.WARNING(
                        f"  ?  {tier}/ is not a known disclosure tier. "
                        "The folder name IS the decision, so an unknown folder means "
                        "nothing can be decided about its contents."
                    )
                )
                continue

            for path in sorted(tier_dir.iterdir()):
                if not path.is_file():
                    continue
                name = path.name.lower().replace(" ", "_").replace("-", "_")

                for fragment, target, reason in MISTIERED:
                    if fragment not in name:
                        continue
                    if TIER_RANK[target] <= TIER_RANK[tier]:
                        # Already at least as strict as required. Nothing to do.
                        continue

                    findings += 1
                    self.stdout.write(
                        self.style.ERROR(f"  MIS-TIERED  {tier}/{path.name}")
                    )
                    self.stdout.write(f"              should be: {target}/")
                    self.stdout.write(f"              why: {reason}")

                    if options["fix"]:
                        dest_dir = base / target
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        dest = dest_dir / path.name
                        if dest.exists():
                            self.stdout.write(
                                self.style.WARNING(
                                    f"              SKIPPED: {dest} already exists. "
                                    "Resolve by hand rather than overwriting — one of the "
                                    "two copies may have been edited."
                                )
                            )
                        else:
                            shutil.move(str(path), str(dest))
                            moved += 1
                            self.stdout.write(
                                self.style.SUCCESS(f"              MOVED -> {target}/{path.name}")
                            )
                    break

        self._report_db_drift(base)

        self.stdout.write("")
        if findings == 0:
            self.stdout.write(self.style.SUCCESS("  No mis-tiered documents found."))
        elif options["fix"]:
            self.stdout.write(
                self.style.SUCCESS(f"  {moved} of {findings} finding(s) moved.")
            )
            self.stdout.write(
                "  NOW RE-REGISTER, or the database still records the old level:\n"
                "    python manage.py register_knowledge_docs"
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  {findings} finding(s). Re-run with --fix to move them, then "
                    "register_knowledge_docs."
                )
            )

    def _report_db_drift(self, base: Path) -> None:
        """
        Where the FOLDER and the ``KnowledgeDocument`` row disagree.

        Its own class of bug, and the one that keeps a document retrievable after the file
        has already been moved: retrieval filters on the database column, not on the path.
        """
        try:
            from apps.knowledge_core.models import KnowledgeDocument
        except Exception:  # noqa: BLE001 - the command is useful without a database
            return

        drift = 0
        try:
            documents = list(KnowledgeDocument.objects.all().only("id", "title", "disclosure_level", "file_path"))
        except Exception:  # noqa: BLE001
            return

        for doc in documents:
            source = getattr(doc, "file_path", "") or ""
            if not source:
                continue
            parts = Path(source).parts
            folder = next((p for p in parts if p in TIER_RANK), None)
            if folder is None or folder == doc.disclosure_level:
                continue
            drift += 1
            self.stdout.write(
                self.style.ERROR(
                    f"  DB DRIFT    {doc.title[:48]}\n"
                    f"              folder says {folder}, database says {doc.disclosure_level}"
                )
            )

        if drift:
            self.stdout.write(
                self.style.WARNING(
                    f"  {drift} document(s) where the folder and the database disagree. "
                    "Retrieval filters on the DATABASE, so the looser of the two is what "
                    "is actually in force. Run register_knowledge_docs."
                )
            )
