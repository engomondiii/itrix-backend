"""
``python manage.py journey_migration_report``

A DRY-RUN report of the ENGAGED split, printed for review BEFORE migration 0003 is
applied (Backend v6.0 §Phase 1).

── WHY A SEPARATE REVIEW STEP ───────────────────────────────────────────────
Migration 0003 reconstructs which of ASSESSMENT / POC / INTEGRATION each ENGAGED lead
actually reached, from evidence rather than from the state value. Reconstruction from
evidence is a judgement, and a judgement applied to a live pipeline should be READ BY A
HUMAN before it is committed — not discovered afterwards from a dashboard that suddenly
shows a different distribution.

This command runs the SAME classification logic as the migration and changes nothing.

── WHY IT SELECTS COLUMNS EXPLICITLY ────────────────────────────────────────
This command must run BEFORE ``migrate``, which means the Lead TABLE does not yet have
``journey_number``, ``state_key``, ``persona_id``, ``first_thread_id`` or
``attachment_count`` — but the Lead MODEL already does. A plain ``Lead.objects.filter()``
would emit ``SELECT ... journey_number ...`` and fail with UndefinedColumn.

So every query here names its columns with ``.values()``, restricted to fields that exist
in BOTH the pre- and post-migration schema. That makes the report runnable at the only
moment it is actually useful, and still correct afterwards.

    manage.py journey_migration_report              # summary
    manage.py journey_migration_report --detail     # one line per lead
    manage.py journey_migration_report --json       # machine-readable, for the cockpit
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

ENGAGED = "ENGAGED"
CLIENT = "CLIENT"
NDA_REVIEW = "NDA_REVIEW"
ASSESSMENT = "ASSESSMENT"
POC = "POC"
INTEGRATION = "INTEGRATION"


class Command(BaseCommand):
    help = "Dry-run report of the ENGAGED -> ASSESSMENT/POC/INTEGRATION split."

    def add_arguments(self, parser):
        parser.add_argument("--detail", action="store_true", help="One line per lead.")
        parser.add_argument("--json", action="store_true", help="Machine-readable output.")

    def handle(self, *args, **options):
        from apps.leads.models import Lead

        # Only columns that exist in BOTH schemas. See the module docstring.
        engaged = Lead.objects.filter(journey_state=ENGAGED).values(
            "id", "company", "status"
        )

        rows = []
        for lead in engaged.iterator():
            target, evidence = self._classify(lead)
            rows.append(
                {
                    "lead_id": str(lead["id"]),
                    "company": lead["company"] or "",
                    "status": lead["status"],
                    "from_state": ENGAGED,
                    "to_state": target,
                    "evidence": evidence,
                }
            )

        # count() emits SELECT COUNT(*), which touches no columns, so it is safe either way.
        client_count = Lead.objects.filter(journey_state=CLIENT).count()

        if options["json"]:
            self.stdout.write(
                json.dumps(
                    {
                        "engaged_total": len(rows),
                        "client_to_nda_review": client_count,
                        "distribution": self._distribution(rows),
                        "rows": rows,
                    },
                    indent=2,
                )
            )
            return

        self.stdout.write(self.style.MIGRATE_HEADING("Journey migration report (DRY RUN)"))
        self.stdout.write("")
        self.stdout.write(f"  CLIENT -> NDA_REVIEW          {client_count}")
        self.stdout.write(f"  ENGAGED rows to split         {len(rows)}")
        self.stdout.write("")

        if not rows:
            self.stdout.write(
                self.style.SUCCESS("  Nothing to split. Migration 0003 is a no-op here.")
            )
            return

        self.stdout.write("  Split distribution:")
        for target, count in sorted(self._distribution(rows).items()):
            self.stdout.write(f"    {target:<14} {count}")

        self.stdout.write("")
        self.stdout.write("  Evidence used:")
        evidence_counts: dict[str, int] = {}
        for row in rows:
            evidence_counts[row["evidence"]] = evidence_counts.get(row["evidence"], 0) + 1
        for evidence, count in sorted(evidence_counts.items()):
            self.stdout.write(f"    {evidence:<28} {count}")

        # The one number that deserves a second look: rows with NO evidence land on the
        # ASSESSMENT floor. If that count is high, the split is mostly guesswork and the
        # evidence sources are worth checking before committing.
        floored = evidence_counts.get("none (conservative floor)", 0)
        if floored:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"  {floored} lead(s) have no stage evidence and will land on "
                    f"ASSESSMENT (the conservative floor). Review these before applying."
                )
            )

        if options["detail"]:
            self.stdout.write("")
            self.stdout.write("  Per-lead:")
            for row in rows:
                self.stdout.write(
                    f"    {row['lead_id']}  {row['company'][:28]:<28} "
                    f"{row['status']:<14} -> {row['to_state']:<12} ({row['evidence']})"
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.NOTICE(
                "  Nothing was written. Apply with: manage.py migrate journey 0003"
            )
        )

    @staticmethod
    def _distribution(rows) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in rows:
            out[row["to_state"]] = out.get(row["to_state"], 0) + 1
        return out

    @staticmethod
    def _classify(lead) -> tuple[str, str]:
        """
        Mirror of the migration's classifier, returning the evidence that decided it.

        ``lead`` is a values() DICT, not a model instance — see the module docstring.
        Evidence lookups filter on ``lead_id`` and use ``.exists()``, which emits a
        bare EXISTS query and therefore never selects a column that may not be there.
        """
        lead_id = lead["id"]
        status = (lead.get("status") or "").strip()
        if status in {"Licensed", "Negotiation"}:
            return INTEGRATION, f"lead status = {status}"

        try:
            from apps.pocs.models import PoC

            if PoC.objects.filter(lead_id=lead_id, status="completed").exists():
                return INTEGRATION, "completed PoC record"
            if PoC.objects.filter(lead_id=lead_id).exists():
                return POC, "PoC record"
        except Exception:  # noqa: BLE001
            pass

        try:
            from apps.evaluations.models import Evaluation

            if Evaluation.objects.filter(lead_id=lead_id).exists():
                return ASSESSMENT, "Evaluation record"
        except Exception:  # noqa: BLE001
            pass

        return ASSESSMENT, "none (conservative floor)"
