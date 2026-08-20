"""Port for persisting and searching document chunks and their embeddings."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from agentic_learning_platform.domain.models import DocumentChunk, SearchResult, SourceDocument


class IVectorStorePort(ABC):
    @abstractmethod
    async def find_by_checksum(
        self, checksum_sha256: str, *, organization_id: str, course_id: str
    ) -> SourceDocument | None:
        """Return the existing document for this checksum within this
        organization/course scope, if any (idempotency is scoped — the same
        checksum can exist as a separate document in a different scope)."""
        ...

    @abstractmethod
    async def insert_document(
        self,
        document: SourceDocument,
        chunks_with_embeddings: Sequence[tuple[DocumentChunk, list[float]]],
    ) -> None:
        """Persist a document and all of its chunks in a single transaction.

        ``document`` and each chunk already carry their own
        ``organization_id``/``course_id`` — this method never receives scope
        as a separate parameter, so there is no way to write a document and
        its chunks with mismatched scope."""
        ...

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        *,
        organization_id: str,
        course_id: str,
        top_k: int,
    ) -> list[SearchResult]:
        """Return the ``top_k`` chunks most similar to ``query_embedding``
        within this organization/course scope, ordered by descending
        similarity score. Scoping is applied directly in SQL before the
        ``LIMIT`` — never by fetching globally and filtering afterward."""
        ...
