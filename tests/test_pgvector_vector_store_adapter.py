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


def _zero_vector(dimension: int) -> list[float]:
    return [0.0] * dimension


def _make_document(*, checksum: str) -> SourceDocument:
    return SourceDocument(
        id=uuid4(),
        source_name="test.pdf",
        checksum_sha256=checksum,
        mime_type="application/pdf",
        file_size=123,
        page_count=2,
        processing_status="completed",
        uploaded_at=datetime.now(UTC),
    )


def _make_chunk(
    *, document_id: UUID, page_number: int, chunk_index: int, content: str
) -> DocumentChunk:
    return DocumentChunk(
        id=uuid4(),
        document_id=document_id,
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

        results = await adapter.search(target_embedding, top_k=1)

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

        found = await adapter.find_by_checksum(checksum)

        assert found is not None
        assert found.id == document.id
        assert found.page_count == 2
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM source_documents WHERE id = $1", document.id)


async def test_find_by_checksum_returns_none_when_absent(pool: asyncpg.Pool) -> None:
    adapter = PgVectorStoreAdapter(pool)

    found = await adapter.find_by_checksum(f"never-inserted-{uuid4()}")

    assert found is None
