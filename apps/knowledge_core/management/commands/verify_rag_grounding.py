"""Operational proof that visitor RAG is returning governed source chunks."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.ai_engine.services.knowledge_retriever import (
    VISITOR_KNOWLEDGE_NAMESPACES,
    KnowledgeRetriever,
)


DEFAULT_QUESTION = (
    "What are ALPHA Compute and ALPHA Core, and can ALPHA Compute deploy in "
    "production without ALPHA Core?"
)


class Command(BaseCommand):
    help = "Verify public RAG grounding and print the exact documents/chunks retrieved."

    def add_arguments(self, parser):
        parser.add_argument("--question", default=DEFAULT_QUESTION)
        parser.add_argument("--top-k", type=int, default=8)

    def handle(self, *args, **opts):
        question = opts["question"]

        chunks = KnowledgeRetriever().retrieve(
            question,
            namespaces=VISITOR_KNOWLEDGE_NAMESPACES,
            top_k=max(1, opts["top_k"]),
            context="public",
            audience="general",
            journey_stage="ARRIVED",
        )

        if not chunks:
            raise CommandError("RAG returned ZERO public knowledge chunks.")

        self.stdout.write(self.style.MIGRATE_HEADING("RAG grounding"))
        self.stdout.write(f"Question: {question}")
        self.stdout.write(f"Chunks: {len(chunks)}")

        canonical = 0
        pinecone = 0
        backends: set[str] = set()

        for i, chunk in enumerate(chunks, 1):
            priority = int(chunk.get("canonical_priority") or 0)
            backend = chunk.get("retrieval_backend") or "unknown"
            backends.add(str(backend))

            if priority >= 90:
                canonical += 1
            if backend == "pinecone":
                pinecone += 1

            self.stdout.write(
                f"\n[{i}] backend={backend} score={chunk.get('score')} "
                f"priority={priority} namespace={chunk.get('namespace')}"
            )
            self.stdout.write(f"    document: {chunk.get('document_title')}")
            self.stdout.write(f"    heading : {chunk.get('heading')}")
            self.stdout.write(f"    chunk id: {chunk.get('chunk_id')}")

            text = " ".join((chunk.get("text") or "").split())
            self.stdout.write(f"    preview : {text[:360]}")

        if canonical == 0:
            raise CommandError("No CANONICAL/CURRENT product source was retrieved.")

        if pinecone == 0:
            backend_text = ", ".join(sorted(backends)) or "unknown"
            self.stdout.write(
                self.style.WARNING(
                    "No returned grounding item came from Pinecone; "
                    f"returned backend(s): {backend_text}."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nPinecone-grounded chunks: {pinecone}/{len(chunks)}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Canonical/current chunks: {canonical}/{len(chunks)}"
            )
        )
