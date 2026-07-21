"""
ATTACHMENTS ARE NEVER INGESTED INTO THE KNOWLEDGE CORE
(Backend v6.0 §4.6 boundary 2, §8.2, Architecture §13.4).

    Not embedded, not indexed, not cross-served, not used for training or evaluation.
    A test asserts that NO ATTACHMENT-DERIVED TEXT IS REACHABLE THROUGH RETRIEVAL ON ANY
    PLANE.

This is that test. The boundary matters because attachments arrive from unidentified
visitors on a pre-NDA surface: one visitor's confidential architecture document must
never become an answer to another visitor's question.
"""

from __future__ import annotations

import pytest

from apps.attachments.services import intake

pytestmark = pytest.mark.django_db

MARKER = "ZZQX-ATTACHMENT-ONLY-MARKER-7741"


def test_attachment_text_is_not_reachable_through_retrieval(thread):
    """The end-to-end assertion: upload, process, then search for the content."""
    from apps.ai_engine.services.knowledge_retriever import KnowledgeRetriever

    attachment = intake.stage(
        thread=thread, filename="secret.txt",
        data=f"{MARKER} our internal architecture".encode(), declared_mime="text/plain",
    )
    intake.process(attachment)
    attachment.refresh_from_db()
    assert attachment.extraction.has_text, "fixture assumption: text was extracted"

    for context in ("public", "controlled", "nda", "customer_contract", "internal"):
        chunks = KnowledgeRetriever().retrieve(MARKER, top_k=20, context=context)
        blob = " ".join(str(c.get("text", "")) for c in chunks)
        assert MARKER not in blob, f"attachment text was retrievable at context={context}"


def test_no_knowledge_document_row_is_created(thread):
    from apps.knowledge_core.models import KnowledgeDocument

    before = KnowledgeDocument.objects.count()
    attachment = intake.stage(thread=thread, filename="x.txt", data=b"content",
                              declared_mime="text/plain")
    intake.process(attachment)
    assert KnowledgeDocument.objects.count() == before


def test_the_registration_command_refuses_the_blob_store():
    """
    STRUCTURAL. ``register_knowledge_docs`` refuses any root that could hold uploads.

    Asserted on BEHAVIOUR rather than source text: the command legitimately names the
    attachment store in the guard that refuses it, and a substring scan would flag the
    enforcement of the rule as a breach of it.
    """
    import pathlib as _pathlib

    from apps.knowledge_core.management.commands.register_knowledge_docs import (
        assert_not_attachment_store,
    )

    for hostile in ("/srv/itrix/private_blobs/attachments", "/var/data/media", "/x/attachments"):
        with pytest.raises(RuntimeError):
            assert_not_attachment_store(_pathlib.Path(hostile))


def test_the_registration_command_accepts_the_knowledge_docs_tree():
    """The guard must not be so broad it refuses the legitimate root."""
    import pathlib as _pathlib

    from apps.knowledge_core.management.commands.register_knowledge_docs import (
        assert_not_attachment_store,
    )

    assert_not_attachment_store(_pathlib.Path("/srv/itrix/knowledge_docs"))
    assert_not_attachment_store(_pathlib.Path("/srv/itrix/knowledge_docs/public"))


def test_attachments_are_thread_scoped(thread):
    """
    Boundary 3: another subject cannot retrieve it.

    A second thread must not see the first thread's attachments in its context.
    """
    from apps.attachments.services import excerpts
    from apps.conversations.services import threads as thread_svc

    attachment = intake.stage(thread=thread, filename="mine.txt",
                              data=f"{MARKER} mine".encode(), declared_mime="text/plain")
    intake.process(attachment)

    other = thread_svc.create_thread(visitor_session="sess-other")
    items = excerpts.for_context(other, MARKER)
    assert items == []


def test_excerpts_for_the_owning_thread_do_work(thread):
    """The negative tests above must not be passing because nothing works at all."""
    from apps.attachments.services import excerpts

    attachment = intake.stage(thread=thread, filename="mine.txt",
                              data=f"{MARKER} my workload".encode(), declared_mime="text/plain")
    intake.process(attachment)
    items = excerpts.for_context(thread, MARKER)
    assert items and MARKER in items[0]["text"]
