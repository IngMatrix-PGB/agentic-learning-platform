"""Unit/integration tests for `RetrievalService`'s hybrid branch — real
Postgres for the actual vector/lexical search (never mocked, same
philosophy as the adapter test files), with a small hand-written
`IEmbeddingPort` test double so the query embedding is fully controllable
(there is no other way to make cosine-similarity ranking deterministic
without depending on FastEmbed's real model output).

Covers: hybrid ordering can differ from vector-only ordering, the evidence
gate uses the fused #1 result's OWN vector similarity (never its RRF
score), and vector-only behavior is unaffected when no lexical port is
configured (regression against PR-002/PR-004).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest

from agentic_learning_platform.application.ports.embedding_port import IEmbeddingPort
from agentic_learning_platform.application.services.retrieval_service import RetrievalService
from agentic_learning_platform.config import Settings, get_settings
from agentic_learning_platform.domain.models import DocumentChunk, RequestContext, SourceDocument
from agentic_learning_platform.infrastructure.db.migrations.runner import run_migrations
from agentic_learning_platform.infrastructure.db.pool import close_pool, create_pool
from agentic_learning_platform.infrastructure.lexical_search.postgres_fts_adapter import (
    PostgresLexicalSearchAdapter,
)
from agentic_learning_platform.infrastructure.vector_store.pgvector_vector_store_adapter import (
    PgVectorStoreAdapter,
)

TEST_ORGANIZATION_ID = "org-hybrid-test"
TEST_COURSE_ID = "course-hybrid-test"
QUESTION = "gestion de incidentes criticos"


class _FixedEmbeddingPort(IEmbeddingPort):
    """Deterministic test double: returns a pre-registered vector for a
    known question string, instead of calling a real embedding model."""

    def __init__(self, embedding_by_text: dict[str, list[float]]) -> None:
        self._embedding_by_text = embedding_by_text

    async def embed_text(self, text: str) -> list[float]:
        return self._embedding_by_text[text]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._embedding_by_text[text] for text in texts]

    def get_dimension(self) -> int:
        return len(next(iter(self._embedding_by_text.values())))

    def get_model_name(self) -> str:
        return "fixed-test-embedding"


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
async def pool(settings: Settings) -> AsyncIterator[asyncpg.Pool]:
    await run_migrations(settings)
    db_pool = await create_pool(settings)
    yield db_pool
    await close_pool(db_pool)


def _document(*, checksum: str) -> SourceDocument:
    return SourceDocument(
        id=uuid4(),
        organization_id=TEST_ORGANIZATION_ID,
        course_id=TEST_COURSE_ID,
        source_name="test.pdf",
        checksum_sha256=checksum,
        mime_type="application/pdf",
        file_size=1,
        page_count=1,
        processing_status="completed",
        uploaded_at=datetime.now(UTC),
    )


def _chunk(*, document_id: UUID, content: str, chunk_index: int = 0) -> DocumentChunk:
    return DocumentChunk(
        id=uuid4(),
        document_id=document_id,
        organization_id=TEST_ORGANIZATION_ID,
        course_id=TEST_COURSE_ID,
        source_name="test.pdf",
        page_number=1,
        chunk_index=chunk_index,
        content=content,
        created_at=datetime.now(UTC),
    )


async def test_hybrid_ordering_can_promote_a_lexically_strong_lower_vector_rank_result(
    pool: asyncpg.Pool, settings: Settings
) -> None:
    dim = settings.embedding_dimension
    query_embedding = [1.0] + [0.0] * (dim - 1)

    document = _document(checksum=f"test-{uuid4()}")
    # A: the best vector match (identical embedding), but no lexical overlap
    # with the question at all.
    chunk_a = _chunk(
        document_id=document.id,
        chunk_index=0,
        content="informacion general del curso y sus modulos",
    )
    # B: a poor vector match (orthogonal embedding), but a strong lexical
    # match for the question.
    chunk_b = _chunk(
        document_id=document.id,
        chunk_index=1,
        content="gestion de incidentes criticos y su resolucion",
    )

    vector_store = PgVectorStoreAdapter(pool)
    try:
        await vector_store.insert_document(
            document,
            [
                (chunk_a, query_embedding),
                (chunk_b, [0.0] * (dim - 1) + [1.0]),
            ],
        )

        embedding_port = _FixedEmbeddingPort({QUESTION: query_embedding})
        lexical_search = PostgresLexicalSearchAdapter(pool)
        context = RequestContext(
            organization_id=TEST_ORGANIZATION_ID, course_id=TEST_COURSE_ID, user_id="tester"
        )

        vector_only_service = RetrievalService(
            embedding_port, vector_store, top_k=2, score_threshold=0.35
        )
        vector_only_outcome = await vector_only_service.retrieve(QUESTION, context)
        assert vector_only_outcome.results[0].chunk_id == chunk_a.id  # pure vector: A wins

        hybrid_service = RetrievalService(
            embedding_port,
            vector_store,
            top_k=2,
            score_threshold=0.35,
            lexical_search_port=lexical_search,
            candidate_top_k=5,
            rrf_k=60,
        )
        hybrid_outcome = await hybrid_service.retrieve(QUESTION, context)

        # Combined signal (found by both branches) outranks a pure vector
        # match found by only one branch — the fused order differs from the
        # vector-only order.
        assert hybrid_outcome.results[0].chunk_id == chunk_b.id
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM source_documents WHERE id = $1", document.id)


async def test_evidence_gate_rejects_a_fused_top1_with_insufficient_vector_similarity(
    pool: asyncpg.Pool, settings: Settings
) -> None:
    """The fused #1 result (chunk_b, from the scenario above) has a low
    vector similarity score (it was a poor vector match) — the evidence gate
    must reject it based on ITS vector score, never the RRF score that made
    it rank #1."""
    dim = settings.embedding_dimension
    query_embedding = [1.0] + [0.0] * (dim - 1)

    document = _document(checksum=f"test-{uuid4()}")
    chunk_a = _chunk(
        document_id=document.id,
        chunk_index=0,
        content="informacion general del curso y sus modulos",
    )
    chunk_b = _chunk(
        document_id=document.id,
        chunk_index=1,
        content="gestion de incidentes criticos y su resolucion",
    )

    vector_store = PgVectorStoreAdapter(pool)
    try:
        await vector_store.insert_document(
            document,
            [
                (chunk_a, query_embedding),
                (chunk_b, [0.0] * (dim - 1) + [1.0]),
            ],
        )

        embedding_port = _FixedEmbeddingPort({QUESTION: query_embedding})
        lexical_search = PostgresLexicalSearchAdapter(pool)
        context = RequestContext(
            organization_id=TEST_ORGANIZATION_ID, course_id=TEST_COURSE_ID, user_id="tester"
        )

        hybrid_service = RetrievalService(
            embedding_port,
            vector_store,
            top_k=2,
            score_threshold=0.35,
            lexical_search_port=lexical_search,
            candidate_top_k=5,
            rrf_k=60,
        )
        outcome = await hybrid_service.retrieve(QUESTION, context)

        assert outcome.results[0].chunk_id == chunk_b.id  # fused #1
        assert outcome.has_sufficient_evidence is False  # but insufficient vector evidence
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM source_documents WHERE id = $1", document.id)


