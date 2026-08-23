"""Port for persisting the raw bytes of an uploaded source document.

Distinct from ``IVectorStorePort``: this port stores the original file
(e.g. in S3, for AWS mode), never the extracted/chunked/embedded content —
PostgreSQL remains the sole store for indexed chunks and metadata. Local
mode has no requirement to keep the raw bytes at all (see
``infrastructure.storage.null_document_storage_adapter``).
"""

from abc import ABC, abstractmethod
from uuid import UUID


def build_document_storage_key(*, organization_id: str, course_id: str, document_id: UUID) -> str:
    """The one place that defines the storage key structure — deterministic
    and fully derivable from identity already on ``SourceDocument``, so it
    is never persisted as its own column (see docs/architecture.md's
    PR-008 section)."""
    return f"org/{organization_id}/courses/{course_id}/documents/{document_id}/source.pdf"


class IDocumentStoragePort(ABC):
    @abstractmethod
    async def upload(self, content: bytes, *, key: str, content_type: str) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Best-effort compensating delete — e.g. when a DB write fails
        after ``upload`` already succeeded (see
        ``application.services.ingestion_service``). Implementations should
        not raise for a key that does not exist."""
        ...
