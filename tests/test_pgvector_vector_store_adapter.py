"""Tests for the PostgreSQL + pgvector store adapter, against a real
database — similarity search is exactly what is being validated here, so it
is never mocked.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest

from agentic_learning_platform.config import Settings, get_settings
from agentic_learning_platform.domain.models import DocumentChunk, SourceDocument
from agentic_learning_platform.infrastructure.db.migrations.runner import run_migrations
from agentic_learning_platform.infrastructure.db.pool import close_pool, create_pool
from agentic_learning_platform.infrastructure.vector_store.pgvector_vector_store_adapter import (
    PgVectorStoreAdapter,
)


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
async def pool(settings: Settings) -> AsyncIterator[asyncpg.Pool]:
    await run_migrations(settings)
    db_pool = await create_pool(settings)
    yield db_pool
    await close_pool(db_pool)


TEST_ORGANIZATION_ID = "org-test"
TEST_COURSE_ID = "course-test"


def _zero_vector(dimension: int) -> list[float]:
    return [0.0] * dimension


def _make_document(
    *,
    checksum: str,
    organization_id: str = TEST_ORGANIZATION_ID,
    course_id: str = TEST_COURSE_ID,
) -> SourceDocument:
    return SourceDocument(
        id=uuid4(),
        organization_id=organization_id,
        course_id=course_id,
        source_name="test.pdf",
        checksum_sha256=checksum,
        mime_type="application/pdf",
        file_size=123,
        page_count=2,
        processing_status="completed",
        uploaded_at=datetime.now(UTC),
    )


def _make_chunk(
    *,
    document_id: UUID,
    page_number: int,
    chunk_index: int,
    content: str,
    organization_id: str = TEST_ORGANIZATION_ID,
    course_id: str = TEST_COURSE_ID,
) -> DocumentChunk:
    return DocumentChunk(
        id=uuid4(),
        document_id=document_id,
        organization_id=organization_id,
        course_id=course_id,
        source_name="test.pdf",
        page_number=page_number,
        chunk_index=chunk_index,
        content=content,
        created_at=datetime.now(UTC),
    )


async def test_search_returns_the_most_similar_chunk_with_its_score(
    pool: asyncpg.Pool, settings: Settings
) -> None:
    adapter = PgVectorStoreAdapter(pool)
    document = _make_document(checksum=f"test-{uuid4()}")
    dim = settings.embedding_dimension

    target_embedding = [1.0] + [0.0] * (dim - 1)
    other_embedding = [0.0] * (dim - 1) + [1.0]

    chunk_target = _make_chunk(
        document_id=document.id, page_number=1, chunk_index=0, content="contenido relevante"
    )
    chunk_other = _make_chunk(
        document_id=document.id, page_number=2, chunk_index=1, content="contenido irrelevante"
    )

    try:
        await adapter.insert_document(
            document, [(chunk_target, target_embedding), (chunk_other, other_embedding)]
        )

        results = await adapter.search(
            target_embedding,
            organization_id=TEST_ORGANIZATION_ID,
            course_id=TEST_COURSE_ID,
            top_k=1,
        )

        assert len(results) == 1
        assert results[0].chunk_id == chunk_target.id
        assert results[0].page_number == 1
        assert results[0].score > 0.9
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM source_documents WHERE id = $1", document.id)


async def test_insert_is_idempotent_by_checksum(pool: asyncpg.Pool, settings: Settings) -> None:
    adapter = PgVectorStoreAdapter(pool)
    checksum = f"test-{uuid4()}"
    document = _make_document(checksum=checksum)
    embedding = _zero_vector(settings.embedding_dimension)
    chunk = _make_chunk(document_id=document.id, page_number=1, chunk_index=0, content="contenido")

    try:
        await adapter.insert_document(document, [(chunk, embedding)])

        found = await adapter.find_by_checksum(
            checksum, organization_id=TEST_ORGANIZATION_ID, course_id=TEST_COURSE_ID
        )

        assert found is not None
        assert found.id == document.id
        assert found.page_count == 2
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM source_documents WHERE id = $1", document.id)


async def test_find_by_checksum_returns_none_when_absent(pool: asyncpg.Pool) -> None:
    adapter = PgVectorStoreAdapter(pool)

    found = await adapter.find_by_checksum(
        f"never-inserted-{uuid4()}",
        organization_id=TEST_ORGANIZATION_ID,
        course_id=TEST_COURSE_ID,
    )

    assert found is None


async def test_search_only_returns_chunks_within_the_same_organization_and_course(
    pool: asyncpg.Pool, settings: Settings
) -> None:
    """Unit-level proof that the adapter's own SQL scopes retrieval — the
    HTTP-level adversarial equivalent lives in tests/test_corpus_isolation.py.
    """
    adapter = PgVectorStoreAdapter(pool)
    embedding = _zero_vector(settings.embedding_dimension)

    doc_a = _make_document(
        checksum=f"test-{uuid4()}", organization_id="org-A", course_id="course-A"
    )
    doc_b = _make_document(
        checksum=f"test-{uuid4()}", organization_id="org-A", course_id="course-B"
    )
    chunk_a = _make_chunk(
        document_id=doc_a.id,
        page_number=1,
        chunk_index=0,
        content="contenido identico",
        organization_id="org-A",
        course_id="course-A",
    )
    chunk_b = _make_chunk(
        document_id=doc_b.id,
        page_number=1,
        chunk_index=0,
        content="contenido identico",
        organization_id="org-A",
        course_id="course-B",
    )

    try:
        await adapter.insert_document(doc_a, [(chunk_a, embedding)])
        await adapter.insert_document(doc_b, [(chunk_b, embedding)])

        results = await adapter.search(
            embedding, organization_id="org-A", course_id="course-A", top_k=10
        )

        chunk_ids = {r.chunk_id for r in results}
        assert chunk_a.id in chunk_ids
        assert chunk_b.id not in chunk_ids
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM source_documents WHERE id = ANY($1::uuid[])",
                [doc_a.id, doc_b.id],
            )


async def test_insert_document_rejects_a_chunk_scoped_to_a_different_course_than_its_document(
    pool: asyncpg.Pool, settings: Settings
) -> None:
    """Adversarial: PostgreSQL itself must refuse a chunk whose scope
    doesn't match its parent document's — via the composite FK
    `document_chunks (document_id, organization_id, course_id)` ->
    `source_documents (id, organization_id, course_id)` (migration 002) —
    not only via application code discipline (`insert_document` being the
    only writer). Real PostgreSQL, no mocks."""
    adapter = PgVectorStoreAdapter(pool)
    embedding = _zero_vector(settings.embedding_dimension)

    document = _make_document(
        checksum=f"test-{uuid4()}", organization_id="org-A", course_id="course-A"
    )
    mismatched_chunk = _make_chunk(
        document_id=document.id,
        page_number=1,
        chunk_index=0,
        content="contenido",
        organization_id="org-A",
        course_id="course-B",  # deliberately inconsistent with the document above
    )

    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await adapter.insert_document(document, [(mismatched_chunk, embedding)])

    # insert_document runs both INSERTs in one transaction — the violation
    # must roll back the whole thing, not leave an orphaned document row.
    found = await adapter.find_by_checksum(
        document.checksum_sha256, organization_id="org-A", course_id="course-A"
    )
    assert found is None


async def test_insert_document_accepts_a_chunk_with_scope_consistent_with_its_document(
    pool: asyncpg.Pool, settings: Settings
) -> None:
    adapter = PgVectorStoreAdapter(pool)
    embedding = _zero_vector(settings.embedding_dimension)

    document = _make_document(
        checksum=f"test-{uuid4()}", organization_id="org-A", course_id="course-A"
    )
    chunk = _make_chunk(
        document_id=document.id,
        page_number=1,
        chunk_index=0,
        content="contenido",
        organization_id="org-A",
        course_id="course-A",
    )

    try:
        await adapter.insert_document(document, [(chunk, embedding)])

        found = await adapter.find_by_checksum(
            document.checksum_sha256, organization_id="org-A", course_id="course-A"
        )
        assert found is not None
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM source_documents WHERE id = $1", document.id)
