"""Tests for the eval harness's own arithmetic — no DB, no golden dataset
execution. The 32 golden questions are NOT converted into pytest assertions
here (see docs/architecture.md's PR-005 section): this file only proves
Recall@K/MRR/citation-accuracy/confusion-matrix/latency-percentile are
computed correctly, using small hand-built fixtures.
"""

from uuid import uuid4

from agentic_learning_platform.domain.models import Citation, SearchResult
from agentic_learning_platform.evals.metrics import (
    citation_is_correct,
    find_rank,
    groundedness_score,
    latency_stats,
    mean_reciprocal_rank,
    rate,
    recall_at_k,
)


def _result(*, source_name: str, page_number: int, score: float = 0.5) -> SearchResult:
    return SearchResult(
        chunk_id=uuid4(),
        document_id=uuid4(),
        source_name=source_name,
        page_number=page_number,
        chunk_index=0,
        content="contenido",
        score=score,
    )


def _citation(*, source: str, page: int) -> Citation:
    return Citation(source=source, page=page, chunk_id=uuid4(), score=0.9)


class TestFindRank:
    def test_returns_rank_of_first_match(self) -> None:
        results = [
            _result(source_name="other.pdf", page_number=1),
            _result(source_name="manual.pdf", page_number=3),
            _result(source_name="manual.pdf", page_number=1),
        ]

        assert find_rank(results, "manual.pdf", [1]) == 3

    def test_returns_none_when_no_result_matches(self) -> None:
        results = [_result(source_name="other.pdf", page_number=1)]

        assert find_rank(results, "manual.pdf", [1]) is None

    def test_returns_none_when_expected_source_is_none(self) -> None:
        results = [_result(source_name="manual.pdf", page_number=1)]

        assert find_rank(results, None, []) is None

    def test_matches_any_page_in_expected_pages(self) -> None:
        results = [_result(source_name="manual.pdf", page_number=2)]

        assert find_rank(results, "manual.pdf", [1, 2, 3]) == 1


class TestRecallAtK:
    def test_hit_within_k_counts(self) -> None:
        assert recall_at_k([1, 2, None], 3) == 2 / 3

    def test_hit_outside_k_does_not_count(self) -> None:
        assert recall_at_k([5], 3) == 0.0

    def test_all_hits_within_k_is_one(self) -> None:
        assert recall_at_k([1, 1, 2], 3) == 1.0

    def test_none_when_no_answerable_cases(self) -> None:
        assert recall_at_k([], 1) is None


class TestMeanReciprocalRank:
    def test_averages_reciprocals(self) -> None:
        # 1/1, 1/2, 0 (miss) -> (1 + 0.5 + 0) / 3
        assert mean_reciprocal_rank([1, 2, None]) == (1 + 0.5 + 0) / 3

    def test_perfect_rank_one_everywhere_is_one(self) -> None:
        assert mean_reciprocal_rank([1, 1, 1]) == 1.0

    def test_none_when_no_answerable_cases(self) -> None:
        assert mean_reciprocal_rank([]) is None


class TestCitationIsCorrect:
    def test_correct_when_sufficient_and_matching_citation_present(self) -> None:
        citations = [_citation(source="manual.pdf", page=1)]

        assert citation_is_correct(True, citations, "manual.pdf", [1]) is True

    def test_incorrect_when_evidence_deemed_insufficient_even_with_matching_citation(
        self,
    ) -> None:
        # Defends against inspecting citations in isolation from the
        # sufficiency decision that actually produced them.
        citations = [_citation(source="manual.pdf", page=1)]

        assert citation_is_correct(False, citations, "manual.pdf", [1]) is False

    def test_incorrect_when_citations_do_not_match_expected_source_or_page(self) -> None:
        citations = [_citation(source="other.pdf", page=9)]

        assert citation_is_correct(True, citations, "manual.pdf", [1]) is False


class TestRate:
    def test_computes_fraction_of_true_values(self) -> None:
        assert rate([True, True, False, False]) == 0.5

    def test_none_when_empty(self) -> None:
        assert rate([]) is None

    def test_all_true_is_one(self) -> None:
        assert rate([True, True]) == 1.0


class TestGroundednessScore:
    def test_single_segment_contained_in_evidence_is_fully_grounded(self) -> None:
        assert groundedness_score("contenido real", ["contenido real", "otro"]) == 1.0

    def test_multi_segment_answer_checks_each_segment_independently(self) -> None:
        answer = "primero\n\n---\n\nsegundo"
        assert groundedness_score(answer, ["primero", "segundo"]) == 1.0

    def test_segment_not_found_in_evidence_lowers_the_score(self) -> None:
        answer = "primero\n\n---\n\ninventado"
        assert groundedness_score(answer, ["primero", "segundo"]) == 0.5

    def test_empty_answer_is_zero(self) -> None:
        assert groundedness_score("", ["algo"]) == 0.0


class TestLatencyStats:
    def test_matches_hand_computed_percentiles(self) -> None:
        samples = [10.0, 20.0, 30.0, 40.0, 50.0]

        stats = latency_stats(samples)

        assert stats["mean"] == 30.0
        assert stats["p50"] == 30.0
        assert stats["p95"] == 48.0  # linear interpolation, same as numpy's default

    def test_single_sample(self) -> None:
        stats = latency_stats([15.0])

        assert stats == {"mean": 15.0, "p50": 15.0, "p95": 15.0}

    def test_empty_samples_are_zero_not_an_error(self) -> None:
        assert latency_stats([]) == {"mean": 0.0, "p50": 0.0, "p95": 0.0}
