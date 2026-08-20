"""Embeds a question, searches the vector store, and decides whether there
is enough evidence to answer.

Kept separate from ``QueryService`` so the evidence-sufficiency decision is
independently testable and so a future caller (e.g. a citation-quality eval)
can reuse retrieval without going through answer generation at all.
"""

from dataclasses import dataclass

from agentic_learning_platform.application.ports.embedding_port import IEmbeddingPort
from agentic_learning_platform.application.ports.vector_store_port import IVectorStorePort
from agentic_learning_platform.domain.models import RequestContext, SearchResult


@dataclass(frozen=True, slots=True)
class RetrievalOutcome:
    results: list[SearchResult]
    has_sufficient_evidence: bool


class RetrievalService:
    def __init__(
        self,
        embedding_port: IEmbeddingPort,
        vector_store_port: IVectorStorePort,
        *,
        top_k: int,
        score_threshold: float,
    ) -> None:
        self._embedding_port = embedding_port
        self._vector_store_port = vector_store_port
        self._top_k = top_k
        self._score_threshold = score_threshold

    async def retrieve(self, question: str, context: RequestContext) -> RetrievalOutcome:
        query_embedding = await self._embedding_port.embed_text(question)
        results = await self._vector_store_port.search(
            query_embedding,
            organization_id=context.organization_id,
            course_id=context.course_id,
            top_k=self._top_k,
        )

        has_sufficient_evidence = bool(results) and results[0].score >= self._score_threshold
        return RetrievalOutcome(results=results, has_sufficient_evidence=has_sufficient_evidence)
