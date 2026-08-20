"""Embeds a question, searches for evidence, and decides whether there is
enough evidence to answer.

Kept separate from ``QueryService`` so the evidence-sufficiency decision is
independently testable and so a future caller (e.g. a citation-quality eval)
can reuse retrieval without going through answer generation at all.

Two strategies, selected once at construction time (never per-call):

- vector_only (default): unchanged since PR-002/PR-004 — embed the question,
  search the vector store, done. ``lexical_search_port`` is ``None``.
- hybrid (PR-006): also search a lexical port, fuse both rankings with
  Reciprocal Rank Fusion, and truncate to ``top_k``. See
  ``application.services.rank_fusion`` and docs/architecture.md's PR-006
  section for the evidence-sufficiency gate's design (it deliberately keeps
  the existing vector-similarity threshold semantics — RRF's fused score is
  a ranking signal, not a calibrated measure of evidence, and is never
  compared against ``score_threshold``).
"""

from dataclasses import dataclass

from agentic_learning_platform.application.ports.embedding_port import IEmbeddingPort
from agentic_learning_platform.application.ports.lexical_search_port import ILexicalSearchPort
from agentic_learning_platform.application.ports.vector_store_port import IVectorStorePort
from agentic_learning_platform.application.services.rank_fusion import reciprocal_rank_fusion
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
        lexical_search_port: ILexicalSearchPort | None = None,
        candidate_top_k: int | None = None,
        rrf_k: int | None = None,
    ) -> None:
        self._embedding_port = embedding_port
        self._vector_store_port = vector_store_port
        self._top_k = top_k
        self._score_threshold = score_threshold
        self._lexical_search_port = lexical_search_port
        self._candidate_top_k = candidate_top_k
        self._rrf_k = rrf_k

    async def retrieve(self, question: str, context: RequestContext) -> RetrievalOutcome:
        query_embedding = await self._embedding_port.embed_text(question)

        if self._lexical_search_port is None:
            results = await self._vector_store_port.search(
                query_embedding,
                organization_id=context.organization_id,
                course_id=context.course_id,
                top_k=self._top_k,
            )
            has_sufficient_evidence = bool(results) and results[0].score >= self._score_threshold
            return RetrievalOutcome(
                results=results, has_sufficient_evidence=has_sufficient_evidence
            )

        return await self._retrieve_hybrid(question, query_embedding, context)

    async def _retrieve_hybrid(
        self, question: str, query_embedding: list[float], context: RequestContext
    ) -> RetrievalOutcome:
        assert self._lexical_search_port is not None
        assert self._candidate_top_k is not None
        assert self._rrf_k is not None

        vector_candidates = await self._vector_store_port.search(
            query_embedding,
            organization_id=context.organization_id,
            course_id=context.course_id,
            top_k=self._candidate_top_k,
        )
        lexical_candidates = await self._lexical_search_port.search(
            question,
            organization_id=context.organization_id,
            course_id=context.course_id,
            top_k=self._candidate_top_k,
        )
        fused = reciprocal_rank_fusion(
            vector_candidates, lexical_candidates, k=self._rrf_k, top_k=self._top_k
        )
        results = [item.result for item in fused]

        # Evidence-sufficiency gate deliberately preserves the EXISTING
        # vector-similarity semantics of `score_threshold` — it does not
        # reinterpret evidence-sufficiency as a function of RRF rank/score.
        # RRF is a ranking signal, not a calibrated measure of evidence: the
        # fused #1 result only counts as sufficient evidence if it was among
        # the vector candidates AND its OWN vector similarity score clears
        # the threshold (see docs/architecture.md's PR-006 section). A
        # result promoted to #1 by lexical search alone, with no vector
        # candidacy at all, is correctly ranked higher but does NOT satisfy
        # this gate — that is a known, intentionally-not-fixed limitation of
        # this PR's hybrid evidence gate (see the eval findings for whether
        # this actually costs anything in practice).
        has_sufficient_evidence = (
            bool(fused)
            and fused[0].vector_score is not None
            and fused[0].vector_score >= self._score_threshold
        )
        return RetrievalOutcome(results=results, has_sufficient_evidence=has_sufficient_evidence)
