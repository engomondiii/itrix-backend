"""
``python manage.py seed_personas``

Seed the persona registry from ``apps/personas/fixtures/personas_60.json``, which is
generated from the 60-persona target-account workbook (12 accounts x 5 functional
families).

IDEMPOTENT: keyed on ``persona_id`` / ``pitch_room_id`` via update_or_create, so
re-running refreshes the registry rather than duplicating it. That matters because the
workbook is a living document — re-seeding after a research pass must be safe.

    --dry-run   report what would change without writing
    --file      seed from a different fixture
    --prune     delete personas that are no longer in the fixture (off by default,
                because deleting a persona orphans any Lead pointing at it)
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.personas.models import Persona, PitchRoom

DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "personas_60.json"

# Fields copied straight from the fixture onto the Persona row.
_PERSONA_FIELDS = (
    "company",
    "department",
    "primary_persona",
    "functional_family",
    "pitch_archetype",
    "buying_role",
    "decision_lens",
    "department_mandate",
    "trigger_event",
    "primary_kpi",
    "supporting_kpis",
    "workload_environment",
    "boundary_waste_hypothesis",
    "desired_gain",
    "likely_champion",
    "likely_blocker",
    "likely_objection",
    "response_angle",
    "first_value_artifact",
    "personalized_cta",
    "commercial_route",
    "product_route",
    "disclosure_ceiling",
    "priority",
    "validation_status",
    "department_confidence",
)


class Command(BaseCommand):
    help = "Seed the target-account persona registry (60 personas + pitch rooms)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report without writing.")
        parser.add_argument("--file", default=str(DEFAULT_FIXTURE), help="Fixture path.")
        parser.add_argument(
            "--prune",
            action="store_true",
            help="Delete personas absent from the fixture (orphans any Lead pointing at them).",
        )

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"Fixture not found: {path}")

        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Fixture is not valid JSON: {exc}") from exc

        if not isinstance(records, list) or not records:
            raise CommandError("Fixture must be a non-empty list of persona objects.")

        dry_run = options["dry_run"]
        created = updated = rooms = 0
        seen_ids: set[str] = set()

        # Validate the whole fixture BEFORE writing any of it. A half-seeded registry is
        # worse than an unseeded one: the matcher would silently prefer whichever
        # personas happened to land first.
        problems = self._validate(records)
        if problems:
            for problem in problems:
                self.stderr.write(self.style.ERROR(f"  {problem}"))
            raise CommandError(f"Fixture failed validation ({len(problems)} problem(s)).")

        with transaction.atomic():
            for record in records:
                persona_id = record["persona_id"]
                seen_ids.add(persona_id)
                defaults = {field: record.get(field) or _default_for(field) for field in _PERSONA_FIELDS}

                if dry_run:
                    exists = Persona.objects.filter(persona_id=persona_id).exists()
                    updated += 1 if exists else 0
                    created += 0 if exists else 1
                    if record.get("pitch_room_id"):
                        rooms += 1
                    continue

                persona, was_created = Persona.objects.update_or_create(
                    persona_id=persona_id, defaults=defaults
                )
                created += 1 if was_created else 0
                updated += 0 if was_created else 1

                room_id = record.get("pitch_room_id")
                if room_id:
                    PitchRoom.objects.update_or_create(
                        pitch_room_id=room_id,
                        defaults={
                            "persona": persona,
                            "title": record.get("pitch_room_title") or "",
                            "slides": record.get("slides") or [],
                            "review_status": record.get("review_status") or "draft",
                        },
                    )
                    rooms += 1

            if options["prune"] and not dry_run:
                stale = Persona.objects.exclude(persona_id__in=seen_ids)
                pruned = stale.count()
                stale.delete()
                self.stdout.write(self.style.WARNING(f"Pruned {pruned} persona(s)."))

            if dry_run:
                transaction.set_rollback(True)

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Personas: {created} created, {updated} updated. Pitch rooms: {rooms}."
            )
        )
        if not dry_run:
            self._report_distribution()

    def _validate(self, records: list[dict]) -> list[str]:
        """Structural checks that must hold before anything is written."""
        problems: list[str] = []
        seen_personas: set[str] = set()
        seen_rooms: set[str] = set()
        valid_families = {choice[0] for choice in Persona._meta.get_field("functional_family").choices}

        for index, record in enumerate(records):
            if not isinstance(record, dict):
                problems.append(f"record {index}: not an object")
                continue
            persona_id = record.get("persona_id")
            if not persona_id:
                problems.append(f"record {index}: missing persona_id")
                continue
            if persona_id in seen_personas:
                problems.append(f"{persona_id}: duplicate persona_id")
            seen_personas.add(persona_id)

            family = record.get("functional_family")
            if family not in valid_families:
                problems.append(f"{persona_id}: unknown functional_family {family!r}")

            room_id = record.get("pitch_room_id")
            if room_id:
                if room_id in seen_rooms:
                    problems.append(f"{persona_id}: duplicate pitch_room_id {room_id}")
                seen_rooms.add(room_id)

            for slide in record.get("slides") or []:
                if not isinstance(slide, dict) or not slide.get("title"):
                    problems.append(f"{persona_id}: malformed slide {slide!r}")
                    break
        return problems

    def _report_distribution(self) -> None:
        from django.db.models import Count

        self.stdout.write("  Distribution by functional family:")
        rows = (
            Persona.objects.values("functional_family")
            .annotate(n=Count("id"))
            .order_by("functional_family")
        )
        for row in rows:
            self.stdout.write(f"    {row['functional_family']:<32} {row['n']}")
        accounts = Persona.objects.values("company").distinct().count()
        self.stdout.write(f"  Strategic accounts: {accounts}")


def _default_for(field: str):
    if field == "supporting_kpis":
        return []
    if field == "priority":
        return 3
    if field == "validation_status":
        return "hypothesis"
    if field == "disclosure_ceiling":
        return "controlled_public"
    return ""
