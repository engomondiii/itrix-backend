"""
Knowledge Core models.

* ``KnowledgeDocument`` — a registered source document (CRE thesis, FQNM arXiv paper,
  ALPHA product docs, proof materials). Carries the file path (local or ``s3://``),
  Pinecone ``namespace``, ``disclosure_level`` (the five-tier model), and an
  ``ingestion_status`` lifecycle (PENDING → PROCESSING → COMPLETE / FAILED).
* ``KnowledgeChunk`` — a heading-bounded chunk of a document, with the vector id it
  maps to in Pinecone and its disclosure level (inherited from the document, but stored
  per-chunk so retrieval filtering is cheap and exact).
* ``ClaimRecord`` — a tracked factual claim (with disclosure level and optional public
  reference) used by the AI engine's claims discipline / hallucination guard.

Disclosure levels match ``itrix-web/src/constants/disclosure.ts`` and the Knowledge
Core governance: public / controlled_public / nda_only / internal_only / prohibited.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel
from storage.utils import knowledge_doc_upload_path


class DisclosureLevel(models.TextChoices):
    PUBLIC = "public", "Public"
    CONTROLLED_PUBLIC = "controlled_public", "Controlled public"
    NDA_ONLY = "nda_only", "NDA only"
    INTERNAL_ONLY = "internal_only", "Internal only"
    PROHIBITED = "prohibited", "Prohibited"


class IngestionStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PROCESSING = "PROCESSING", "Processing"
    COMPLETE = "COMPLETE", "Complete"
    FAILED = "FAILED", "Failed"


class KnowledgeDocument(BaseModel):
    """A source document registered for ingestion into the Knowledge Core."""

    title = models.CharField(max_length=255)
    # Either a path (local repo path or s3:// URI) OR an uploaded file (admin upload).
    file_path = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        help_text="Local path (e.g. knowledge_docs/public/FQNM.pdf) or s3://bucket/key.",
    )
    uploaded_file = models.FileField(
        upload_to=knowledge_doc_upload_path, blank=True, null=True
    )

    namespace = models.CharField(
        max_length=120,
        db_index=True,
        help_text="Pinecone namespace, e.g. alpha-compute / alpha-core / proofs.",
    )
    disclosure_level = models.CharField(
        max_length=20, choices=DisclosureLevel.choices, default=DisclosureLevel.PUBLIC
    )

    ingestion_status = models.CharField(
        max_length=12,
        choices=IngestionStatus.choices,
        default=IngestionStatus.PENDING,
        db_index=True,
    )
    ingestion_error = models.TextField(blank=True, default="")
    content_hash = models.CharField(max_length=64, blank=True, default="")
    chunk_count = models.PositiveIntegerField(default=0)
    last_ingested_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Knowledge document"
        verbose_name_plural = "Knowledge documents"
        indexes = [models.Index(fields=["namespace", "ingestion_status"])]

    def __str__(self) -> str:
        return f"{self.title} [{self.namespace}/{self.disclosure_level}]"

    @property
    def source_ref(self) -> str:
        """The effective source location: uploaded file path or the file_path string."""
        if self.uploaded_file:
            try:
                return self.uploaded_file.path
            except Exception:  # noqa: BLE001 - storage may be remote
                return self.uploaded_file.name
        return self.file_path


class KnowledgeChunk(BaseModel):
    """One heading-bounded chunk of a document, mapped to a Pinecone vector."""

    document = models.ForeignKey(
        KnowledgeDocument, on_delete=models.CASCADE, related_name="chunks"
    )
    namespace = models.CharField(max_length=120, db_index=True)
    disclosure_level = models.CharField(
        max_length=20, choices=DisclosureLevel.choices, default=DisclosureLevel.PUBLIC
    )
    chunk_index = models.PositiveIntegerField(default=0)
    heading = models.CharField(max_length=512, blank=True, default="")
    text = models.TextField()
    token_estimate = models.PositiveIntegerField(default=0)
    vector_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    embedded = models.BooleanField(default=False)

    class Meta:
        ordering = ["document", "chunk_index"]
        verbose_name = "Knowledge chunk"
        verbose_name_plural = "Knowledge chunks"

    def __str__(self) -> str:
        return f"Chunk {self.chunk_index} of {self.document_id}"


class ClaimRecord(BaseModel):
    """A tracked claim used by the AI engine's claims discipline."""

    document = models.ForeignKey(
        KnowledgeDocument,
        on_delete=models.CASCADE,
        related_name="claims",
        null=True,
        blank=True,
    )
    text = models.TextField()
    disclosure_level = models.CharField(
        max_length=20, choices=DisclosureLevel.choices, default=DisclosureLevel.PUBLIC
    )
    public_reference = models.CharField(max_length=512, blank=True, default="")
    is_prohibited = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Claim({self.disclosure_level}): {self.text[:50]}"
