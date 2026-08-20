"""PostgreSQL native full-text search adapter (Hybrid Retrieval, PR-006).

Uses ``tsvector``/``ts_rank_cd`` with the built-in ``'spanish'`` text search
configuration (Snowball stemming + Spanish stopwords, both included by
PostgreSQL itself — no tokenization code of our own). This is deliberately
NOT called a "BM25 adapter": ``ts_rank_cd`` is a term-frequency/coverage-
density ranking, not the Okapi BM25 formula — see docs/architecture.md's
PR-006 section for why that distinction is called out explicitly everywhere
in this codebase ("lexical search"/"PostgreSQL FTS", never "BM25").

Relies on migration 003's generated ``content_tsv`` column, which PostgreSQL
recomputes automatically on every insert — this adapter never writes to
that column and ``IngestionService`` needs no changes to keep it in sync.
"""

import asyncpg

from agentic_learning_platform.application.ports.lexical_search_port import ILexicalSearchPort
from agentic_learning_platform.domain.models import SearchResult


class PostgresLexicalSearchAdapter(ILexicalSearchPort):
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def search(
        self,
        question: str,
        *,
        organization_id: str,
        course_id: str,
        top_k: int,
    ) -> list[SearchResult]:
        async with self._pool.acquire() as conn:
            # WHERE is applied here, before ORDER BY/LIMIT, in one statement —
            # never a global fetch filtered afterward in Python (same
            # requirement as PgVectorStoreAdapter.search — see
            # docs/architecture.md's PR-004 and PR-006 sections).
            rows = await conn.fetch(
                """
                SELECT id, document_id, source_name, page_number, chunk_index, content,
                       ts_rank_cd(content_tsv, plainto_tsquery('spanish', $1)) AS score
                FROM document_chunks
                WHERE organization_id = $2 AND course_id = $3
                  AND content_tsv @@ plainto_tsquery('spanish', $1)
                ORDER BY score DESC
                LIMIT $4
                """,
                question,
                organization_id,
                course_id,
                top_k,
            )
        return [
            SearchResult(
                chunk_id=row["id"],
                document_id=row["document_id"],
                source_name=row["source_name"],
                page_number=row["page_number"],
                chunk_index=row["chunk_index"],
                content=row["content"],
                score=float(row["score"]),
            )
            for row in rows
        ]
