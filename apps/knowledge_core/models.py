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
Core governance: Public / Controlled public / Authorized / Agreement-gated / Private workspace / Role-restricted; PROHIBITED is a separate non-embedding sentinel.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel
from storage.utils import knowledge_doc_upload_path


class DisclosureLevel(models.TextChoices):
    # Six-state disclosure model plus a fail-closed PROHIBITED sentinel.
    PUBLIC = "public", "Public"
    CONTROLLED_PUBLIC = "controlled_public", "Controlled public"
    AUTHORIZED = "authorized", "Authorized"
    NDA_ONLY = "nda_only", "Agreement-gated / NDA"
    CUSTOMER_CONTRACT = "customer_contract", "Private workspace / customer contract"
    INTERNAL_ONLY = "internal_only", "Role-restricted / internal"
    PROHIBITED = "prohibited", "Prohibited — never embed or retrieve"


class SourceAuthority(models.TextChoices):
    AUTHORITATIVE = "authoritative", "Authoritative register / executed record"
    GOVERNING = "governing", "Current approved governing document"
    WORKING = "working", "Working technical document"
    LEGACY = "legacy", "Legacy / superseded material"


class ParaphrasePermission(models.TextChoices):
    NONE = "none", "No external paraphrase"
    SUMMARY = "summary", "Approved summary only"
    APPROVED = "approved", "Approved wording / bounded paraphrase"
    FULL = "full", "Full-source paraphrase within disclosure ceiling"


class TechnologyFamily(models.TextChoices):
    GENERAL = "general", "General / cross-cutting"
    AXIOM = "axiom", "AXIOM"
    CRE = "cre", "CRE"
    FQNM = "fqnm", "FQNM"
    ALPHA_COMPUTE = "alpha_compute", "ALPHA Compute"
    ALPHA_CORE = "alpha_core", "ALPHA Core"
    CROSS_CUTTING = "cross_cutting", "Boundary-aware / cross-cutting"
    ASTOP = "astop", "ASTOP"
    PRISM = "prism", "PRISM"
    AXIOM_TENSOR = "axiom_tensor", "AXIOM-TENSOR"
    QNTA = "qnta", "QNTA"


class KnowledgeEntityType(models.TextChoices):
    PRODUCT = "product", "Product"
    TECHNOLOGY = "technology", "Technology"
    PLATFORM = "platform", "Commercialization platform"
    RESEARCH = "research", "Research"
    GOVERNANCE = "governance", "Governance"
    MIXED = "mixed", "Mixed"


class EvidenceStatus(models.TextChoices):
    MATHEMATICAL = "mathematical", "Mathematical"
    EXPERIMENTAL = "experimental", "Experimental"
    IMPLEMENTED = "implemented", "Implemented"
    VALIDATED = "validated", "Validated"
    VALUE_VERIFIED = "value_verified", "Value-Verified"
    LICENSABLE = "licensable", "Licensable"
    GOVERNANCE = "governance", "Governance / policy"
    MIXED = "mixed", "Mixed"


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
        max_length=24, choices=DisclosureLevel.choices, default=DisclosureLevel.PUBLIC
    )

    # Governing response metadata. Retrieval permission and disclosure permission are
    # deliberately separate: a document can be indexed for an authorized plane while
    # still carrying a narrower approved audience/stage/paraphrase ceiling.
    source_authority = models.CharField(
        max_length=20, choices=SourceAuthority.choices, default=SourceAuthority.WORKING, db_index=True
    )
    is_current = models.BooleanField(default=True, db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    canonical_rule = models.CharField(max_length=512, blank=True, default="")
    approved_audience = models.JSONField(default=list, blank=True)
    allowed_journey_stages = models.JSONField(default=list, blank=True)
    approval_owner = models.CharField(max_length=255, blank=True, default="")
    approval_date = models.DateField(null=True, blank=True)
    review_after = models.DateField(null=True, blank=True)
    permitted_paraphrase = models.CharField(
        max_length=16, choices=ParaphrasePermission.choices, default=ParaphrasePermission.APPROVED
    )
    technology_family = models.CharField(
        max_length=20, choices=TechnologyFamily.choices, default=TechnologyFamily.GENERAL, db_index=True
    )
    # The singular legacy family remains for backwards compatibility. These lists are
    # the canonical representation for combined sources and explicit entity→product
    # relationships used by retrieval/governance.
    technology_families = models.JSONField(default=list, blank=True)
    canonical_entities = models.JSONField(default=list, blank=True)
    related_products = models.JSONField(default=list, blank=True)
    # Claim level ceiling used by orchestration.  0 means metadata has not assigned a
    # special ceiling; the normal journey/disclosure ceiling still applies.
    claim_ceiling = models.PositiveSmallIntegerField(default=0)
    entity_type = models.CharField(max_length=20, choices=KnowledgeEntityType.choices, default=KnowledgeEntityType.MIXED, db_index=True)
    evidence_status = models.CharField(max_length=24, choices=EvidenceStatus.choices, default=EvidenceStatus.MIXED, db_index=True)

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
        max_length=24, choices=DisclosureLevel.choices, default=DisclosureLevel.PUBLIC
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
        max_length=24, choices=DisclosureLevel.choices, default=DisclosureLevel.PUBLIC
    )
    public_reference = models.CharField(max_length=512, blank=True, default="")
    is_prohibited = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Claim({self.disclosure_level}): {self.text[:50]}"


