"""Orchestrates parse -> chunk -> embed -> persist, idempotent by the
checksum of the uploaded bytes. Runs synchronously within the request, as
scoped for this PR — no queue.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from agentic_learning_platform.application.ports.document_parser_port import IDocumentParserPort
from agentic_learning_platform.application.ports.embedding_port import IEmbeddingPort
from agentic_learning_platform.application.ports.vector_store_port import IVectorStorePort
from agentic_learning_platform.domain.models import DocumentChunk, RequestContext, SourceDocument
from agentic_learning_platform.exceptions import DocumentTooLargeError, UnsupportedDocumentError
from agentic_learning_platform.infrastructure.chunking.page_chunking_strategy import chunk_by_page

logger = logging.getLogger(__name__)

_ALLOWED_MIME_TYPES = {"application/pdf"}


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    document_id: UUID
    pages: int
    chunks_created: int
    already_existed: bool


class IngestionService:
    def __init__(
        self,
        parser_port: IDocumentParserPort,
        embedding_port: IEmbeddingPort,
        vector_store_port: IVectorStorePort,
        *,
        max_upload_size_mb: int,
        chunk_max_chars: int,
    ) -> None:
        self._parser_port = parser_port
        self._embedding_port = embedding_port
        self._vector_store_port = vector_store_port
        self._max_upload_size_bytes = max_upload_size_mb * 1024 * 1024
        self._chunk_max_chars = chunk_max_chars

    async def ingest(
        self, content: bytes, *, filename: str, mime_type: str, context: RequestContext
    ) -> IngestionOutcome:
        if mime_type not in _ALLOWED_MIME_TYPES:
            raise UnsupportedDocumentError(
                f"Unsupported content type {mime_type!r}; only PDF is supported in this version."
            )
        if len(content) > self._max_upload_size_bytes:
            raise DocumentTooLargeError(
                f"{filename!r} is {len(content)} bytes, exceeding the "
                f"{self._max_upload_size_bytes} byte limit."
            )

        checksum = hashlib.sha256(content).hexdigest()
        existing = await self._vector_store_port.find_by_checksum(
            checksum, organization_id=context.organization_id, course_id=context.course_id
        )
        if existing is not None:
            logger.info(
                "document_ingest_skipped_already_exists organization_id=%s course_id=%s "
                "document_id=%s",
                context.organization_id,
                context.course_id,
                existing.id,
            )
            return IngestionOutcome(
                document_id=existing.id,
                pages=existing.page_count,
                chunks_created=0,
                already_existed=True,
            )

        extracted = await self._parser_port.extract(content, filename=filename)
        pending_chunks = chunk_by_page(extracted, max_chars=self._chunk_max_chars)
        embeddings = await self._embedding_port.embed_batch(
            [chunk.content for chunk in pending_chunks]
        )

        document_id = uuid4()
        now = datetime.now(UTC)
        document = SourceDocument(
            id=document_id,
            organization_id=context.organization_id,
            course_id=context.course_id,
            source_name=filename,
            checksum_sha256=checksum,
            mime_type=mime_type,
            file_size=len(content),
            page_count=extracted.page_count,
            processing_status="completed",
            uploaded_at=now,
        )
        chunks_with_embeddings = [
            (
                DocumentChunk(
                    id=uuid4(),
                    document_id=document_id,
                    organization_id=context.organization_id,
                    course_id=context.course_id,
                    source_name=filename,
                    page_number=pending.page_number,
                    chunk_index=pending.chunk_index,
                    content=pending.content,
                    created_at=now,
                ),
                embedding,
            )
            for pending, embedding in zip(pending_chunks, embeddings, strict=True)
        ]

        await self._vector_store_port.insert_document(document, chunks_with_embeddings)

        logger.info(
            "document_ingested organization_id=%s course_id=%s document_id=%s chunks=%d",
            context.organization_id,
            context.course_id,
            document_id,
            len(chunks_with_embeddings),
        )
        return IngestionOutcome(
            document_id=document_id,
            pages=extracted.page_count,
            chunks_created=len(chunks_with_embeddings),
            already_existed=False,
        )
