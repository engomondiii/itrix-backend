"""Print recent agent replies and the exact knowledge chunks persisted with them."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.conversations.models import Message
from apps.knowledge_core.models import KnowledgeChunk


class Command(BaseCommand):
    help = "Audit persisted AI grounding/citations for recent agent messages."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--contains", default="")

    def handle(self, *args, **opts):
        qs = Message.objects.filter(sender_kind="agent").order_by("-created_at")
        if opts["contains"]:
            qs = qs.filter(body__icontains=opts["contains"])
        messages = list(qs[: max(1, opts["limit"])])

        for message in messages:
            ids = [str(i) for i in (message.cited_chunk_ids or []) if i]
            self.stdout.write("\n" + "=" * 78)
            self.stdout.write(f"MESSAGE {message.id}")
            self.stdout.write(" ".join((message.body or "").split())[:700])
            self.stdout.write(f"CITED IDS: {ids}")
            if not ids:
                self.stdout.write(self.style.WARNING("  NO PERSISTED KNOWLEDGE CITATIONS"))
                continue
            chunks = KnowledgeChunk.objects.filter(vector_id__in=ids).select_related("document")
            for chunk in chunks:
                self.stdout.write(
                    f"  -> {chunk.document.title} | {chunk.namespace} | "
                    f"{chunk.disclosure_level} | {chunk.heading} | {chunk.vector_id}"
                )