class HardFact(BaseModel):
    """Structured owner-verifiable fact; prose retrieval must not upgrade its status."""

    class Category(models.TextChoices):
        PATENT = "patent", "Patent / IP"
        CORPORATE = "corporate", "Corporate"
        COMMERCIAL = "commercial", "Commercial"
        BENCHMARK = "benchmark", "Benchmark"
        CUSTOMER = "customer", "Customer"
        TRANSACTION = "transaction", "Transaction"

    key = models.SlugField(max_length=160, unique=True)
    category = models.CharField(max_length=24, choices=Category.choices, db_index=True)
    public_statement = models.TextField(blank=True, default="")
    jurisdiction = models.CharField(max_length=80, blank=True, default="")
    internal_reference = models.CharField(max_length=120, blank=True, default="")
    official_application_number = models.CharField(max_length=120, blank=True, default="")
    filing_date = models.DateField(null=True, blank=True)
    publication_status = models.CharField(max_length=120, blank=True, default="")
    prosecution_status = models.CharField(max_length=120, blank=True, default="")
    verified_grant_number = models.CharField(max_length=120, blank=True, default="")
    ownership_assignment = models.CharField(max_length=255, blank=True, default="")
    source_document = models.ForeignKey(
        KnowledgeDocument, on_delete=models.SET_NULL, null=True, blank=True, related_name="hard_facts"
    )
    source_reference = models.CharField(max_length=512, blank=True, default="")
    source_authority = models.CharField(
        max_length=20, choices=SourceAuthority.choices, default=SourceAuthority.AUTHORITATIVE, db_index=True
    )
    is_current = models.BooleanField(default=True, db_index=True)
    disclosure_level = models.CharField(
        max_length=24, choices=DisclosureLevel.choices, default=DisclosureLevel.INTERNAL_ONLY
    )
    approved_audience = models.JSONField(default=list, blank=True)
    claim_ceiling = models.PositiveSmallIntegerField(default=1)
    last_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["category", "key"]


class ContentAuthorization(BaseModel):
    """Explicit per-content authorization, deliberately independent of NDA/account state."""

    class SubjectKind(models.TextChoices):
        CLIENT = "client", "Client"
        LEAD = "lead", "Lead"
        THREAD = "thread", "Thread"

    document = models.ForeignKey(
        KnowledgeDocument, on_delete=models.CASCADE, related_name="content_authorizations"
    )
    subject_kind = models.CharField(max_length=16, choices=SubjectKind.choices, db_index=True)
    subject_id = models.CharField(max_length=64, db_index=True)
    scope = models.CharField(max_length=255, blank=True, default="")
    reason = models.CharField(max_length=512, blank=True, default="")
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="knowledge_authorizations"
    )
    active = models.BooleanField(default=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "subject_kind", "subject_id"],
                name="uniq_knowledge_document_subject_authorization",
            )
        ]


class KnowledgeConflict(BaseModel):
    """Auditable unresolved conflict among equally authoritative applicable sources."""

    query_fingerprint = models.CharField(max_length=64, db_index=True)
    topic = models.CharField(max_length=160, blank=True, default="")
    authority = models.CharField(max_length=20, choices=SourceAuthority.choices)
    document_ids = models.JSONField(default=list, blank=True)
    detail = models.CharField(max_length=1024, blank=True, default="")
    resolved = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]
