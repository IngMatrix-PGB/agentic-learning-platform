"""Tests for the PostgreSQL full-text search (lexical) adapter, against a
real database — same philosophy as
`tests/test_pgvector_vector_store_adapter.py`: the ranking/scoping being
validated here is never mocked.
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
from agentic_learning_platform.infrastructure.lexical_search.postgres_fts_adapter import (
    PostgresLexicalSearchAdapter,
)
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


TEST_ORGANIZATION_ID = "org-lexical-test"
TEST_COURSE_ID = "course-lexical-test"


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
        page_count=1,
        processing_status="completed",
        uploaded_at=datetime.now(UTC),
    )


def _make_chunk(
    *,
    document_id: UUID,
    content: str,
    chunk_index: int = 0,
    organization_id: str = TEST_ORGANIZATION_ID,
    course_id: str = TEST_COURSE_ID,
) -> DocumentChunk:
    return DocumentChunk(
        id=uuid4(),
        document_id=document_id,
        organization_id=organization_id,
        course_id=course_id,
        source_name="test.pdf",
        page_number=1,
        chunk_index=chunk_index,
        content=content,
        created_at=datetime.now(UTC),
    )


async def _insert(
    pool: asyncpg.Pool, settings: Settings, document: SourceDocument, content: str
) -> DocumentChunk:
    vector_adapter = PgVectorStoreAdapter(pool)
    chunk = _make_chunk(
        document_id=document.id,
        content=content,
        organization_id=document.organization_id,
        course_id=document.course_id,
    )
    embedding = _zero_vector(settings.embedding_dimension)
    await vector_adapter.insert_document(document, [(chunk, embedding)])
    return chunk


async def test_search_finds_a_chunk_matching_the_query_terms(
    pool: asyncpg.Pool, settings: Settings
) -> None:
    adapter = PostgresLexicalSearchAdapter(pool)
    document = _make_document(checksum=f"test-{uuid4()}")

    try:
        matching = await _insert(
            pool, settings, document, "El acuerdo de nivel de servicio define tiempos de respuesta."
        )

        results = await adapter.search(
            "nivel de servicio",
            organization_id=TEST_ORGANIZATION_ID,
            course_id=TEST_COURSE_ID,
            top_k=5,
        )

        assert len(results) == 1
        assert results[0].chunk_id == matching.id
        assert results[0].score > 0.0
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM source_documents WHERE id = $1", document.id)


async def test_search_ranks_the_more_relevant_chunk_first(
    pool: asyncpg.Pool, settings: Settings
) -> None:
    adapter = PostgresLexicalSearchAdapter(pool)
    document = _make_document(checksum=f"test-{uuid4()}")

    try:
        vector_adapter = PgVectorStoreAdapter(pool)
        embedding = _zero_vector(settings.embedding_dimension)
        highly_relevant = _make_chunk(
            document_id=document.id,
            chunk_index=0,
            content="Gestion de incidentes: gestion de incidentes y gestion de problemas.",
        )
        barely_relevant = _make_chunk(
            document_id=document.id,
            chunk_index=1,
            content="Gestion de activos de hardware y software.",
        )
        await vector_adapter.insert_document(
            document, [(highly_relevant, embedding), (barely_relevant, embedding)]
        )

        results = await adapter.search(
            "gestion de incidentes",
            organization_id=TEST_ORGANIZATION_ID,
            course_id=TEST_COURSE_ID,
            top_k=5,
        )

        assert results[0].chunk_id == highly_relevant.id
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM source_documents WHERE id = $1", document.id)


async def test_spanish_configuration_stems_plural_to_match_singular_query(
    pool: asyncpg.Pool, settings: Settings
) -> None:
    """Reproducible stemming check: PostgreSQL's built-in 'spanish' text
    search configuration (Snowball stemmer) reduces "incidentes" (plural,
    in the stored content) and "incidente" (singular, in the query) to the
    same lexeme — no custom tokenization code involved."""
    adapter = PostgresLexicalSearchAdapter(pool)
    document = _make_document(checksum=f"test-{uuid4()}")

    try:
        chunk = await _insert(
            pool, settings, document, "El registro de incidentes es responsabilidad del equipo."
        )

        results = await adapter.search(
            "incidente",
            organization_id=TEST_ORGANIZATION_ID,
            course_id=TEST_COURSE_ID,
            top_k=5,
        )

        assert len(results) == 1
        assert results[0].chunk_id == chunk.id
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM source_documents WHERE id = $1", document.id)


async def test_search_only_returns_chunks_within_the_same_organization(
    pool: asyncpg.Pool, settings: Settings
) -> None:
    adapter = PostgresLexicalSearchAdapter(pool)
    doc_a = _make_document(
        checksum=f"test-{uuid4()}", organization_id="org-A", course_id="course-A"
    )
    doc_b = _make_document(
        checksum=f"test-{uuid4()}", organization_id="org-B", course_id="course-A"
    )

    try:
        chunk_a = await _insert(pool, settings, doc_a, "contenido identico sobre incidentes")
        await _insert(pool, settings, doc_b, "contenido identico sobre incidentes")

        results = await adapter.search(
            "incidentes", organization_id="org-A", course_id="course-A", top_k=10
        )

        chunk_ids = {r.chunk_id for r in results}
        assert chunk_a.id in chunk_ids
        assert len(chunk_ids) == 1
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM source_documents WHERE id = ANY($1::uuid[])", [doc_a.id, doc_b.id]
            )


async def test_search_only_returns_chunks_within_the_same_course(
    pool: asyncpg.Pool, settings: Settings
) -> None:
    adapter = PostgresLexicalSearchAdapter(pool)
    doc_a = _make_document(
        checksum=f"test-{uuid4()}", organization_id="org-A", course_id="course-A"
    )
    doc_b = _make_document(
        checksum=f"test-{uuid4()}", organization_id="org-A", course_id="course-B"
    )

    try:
        chunk_a = await _insert(pool, settings, doc_a, "contenido identico sobre incidentes")
        await _insert(pool, settings, doc_b, "contenido identico sobre incidentes")

        results = await adapter.search(
            "incidentes", organization_id="org-A", course_id="course-A", top_k=10
        )

        chunk_ids = {r.chunk_id for r in results}
        assert chunk_a.id in chunk_ids
        assert len(chunk_ids) == 1
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM source_documents WHERE id = ANY($1::uuid[])", [doc_a.id, doc_b.id]
            )


async def test_search_returns_no_results_when_nothing_matches(
    pool: asyncpg.Pool, settings: Settings
) -> None:
    adapter = PostgresLexicalSearchAdapter(pool)

    results = await adapter.search(
        "una consulta que no coincide con nada",
        organization_id=f"org-empty-{uuid4()}",
        course_id=TEST_COURSE_ID,
        top_k=5,
    )

    assert results == []
