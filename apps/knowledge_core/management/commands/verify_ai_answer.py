"""Run one read-only visitor AI answer and prove which knowledge sources grounded it.

This command does NOT create a Lead, Thread, Message, journey transition, contact ask,
personalised page, or attachment. It constructs an in-memory public AgentContext and
calls the concierge AI path directly, making it safe for production RAG verification.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.agents.services.concierge import ConciergeAgent
from apps.agents.services.context import AgentContext, PLANE_PUBLIC
from apps.knowledge_core.models import HardFact, KnowledgeChunk


DEFAULT_QUESTION = (
    "What are ALPHA Compute and ALPHA Core, and can ALPHA Compute deploy in "
    "production without ALPHA Core?"
)


def _is_v35_canonical_reference(value: str) -> bool:
    blob = (value or "").replace("\\", "/").lower()
    return (
        "itrix_product_canonical_v3_5" in blob
        or "itrix product canonical v3 5" in blob
    )


class Command(BaseCommand):
    help = "Generate one read-only public concierge answer and print its exact RAG sources."

    def add_arguments(self, parser):
        parser.add_argument("--question", default=DEFAULT_QUESTION)

    def handle(self, *args, **opts):
        question = (opts["question"] or "").strip()
        if not question:
            raise CommandError("--question cannot be empty")

        # Model the actual anonymous visitor state rather than leaving journey metadata
        # blank. This allows governed PUBLIC-SAFE sources to participate in retrieval.
        ctx = AgentContext(
            prompt=question,
            product_route="undetermined",
            tier=4,
            plane=PLANE_PUBLIC,
            context_label="rag_verification",
            extra={
                "message": question,
                "journey_state": "ARRIVED",
                "audience": "general",
            },
        )

        output = ConciergeAgent().run_ai(ctx)
        if not output.used_ai:
            raise CommandError("AI engine did not produce an answer.")

        reply = str((output.payload or {}).get("reply") or "").strip()
        ids = [str(i) for i in (output.chunk_ids or []) if i]

        if not reply:
            raise CommandError("AI returned an empty reply.")
        if not ids:
            raise CommandError(
                "AI answered with ZERO knowledge grounding ids — grounding failed."
            )

        self.stdout.write(self.style.MIGRATE_HEADING("AI answer"))
        self.stdout.write(reply)

        self.stdout.write(self.style.MIGRATE_HEADING("Persistable grounding ids"))
        self.stdout.write(str(ids))

        vector_ids = [chunk_id for chunk_id in ids if not chunk_id.startswith("hard-fact:")]
        hard_fact_ids = [
            chunk_id.split(":", 1)[1]
            for chunk_id in ids
            if chunk_id.startswith("hard-fact:") and ":" in chunk_id
        ]

        rows = {
            row.vector_id: row
            for row in KnowledgeChunk.objects.filter(
                vector_id__in=vector_ids
            ).select_related("document")
        }

        facts = {
            f"hard-fact:{fact.id}": fact
            for fact in HardFact.objects.filter(id__in=hard_fact_ids).select_related(
                "source_document"
            )
        }

        missing = [
            grounding_id
            for grounding_id in ids
            if grounding_id not in rows and grounding_id not in facts
        ]
        if missing:
            raise CommandError(
                f"Retrieved grounding ids are missing from PostgreSQL: {missing}"
            )

        current = 0
        self.stdout.write(self.style.MIGRATE_HEADING("Sources"))

        for grounding_id in ids:
            if grounding_id in facts:
                fact = facts[grounding_id]
                source_document = fact.source_document
                blob = " ".join(
                    [
                        str(fact.source_reference or ""),
                        str(getattr(source_document, "title", "") or ""),
                        str(getattr(source_document, "file_path", "") or ""),
                    ]
                )

                is_current = bool(fact.is_current) and _is_v35_canonical_reference(blob)
                if is_current:
                    current += 1

                marker = " CURRENT-CANONICAL" if is_current else ""
                self.stdout.write(
                    f"  ->{marker} HARD-FACT {fact.key} | "
                    f"{fact.disclosure_level} | "
                    f"{fact.source_reference} | {grounding_id}"
                )
                continue

            row = rows[grounding_id]
            blob = f"{row.document.title} {row.document.file_path}"
            is_current = bool(row.document.is_current) and _is_v35_canonical_reference(
                blob
            )

            if is_current:
                current += 1

            marker = " CURRENT-CANONICAL" if is_current else ""
            self.stdout.write(
                f"  ->{marker} {row.document.title} | {row.namespace} | "
                f"{row.disclosure_level} | {row.heading} | {row.vector_id}"
            )

        if current == 0:
            raise CommandError(
                "AI answer had grounding ids, but none came from the current "
                "v3.5 canonical product source or its authoritative hard facts."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nPASS: AI answered from {len(ids)} grounded source(s); "
                f"{current} current canonical source(s)."
            )
        )
