"""Pure unit tests for Reciprocal Rank Fusion — no DB, no mocks: the
function only takes and returns plain data.

Tie-break note: given the ranks (`enumerate`) computed from `vector_results`/
`lexical_results`, two distinct chunks can never simultaneously have both
equal `rrf_score` AND equal `vector_rank` (including both being absent) —
that would require two different chunks occupying the same position within
one already-ranked list, which is impossible by construction. The
`chunk_id`-based final tie-break in the implementation is therefore a
defense-in-depth guarantee, not a reachable branch under well-formed input;
the reachable, meaningful tie (equal `rrf_score`, differing `vector_rank`)
is what `test_tie_is_broken_by_the_better_vector_rank` below exercises.
"""

from uuid import uuid4

from agentic_learning_platform.application.services.rank_fusion import reciprocal_rank_fusion
from agentic_learning_platform.domain.models import SearchResult

K = 60


def _result(*, score: float = 0.0, content: str = "contenido") -> SearchResult:
    return SearchResult(
        chunk_id=uuid4(),
        document_id=uuid4(),
        source_name="doc.pdf",
        page_number=1,
        chunk_index=0,
        content=content,
        score=score,
    )


def test_a_document_in_both_rankings_sums_both_reciprocal_terms() -> None:
    shared = _result(score=0.87)
    lexical_view = SearchResult(
        chunk_id=shared.chunk_id,
        document_id=shared.document_id,
        source_name=shared.source_name,
        page_number=shared.page_number,
        chunk_index=shared.chunk_index,
        content=shared.content,
        score=0.42,  # a different, incomparable (lexical) score for the same chunk
    )

    fused = reciprocal_rank_fusion([shared], [lexical_view], k=K, top_k=5)

    assert len(fused) == 1  # deduplicated, not duplicated
    entry = fused[0]
    assert entry.vector_rank == 1
    assert entry.lexical_rank == 1
    assert entry.rrf_score == 1 / (K + 1) + 1 / (K + 1)
    # The vector branch's own similarity score is preserved distinctly and
    # is never overwritten by the lexical score or the RRF score.
    assert entry.vector_score == 0.87
    assert entry.result.score == 0.87  # vector-sourced object wins as the representative


def test_a_document_found_only_by_vector_search() -> None:
    only_vector = _result(score=0.91)

    fused = reciprocal_rank_fusion([only_vector], [], k=K, top_k=5)

    assert len(fused) == 1
    entry = fused[0]
    assert entry.vector_rank == 1
    assert entry.lexical_rank is None
    assert entry.vector_score == 0.91
    assert entry.rrf_score == 1 / (K + 1)


def test_a_document_found_only_by_lexical_search() -> None:
    only_lexical = _result(score=0.15)

    fused = reciprocal_rank_fusion([], [only_lexical], k=K, top_k=5)

    assert len(fused) == 1
    entry = fused[0]
    assert entry.vector_rank is None
    assert entry.lexical_rank == 1
    # No vector candidacy at all: vector_score must be None, never a
    # fabricated 0.0 or the lexical score under a different name.
    assert entry.vector_score is None
    assert entry.rrf_score == 1 / (K + 1)


def test_tie_is_broken_by_the_better_vector_rank() -> None:
    # vector_rank=1, lexical_rank=None -> rrf = 1/(K+1)
    vector_only = _result(score=0.5)
    # vector_rank=None, lexical_rank=1 -> rrf = 1/(K+1), an exact tie with the above
    lexical_only = _result(score=0.5)

    fused = reciprocal_rank_fusion([vector_only], [lexical_only], k=K, top_k=5)

    assert len(fused) == 2
    assert fused[0].rrf_score == fused[1].rrf_score  # genuine tie
    assert fused[0].result.chunk_id == vector_only.chunk_id  # the one WITH a vector rank wins
    assert fused[1].result.chunk_id == lexical_only.chunk_id


def test_top_k_truncates_the_fused_list() -> None:
    vector_results = [_result(score=0.9 - 0.01 * i) for i in range(10)]

    fused = reciprocal_rank_fusion(vector_results, [], k=K, top_k=3)

    assert len(fused) == 3
    assert [f.vector_rank for f in fused] == [1, 2, 3]


def test_fused_order_is_by_descending_rrf_score() -> None:
    top_both = _result(score=0.9)  # rank 1 in both -> highest rrf
    mid_vector_only = _result(score=0.7)  # rank 2 in vector only
    low_lexical_only = _result(score=0.2)  # rank 2 in lexical only

    vector_results = [top_both, mid_vector_only]
    lexical_results = [
        SearchResult(
            chunk_id=top_both.chunk_id,
            document_id=top_both.document_id,
            source_name=top_both.source_name,
            page_number=top_both.page_number,
            chunk_index=top_both.chunk_index,
            content=top_both.content,
            score=0.6,
        ),
        low_lexical_only,
    ]

    fused = reciprocal_rank_fusion(vector_results, lexical_results, k=K, top_k=5)

    assert [f.result.chunk_id for f in fused] == [
        top_both.chunk_id,
        mid_vector_only.chunk_id,
        low_lexical_only.chunk_id,
    ]


def test_returns_empty_list_when_both_branches_are_empty() -> None:
    assert reciprocal_rank_fusion([], [], k=K, top_k=5) == []
