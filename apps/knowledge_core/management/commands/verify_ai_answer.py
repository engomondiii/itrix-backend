"""Run one read-only visitor AI answer and prove which knowledge chunks grounded it.

This command does NOT create a Lead, Thread, Message, journey transition, contact ask,
personalised page, or attachment.  It constructs an in-memory public AgentContext and calls
the concierge AI path directly, making it safe for production RAG verification.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.agents.services.concierge import ConciergeAgent
from apps.agents.services.context import AgentContext, PLANE_PUBLIC
from apps.knowledge_core.models import KnowledgeChunk


DEFAULT_QUESTION = (
    "What are ALPHA Compute and ALPHA Core, and can ALPHA Compute deploy in "
    "production without ALPHA Core?"
)


class Command(BaseCommand):
    help = "Generate one read-only public concierge answer and print its exact RAG sources."

    def add_arguments(self, parser):
        parser.add_argument("--question", default=DEFAULT_QUESTION)

    def handle(self, *args, **opts):
        question = (opts["question"] or "").strip()
        if not question:
            raise CommandError("--question cannot be empty")

        ctx = AgentContext(
            prompt=question,
            product_route="general",
            tier=4,
            plane=PLANE_PUBLIC,
            context_label="rag_verification",
            extra={"message": question},
        )
        output = ConciergeAgent().run_ai(ctx)
        if not output.used_ai:
            raise CommandError("AI engine did not produce an answer.")

        reply = str((output.payload or {}).get("reply") or "").strip()
        ids = [str(i) for i in (output.chunk_ids or []) if i]
        if not reply:
            raise CommandError("AI returned an empty reply.")
        if not ids:
            raise CommandError("AI answered with ZERO knowledge chunk ids — grounding failed.")

        self.stdout.write(self.style.MIGRATE_HEADING("AI answer"))
        self.stdout.write(reply)
        self.stdout.write(self.style.MIGRATE_HEADING("Persistable grounding ids"))
        self.stdout.write(str(ids))

        rows = {
            row.vector_id: row
            for row in KnowledgeChunk.objects.filter(vector_id__in=ids).select_related("document")
        }
        missing = [chunk_id for chunk_id in ids if chunk_id not in rows]
        if missing:
            raise CommandError(f"Retrieved chunk ids are missing from PostgreSQL: {missing}")

        current = 0
        self.stdout.write(self.style.MIGRATE_HEADING("Sources"))
        for chunk_id in ids:
            row = rows[chunk_id]
            blob = f"{row.document.title} {row.document.file_path}".lower()
            is_current = (
                "wp_alpha_compute_core_v2.4" in blob
                or "wp alpha compute core v2.4" in blob
                or "itrix_product_canonical_v2_4" in blob
                or "itrix product canonical v2 4" in blob
            )
            if is_current:
                current += 1
            marker = " CURRENT" if is_current else ""
            self.stdout.write(
                f"  ->{marker} {row.document.title} | {row.namespace} | "
                f"{row.disclosure_level} | {row.heading} | {row.vector_id}"
            )

        if current == 0:
            raise CommandError("AI answer had citations, but none came from a current canonical product source.")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nPASS: AI answered from {len(ids)} retrieved chunk(s); "
                f"{current} current canonical product source chunk(s)."
            )
        )
