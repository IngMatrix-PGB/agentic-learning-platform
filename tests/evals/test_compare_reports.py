"""Pure unit tests for the comparison-report logic — small synthetic
report dicts, never the real golden dataset or a live eval run."""

from typing import Any

import pytest

from agentic_learning_platform.evals.compare_reports import build_comparison

_METRICS_TEMPLATE = {
    "recall_at_1": 0.5,
    "recall_at_3": 0.6,
    "recall_at_5": 0.6,
    "mrr": 0.55,
    "citation_accuracy": 0.5,
    "no_evidence_accuracy": 1.0,
    "false_positive_rate": 0.0,
    "false_negative_rate": 0.0,
}

_LATENCY_TEMPLATE = {"mean": 5.0, "p50": 4.5, "p95": 8.0}


def _report(per_case: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    return {
        "dataset": "golden_dataset.v1.json",
        "metrics": {**_METRICS_TEMPLATE, **overrides.get("metrics", {})},
        "latency_ms": {**_LATENCY_TEMPLATE, **overrides.get("latency_ms", {})},
        "per_case": per_case,
    }


def _case(case_id: str, rank: int | None) -> dict[str, Any]:
    return {"id": case_id, "rank": rank}


def test_case_whose_rank_improves_is_listed_as_improved() -> None:
    vector = _report([_case("Q1", 3)])
    hybrid = _report([_case("Q1", 1)])

    comparison = build_comparison(vector, hybrid)

    assert comparison["improved_cases"] == ["Q1"]
    assert comparison["regressed_cases"] == []


def test_case_whose_rank_worsens_is_listed_as_regressed() -> None:
    vector = _report([_case("Q1", 1)])
    hybrid = _report([_case("Q1", 3)])

    comparison = build_comparison(vector, hybrid)

    assert comparison["regressed_cases"] == ["Q1"]
    assert comparison["improved_cases"] == []


def test_case_that_never_found_evidence_in_either_run_is_an_unchanged_failure() -> None:
    vector = _report([_case("E1", None)])
    hybrid = _report([_case("E1", None)])

    comparison = build_comparison(vector, hybrid)

    assert comparison["unchanged_failures"] == ["E1"]


def test_case_that_starts_failing_and_then_passes_is_newly_passing() -> None:
    vector = _report([_case("C1-sla-synonym", None)])
    hybrid = _report([_case("C1-sla-synonym", 2)])

    comparison = build_comparison(vector, hybrid)

    assert comparison["newly_passing_cases"] == ["C1-sla-synonym"]
    assert comparison["headline_cases"]["C1-sla-synonym"] == {
        "vector_rank": None,
        "hybrid_rank": 2,
    }


def test_case_that_starts_passing_and_then_fails_is_newly_failing() -> None:
    vector = _report([_case("Q1", 1)])
    hybrid = _report([_case("Q1", None)])

    comparison = build_comparison(vector, hybrid)

    assert comparison["newly_failing_cases"] == ["Q1"]


def test_metric_delta_is_hybrid_minus_vector() -> None:
    vector = _report([], metrics={"mrr": 0.80})
    hybrid = _report([], metrics={"mrr": 0.90})

    comparison = build_comparison(vector, hybrid)

    assert comparison["metrics"]["mrr"]["vector"] == 0.80
    assert comparison["metrics"]["mrr"]["hybrid"] == 0.90
    assert comparison["metrics"]["mrr"]["delta"] == pytest.approx(0.10)


def test_latency_ratio_is_hybrid_over_vector() -> None:
    vector = _report([], latency_ms={"mean": 5.0, "p50": 4.5, "p95": 8.0})
    hybrid = _report([], latency_ms={"mean": 10.0, "p50": 9.0, "p95": 16.0})

    comparison = build_comparison(vector, hybrid)

    assert comparison["latency_ms"]["mean"]["ratio"] == pytest.approx(2.0)
    assert comparison["latency_ms"]["mean"]["delta"] == pytest.approx(5.0)


def test_headline_cases_omitted_when_not_present_in_either_report() -> None:
    vector = _report([_case("Q1", 1)])
    hybrid = _report([_case("Q1", 1)])

    comparison = build_comparison(vector, hybrid)

    assert comparison["headline_cases"] == {}
