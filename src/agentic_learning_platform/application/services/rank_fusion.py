"""Reciprocal Rank Fusion (RRF): combines a vector-similarity ranking and a
lexical ranking into one ordered list, using each ranking's *position* only —
never comparing the two branches' raw scores directly, since they live on
incomparable scales (cosine similarity in [0, 1] vs. PostgreSQL FTS's
unbounded, corpus-dependent ``ts_rank_cd`` scale).

    RRF_score(d) = sum(1 / (k + rank_i(d)))  over the rankings where d appears

``k=60`` is the literature-standard default (Cormack, Clarke & Buettcher,
2009; also Elasticsearch's own RRF default) — never tuned against the golden
dataset (see docs/architecture.md's PR-006 section).
"""

from dataclasses import dataclass
from uuid import UUID

from agentic_learning_platform.domain.models import SearchResult


@dataclass(frozen=True, slots=True)
class FusedResult:
    """One fused ranking position.

    ``result.score`` is the chunk's own score from whichever branch it was
    actually found by (the raw vector cosine similarity if present in the
    vector candidates, otherwise the raw lexical score) — it is never the
    RRF score, and a value from one ``FusedResult`` is never comparable to
    another's if they came from different branches. ``vector_score`` is kept
    separately, explicitly, for callers (the evidence-sufficiency gate) that
    must reason about vector similarity specifically and must not be handed
    an RRF or lexical value instead — see ``RetrievalService.retrieve``.
    """

    result: SearchResult
    rrf_score: float
    vector_rank: int | None
    lexical_rank: int | None
    vector_score: float | None


def reciprocal_rank_fusion(
    vector_results: list[SearchResult],
    lexical_results: list[SearchResult],
    *,
    k: int,
    top_k: int,
) -> list[FusedResult]:
    """Fuse two independently-ranked candidate lists by ``chunk_id``.

    Deterministic ordering: highest RRF score first; ties broken by the
    better (lower) vector rank — a chunk absent from the vector ranking
    sorts after any chunk present in it; a final tie-break by ``chunk_id``
    guarantees a fully deterministic order even between two lexical-only
    chunks with an identical fused score.
    """
    vector_rank_by_id: dict[UUID, int] = {
        result.chunk_id: rank for rank, result in enumerate(vector_results, start=1)
    }
    vector_score_by_id: dict[UUID, float] = {
        result.chunk_id: result.score for result in vector_results
    }
    lexical_rank_by_id: dict[UUID, int] = {
        result.chunk_id: rank for rank, result in enumerate(lexical_results, start=1)
    }

    # When a chunk_id appears in both branches, the vector-sourced
    # `SearchResult` wins as the representative object (a bounded [0, 1]
    # cosine score is more informative than the unbounded lexical score for
    # anything downstream that inspects `.score`) — iteration order below
    # (vector first) makes `setdefault` express exactly that preference.
    result_by_id: dict[UUID, SearchResult] = {}
    for result in vector_results:
        result_by_id.setdefault(result.chunk_id, result)
    for result in lexical_results:
        result_by_id.setdefault(result.chunk_id, result)

    fused: list[FusedResult] = []
    for chunk_id, result in result_by_id.items():
        vector_rank = vector_rank_by_id.get(chunk_id)
        lexical_rank = lexical_rank_by_id.get(chunk_id)

        rrf_score = 0.0
        if vector_rank is not None:
            rrf_score += 1.0 / (k + vector_rank)
        if lexical_rank is not None:
            rrf_score += 1.0 / (k + lexical_rank)

        fused.append(
            FusedResult(
                result=result,
                rrf_score=rrf_score,
                vector_rank=vector_rank,
                lexical_rank=lexical_rank,
                vector_score=vector_score_by_id.get(chunk_id),
            )
        )

    fused.sort(
        key=lambda item: (
            -item.rrf_score,
            item.vector_rank if item.vector_rank is not None else float("inf"),
            str(item.result.chunk_id),
        )
    )
    return fused[:top_k]
