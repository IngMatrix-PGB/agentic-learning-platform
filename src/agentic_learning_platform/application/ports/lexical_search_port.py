"""Port for keyword/lexical search over document chunks.

A second, independent retrieval signal alongside ``IVectorStorePort`` — used
by Hybrid Retrieval (PR-006) together with Reciprocal Rank Fusion. Returns
``SearchResult`` for the same reason ``IVectorStorePort.search`` does: both
branches feed the same fusion step, which only needs each result's identity
(``chunk_id``) and content, never a branch-specific shape.
"""

from abc import ABC, abstractmethod

from agentic_learning_platform.domain.models import SearchResult


class ILexicalSearchPort(ABC):
    @abstractmethod
    async def search(
        self,
        question: str,
        *,
        organization_id: str,
        course_id: str,
        top_k: int,
    ) -> list[SearchResult]:
        """Return the ``top_k`` chunks most relevant to ``question`` by
        keyword/lexical ranking within this organization/course scope,
        ordered by descending relevance. Scoping is applied directly in the
        underlying query before any ``LIMIT`` — never by fetching globally
        and filtering afterward (same requirement as ``IVectorStorePort``).

        This is a lexical signal, not a probability or a similarity score
        comparable to ``IVectorStorePort.search``'s cosine scores — the two
        must only ever be combined by rank (see
        ``application.services.rank_fusion``), never by comparing their raw
        scores directly.
        """
        ...
