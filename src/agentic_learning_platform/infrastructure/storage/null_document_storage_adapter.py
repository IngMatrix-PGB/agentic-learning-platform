"""No-op document storage for local mode — preserves today's behavior of
never persisting the raw uploaded bytes anywhere. Local mode has no S3 (or
equivalent) requirement; this exists only so ``IngestionService`` can call
``IDocumentStoragePort`` uniformly regardless of ``runtime_mode``.
"""

from agentic_learning_platform.application.ports.document_storage_port import IDocumentStoragePort


class NullDocumentStorageAdapter(IDocumentStoragePort):
    async def upload(self, content: bytes, *, key: str, content_type: str) -> None:
        return None

    async def delete(self, key: str) -> None:
        return None
