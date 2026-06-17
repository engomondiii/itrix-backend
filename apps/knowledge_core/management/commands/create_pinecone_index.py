"""
``python manage.py create_pinecone_index``

Creates the Pinecone serverless index used by the Knowledge Core, using the settings from
your ``.env``:

* name      ← ``PINECONE_INDEX``            (e.g. itrix-knowledge-core)
* dimension ← derived from the embedding model (text-embedding-3-small → 1536)
* metric    ← cosine
* cloud     ← ``PINECONE_CLOUD``            (e.g. aws)
* region    ← ``PINECONE_REGION``           (e.g. us-east-1)

It is idempotent: if the index already exists it reports that and does nothing. Use
``--wait`` (default on) to block until the index is ready to receive vectors.

Requires a real ``PINECONE_API_KEY``. This does NOT require ``ENABLE_AI_ENGINE=True`` — you
can create the index first, then flip the flag and re-ingest.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create the Pinecone index defined by PINECONE_INDEX (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--metric", default="cosine", help="Distance metric (default: cosine)."
        )
        parser.add_argument(
            "--no-wait",
            action="store_false",
            dest="wait",
            help="Don't wait for the index to become ready.",
        )
        parser.add_argument(
            "--dimension",
            type=int,
            default=None,
            help="Override the vector dimension (default: derived from the embedding model).",
        )

    def handle(self, *args, **opts):
        api_key = settings.PINECONE_API_KEY
        if not api_key:
            raise CommandError("PINECONE_API_KEY is not set in your environment / .env.")

        name = settings.PINECONE_INDEX
        cloud = getattr(settings, "PINECONE_CLOUD", "aws")
        region = getattr(settings, "PINECONE_REGION", "us-east-1")
        metric = opts["metric"]

        # Derive the dimension from the embedder unless explicitly overridden.
        if opts["dimension"]:
            dimension = opts["dimension"]
        else:
            from apps.knowledge_core.services.embedder import embedding_dimension

            dimension = embedding_dimension()

        try:
            from pinecone import Pinecone, ServerlessSpec
        except ImportError as exc:  # pragma: no cover
            raise CommandError(
                "The 'pinecone' package is not installed. `pip install -r requirements.txt`."
            ) from exc

        pc = Pinecone(api_key=api_key)

        existing = [i["name"] for i in pc.list_indexes()]
        if name in existing:
            self.stdout.write(
                self.style.WARNING(f"Index '{name}' already exists — nothing to do.")
            )
            self._print_stats(pc, name)
            return

        self.stdout.write(
            f"Creating index '{name}' (dim={dimension}, metric={metric}, {cloud}/{region})…"
        )
        try:
            pc.create_index(
                name=name,
                dimension=dimension,
                metric=metric,
                spec=ServerlessSpec(cloud=cloud, region=region),
            )
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Failed to create index: {exc}") from exc

        if opts["wait"]:
            self.stdout.write("Waiting for the index to become ready…")
            for _ in range(60):
                try:
                    desc = pc.describe_index(name)
                    ready = desc.get("status", {}).get("ready") if isinstance(desc, dict) else getattr(desc.status, "ready", False)
                    if ready:
                        break
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(2)

        self.stdout.write(self.style.SUCCESS(f"✓ Index '{name}' created."))
        self._print_stats(pc, name)
        self.stdout.write(
            "\nNext: set ENABLE_AI_ENGINE=True and run "
            "`python manage.py reingest_namespace --namespace <ns>` for each namespace."
        )

    def _print_stats(self, pc, name):
        try:
            stats = pc.Index(name).describe_index_stats()
            self.stdout.write(f"  index stats: {stats}")
        except Exception:  # noqa: BLE001
            pass
