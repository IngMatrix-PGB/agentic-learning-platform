"""Port for persisting and searching document chunks and their embeddings."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from agentic_learning_platform.domain.models import DocumentChunk, SearchResult, SourceDocument


class IVectorStorePort(ABC):
    @abstractmethod
    async def find_by_checksum(self, checksum_sha256: str) -> SourceDocument | None:
        """Return the existing document for this checksum, if any (idempotency)."""
        ...

    @abstractmethod
    async def insert_document(
        self,
        document: SourceDocument,
        chunks_with_embeddings: Sequence[tuple[DocumentChunk, list[float]]],
    ) -> None:
        """Persist a document and all of its chunks in a single transaction."""
        ...

    @abstractmethod
    async def search(self, query_embedding: list[float], *, top_k: int) -> list[SearchResult]:
        """Return the ``top_k`` chunks most similar to ``query_embedding``,
        ordered by descending similarity score."""
        ...
