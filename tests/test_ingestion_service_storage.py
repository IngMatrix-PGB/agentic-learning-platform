"""Tests for the PR-008 document-storage integration inside
``IngestionService``: upload-before-DB ordering, duplicate-checksum
short-circuit, and the best-effort compensating delete when the DB insert
fails after a successful upload. Fakes only — no real Postgres, no real S3
(the checksum-dedup/isolation invariants themselves remain covered by the
existing DB-backed tests in test_documents_endpoint.py /
test_corpus_isolation.py, which are unaffected by this change).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from agentic_learning_platform.application.ports.document_parser_port import (
    ExtractedDocument,
    ExtractedPage,
    IDocumentParserPort,
)
from agentic_learning_platform.application.ports.document_storage_port import (
    IDocumentStoragePort,
)
from agentic_learning_platform.application.ports.embedding_port import IEmbeddingPort
from agentic_learning_platform.application.ports.vector_store_port import IVectorStorePort
from agentic_learning_platform.application.services.ingestion_service import IngestionService
from agentic_learning_platform.domain.models import (
    DocumentChunk,
    RequestContext,
    SearchResult,
    SourceDocument,
)

_PDF_BYTES = b"%PDF-1.4 fake pdf content"


class _FakeParserPort(IDocumentParserPort):
    async def extract(self, content: bytes, *, filename: str) -> ExtractedDocument:
        return ExtractedDocument(pages=[ExtractedPage(page_number=1, text="some extracted text")])


class _FakeEmbeddingPort(IEmbeddingPort):
    async def embed_text(self, text: str) -> list[float]:
        return [0.1]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] for _ in texts]

    def get_dimension(self) -> int:
        return 1

    def get_model_name(self) -> str:
        return "fake"


@dataclass
class _FakeVectorStorePort(IVectorStorePort):
    existing_by_checksum: SourceDocument | None = None
    insert_calls: list[SourceDocument] = field(default_factory=list)
    raise_on_insert: bool = False

    async def find_by_checksum(
        self, checksum_sha256: str, *, organization_id: str, course_id: str
    ) -> SourceDocument | None:
        return self.existing_by_checksum

    async def insert_document(
        self,
        document: SourceDocument,
        chunks_with_embeddings: Sequence[tuple[DocumentChunk, list[float]]],
    ) -> None:
        if self.raise_on_insert:
            raise RuntimeError("simulated DB failure")
        self.insert_calls.append(document)

    async def search(
        self, query_embedding: list[float], *, organization_id: str, course_id: str, top_k: int
    ) -> list[SearchResult]:
        raise NotImplementedError("not exercised by these tests")


@dataclass
class _FakeDocumentStoragePort(IDocumentStoragePort):
    upload_calls: list[str] = field(default_factory=list)
    delete_calls: list[str] = field(default_factory=list)
    raise_on_upload: bool = False
    raise_on_delete: bool = False

    async def upload(self, content: bytes, *, key: str, content_type: str) -> None:
        if self.raise_on_upload:
            raise RuntimeError("simulated S3 upload failure")
        self.upload_calls.append(key)

    async def delete(self, key: str) -> None:
        if self.raise_on_delete:
            raise RuntimeError("simulated S3 delete failure")
        self.delete_calls.append(key)


def _context() -> RequestContext:
    return RequestContext(organization_id="org-a", course_id="course-a", user_id="user-1")


def _service(
    vector_store: _FakeVectorStorePort, storage: _FakeDocumentStoragePort
) -> IngestionService:
    return IngestionService(
        _FakeParserPort(),
        _FakeEmbeddingPort(),
        vector_store,
        storage,
        max_upload_size_mb=20,
        chunk_max_chars=1200,
    )


async def test_duplicate_checksum_never_uploads_to_storage() -> None:
    existing = SourceDocument(
        id=uuid.uuid4(),
        organization_id="org-a",
        course_id="course-a",
        source_name="manual.pdf",
        checksum_sha256="irrelevant",
        mime_type="application/pdf",
        file_size=10,
        page_count=1,
        processing_status="completed",
        uploaded_at=datetime.now(UTC),
    )
    vector_store = _FakeVectorStorePort(existing_by_checksum=existing)
    storage = _FakeDocumentStoragePort()

    outcome = await _service(vector_store, storage).ingest(
        _PDF_BYTES, filename="manual.pdf", mime_type="application/pdf", context=_context()
    )

    assert outcome.already_existed is True
    assert storage.upload_calls == []


async def test_successful_ingestion_uploads_before_inserting() -> None:
    vector_store = _FakeVectorStorePort()
    storage = _FakeDocumentStoragePort()

    outcome = await _service(vector_store, storage).ingest(
        _PDF_BYTES, filename="manual.pdf", mime_type="application/pdf", context=_context()
    )

    assert outcome.already_existed is False
    assert len(storage.upload_calls) == 1
    assert len(vector_store.insert_calls) == 1
    assert storage.upload_calls[0] == (
        f"org/org-a/courses/course-a/documents/{outcome.document_id}/source.pdf"
    )


async def test_storage_upload_failure_prevents_db_persistence() -> None:
    vector_store = _FakeVectorStorePort()
    storage = _FakeDocumentStoragePort(raise_on_upload=True)

    with pytest.raises(RuntimeError, match="simulated S3 upload failure"):
        await _service(vector_store, storage).ingest(
            _PDF_BYTES, filename="manual.pdf", mime_type="application/pdf", context=_context()
        )

    assert vector_store.insert_calls == []


async def test_db_failure_after_upload_triggers_a_compensating_delete() -> None:
    vector_store = _FakeVectorStorePort(raise_on_insert=True)
    storage = _FakeDocumentStoragePort()

    with pytest.raises(RuntimeError, match="simulated DB failure"):
        await _service(vector_store, storage).ingest(
            _PDF_BYTES, filename="manual.pdf", mime_type="application/pdf", context=_context()
        )

    assert len(storage.upload_calls) == 1
    assert storage.delete_calls == storage.upload_calls


async def test_a_failed_compensating_delete_does_not_replace_the_original_exception() -> None:
    vector_store = _FakeVectorStorePort(raise_on_insert=True)
    storage = _FakeDocumentStoragePort(raise_on_delete=True)

    with pytest.raises(RuntimeError, match="simulated DB failure"):
        await _service(vector_store, storage).ingest(
            _PDF_BYTES, filename="manual.pdf", mime_type="application/pdf", context=_context()
        )