async def test_evidence_gate_accepts_a_fused_top1_with_sufficient_vector_similarity(
    pool: asyncpg.Pool, settings: Settings
) -> None:
    dim = settings.embedding_dimension
    query_embedding = [1.0] + [0.0] * (dim - 1)

    document = _document(checksum=f"test-{uuid4()}")
    # Strong match in both branches: identical embedding AND matching content.
    chunk = _chunk(
        document_id=document.id, content="gestion de incidentes criticos y su resolucion"
    )

    vector_store = PgVectorStoreAdapter(pool)
    try:
        await vector_store.insert_document(document, [(chunk, query_embedding)])

        embedding_port = _FixedEmbeddingPort({QUESTION: query_embedding})
        lexical_search = PostgresLexicalSearchAdapter(pool)
        context = RequestContext(
            organization_id=TEST_ORGANIZATION_ID, course_id=TEST_COURSE_ID, user_id="tester"
        )

        hybrid_service = RetrievalService(
            embedding_port,
            vector_store,
            top_k=2,
            score_threshold=0.35,
            lexical_search_port=lexical_search,
            candidate_top_k=5,
            rrf_k=60,
        )
        outcome = await hybrid_service.retrieve(QUESTION, context)

        assert outcome.has_sufficient_evidence is True
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM source_documents WHERE id = $1", document.id)


async def test_vector_only_behavior_is_unchanged_when_no_lexical_port_is_configured(
    pool: asyncpg.Pool, settings: Settings
) -> None:
    """Regression: constructing `RetrievalService` without a lexical port
    (the default) must behave exactly as it did before PR-006."""
    dim = settings.embedding_dimension
    query_embedding = [1.0] + [0.0] * (dim - 1)

    document = _document(checksum=f"test-{uuid4()}")
    chunk = _chunk(document_id=document.id, content="cualquier contenido")

    vector_store = PgVectorStoreAdapter(pool)
    try:
        await vector_store.insert_document(document, [(chunk, query_embedding)])

        embedding_port = _FixedEmbeddingPort({QUESTION: query_embedding})
        context = RequestContext(
            organization_id=TEST_ORGANIZATION_ID, course_id=TEST_COURSE_ID, user_id="tester"
        )

        service = RetrievalService(embedding_port, vector_store, top_k=5, score_threshold=0.35)
        outcome = await service.retrieve(QUESTION, context)

        assert outcome.results[0].chunk_id == chunk.id
        assert outcome.has_sufficient_evidence is True
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM source_documents WHERE id = $1", document.id)
