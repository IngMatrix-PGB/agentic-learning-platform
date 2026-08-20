"""PostgreSQL + pgvector adapter: persistence and cosine-similarity search.

Requires the pool's connections to have gone through
``pgvector.asyncpg.register_vector`` (done once in
``infrastructure.db.pool.create_pool``) — a plain ``list[float]`` passed as a
query parameter is then encoded as a pgvector ``vector`` automatically.
"""

from collections.abc import Sequence

import asyncpg

from agentic_learning_platform.application.ports.vector_store_port import IVectorStorePort
from agentic_learning_platform.domain.models import DocumentChunk, SearchResult, SourceDocument


class PgVectorStoreAdapter(IVectorStorePort):
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def find_by_checksum(
        self, checksum_sha256: str, *, organization_id: str, course_id: str
    ) -> SourceDocument | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, organization_id, course_id, source_name, checksum_sha256,
                       mime_type, file_size, page_count, processing_status, uploaded_at
                FROM source_documents
                WHERE checksum_sha256 = $1 AND organization_id = $2 AND course_id = $3
                """,
                checksum_sha256,
                organization_id,
                course_id,
            )
        return _row_to_source_document(row) if row is not None else None

    async def insert_document(
        self,
        document: SourceDocument,
        chunks_with_embeddings: Sequence[tuple[DocumentChunk, list[float]]],
    ) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                INSERT INTO source_documents
                    (id, organization_id, course_id, source_name, checksum_sha256,
                     mime_type, file_size, page_count, processing_status, uploaded_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                document.id,
                document.organization_id,
                document.course_id,
                document.source_name,
                document.checksum_sha256,
                document.mime_type,
                document.file_size,
                document.page_count,
                document.processing_status,
                document.uploaded_at,
            )
            await conn.executemany(
                """
                INSERT INTO document_chunks
                    (id, document_id, organization_id, course_id, source_name,
                     page_number, chunk_index, content, embedding, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                [
                    (
                        chunk.id,
                        chunk.document_id,
                        chunk.organization_id,
                        chunk.course_id,
                        chunk.source_name,
                        chunk.page_number,
                        chunk.chunk_index,
                        chunk.content,
                        embedding,
                        chunk.created_at,
                    )
                    for chunk, embedding in chunks_with_embeddings
                ],
            )

    async def search(
        self,
        query_embedding: list[float],
        *,
        organization_id: str,
        course_id: str,
        top_k: int,
    ) -> list[SearchResult]:
        async with self._pool.acquire() as conn:
            # WHERE is applied here, before ORDER BY/LIMIT, in one statement —
            # never a global top-k fetch filtered afterward in Python. See
            # docs/architecture.md's PR-004 section for why organization_id/
            # course_id live directly on this table (not just on
            # source_documents, requiring a JOIN here that pgvector's HNSW
            # index cannot use as efficiently).
            rows = await conn.fetch(
                """
                SELECT id, document_id, source_name, page_number, chunk_index, content,
                       1 - (embedding <=> $1) AS score
                FROM document_chunks
                WHERE organization_id = $2 AND course_id = $3
                ORDER BY embedding <=> $1
                LIMIT $4
                """,
                query_embedding,
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


def _row_to_source_document(row: asyncpg.Record) -> SourceDocument:
    return SourceDocument(
        id=row["id"],
        organization_id=row["organization_id"],
        course_id=row["course_id"],
        source_name=row["source_name"],
        checksum_sha256=row["checksum_sha256"],
        mime_type=row["mime_type"],
        file_size=row["file_size"],
        page_count=row["page_count"],
        processing_status=row["processing_status"],
        uploaded_at=row["uploaded_at"],
    )
