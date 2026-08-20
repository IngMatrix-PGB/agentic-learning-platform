"""Compares two eval reports produced by the SAME harness/formulas
(``evals/report.py``) — e.g. ``eval_results/baseline_vector_only.v1.json``
vs. ``eval_results/hybrid_retrieval.v1.json``. Never recomputes any metric:
only reads the two JSON payloads and diffs already-computed numbers.

Entrypoint: ``uv run python -m agentic_learning_platform.evals.compare_reports``
(wrapped by ``make eval-compare``), defaulting to the two files above. Writes
``eval_results/comparison_vector_vs_hybrid.v1.json`` and prints a
human-readable summary table + per-case transition lists.
"""

import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_VECTOR_PATH = Path("eval_results") / "baseline_vector_only.v1.json"
DEFAULT_HYBRID_PATH = Path("eval_results") / "hybrid_retrieval.v1.json"
DEFAULT_OUTPUT_PATH = Path("eval_results") / "comparison_vector_vs_hybrid.v1.json"

_METRIC_KEYS = [
    "recall_at_1",
    "recall_at_3",
    "recall_at_5",
    "mrr",
    "citation_accuracy",
    "no_evidence_accuracy",
    "false_positive_rate",
    "false_negative_rate",
]

_LATENCY_STATS = ["mean", "p50", "p95"]

# Called out explicitly per the PR-006 spec — never given special-case
# retrieval logic, only special-case reporting visibility.
HEADLINE_CASE_IDS = [
    "C1-sla-synonym",
    "C2-support-tiers-synonym",
    "D1-incident-ambiguous",
    "D2-problem-ambiguous",
]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _delta(vector_value: float | None, hybrid_value: float | None) -> float | None:
    if vector_value is None or hybrid_value is None:
        return None
    return hybrid_value - vector_value


def _ratio(vector_value: float, hybrid_value: float) -> float | None:
    if vector_value == 0:
        return None
    return hybrid_value / vector_value


def build_comparison(
    vector_report: dict[str, Any], hybrid_report: dict[str, Any]
) -> dict[str, Any]:
    v_metrics = vector_report["metrics"]
    h_metrics = hybrid_report["metrics"]
    metrics_table = {
        key: {
            "vector": v_metrics.get(key),
            "hybrid": h_metrics.get(key),
            "delta": _delta(v_metrics.get(key), h_metrics.get(key)),
        }
        for key in _METRIC_KEYS
    }

    v_latency = vector_report["latency_ms"]
    h_latency = hybrid_report["latency_ms"]
    latency_table = {
        stat: {
            "vector": v_latency[stat],
            "hybrid": h_latency[stat],
            "delta": h_latency[stat] - v_latency[stat],
            "ratio": _ratio(v_latency[stat], h_latency[stat]),
        }
        for stat in _LATENCY_STATS
    }

    v_by_id = {case["id"]: case for case in vector_report["per_case"]}
    h_by_id = {case["id"]: case for case in hybrid_report["per_case"]}

    improved_cases: list[str] = []
    regressed_cases: list[str] = []
    unchanged_failures: list[str] = []
    newly_passing_cases: list[str] = []
    newly_failing_cases: list[str] = []

    for case_id, v_case in v_by_id.items():
        h_case = h_by_id.get(case_id)
        if h_case is None:
            continue
        v_rank: int | None = v_case["rank"]
        h_rank: int | None = h_case["rank"]

        if v_rank is None and h_rank is None:
            unchanged_failures.append(case_id)
        elif v_rank is None:
            newly_passing_cases.append(case_id)
        elif h_rank is None:
            newly_failing_cases.append(case_id)
        elif h_rank < v_rank:
            improved_cases.append(case_id)
        elif h_rank > v_rank:
            regressed_cases.append(case_id)

    headline_cases = {
        case_id: {
            "vector_rank": v_by_id[case_id]["rank"],
            "hybrid_rank": h_by_id[case_id]["rank"],
        }
        for case_id in HEADLINE_CASE_IDS
        if case_id in v_by_id and case_id in h_by_id
    }

    return {
        "vector_dataset": vector_report.get("dataset"),
        "hybrid_dataset": hybrid_report.get("dataset"),
        "metrics": metrics_table,
        "latency_ms": latency_table,
        "improved_cases": sorted(improved_cases),
        "regressed_cases": sorted(regressed_cases),
        "unchanged_failures": sorted(unchanged_failures),
        "newly_passing_cases": sorted(newly_passing_cases),
        "newly_failing_cases": sorted(newly_failing_cases),
        "headline_cases": headline_cases,
    }


def render_json(comparison: dict[str, Any]) -> str:
    return json.dumps(comparison, indent=2, ensure_ascii=False)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _fmt_delta(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.3f}"


def render_summary(comparison: dict[str, Any]) -> str:
    lines = [
        "Vector vs. Hybrid comparison",
        f"{'':22}{'VECTOR':>10}{'HYBRID':>10}{'DELTA':>10}",
    ]
    for key, row in comparison["metrics"].items():
        lines.append(
            f"{key:22}{_fmt(row['vector']):>10}{_fmt(row['hybrid']):>10}{_fmt_delta(row['delta']):>10}"
        )

    lines.append("")
    lines.append(f"{'latency (ms)':22}{'VECTOR':>10}{'HYBRID':>10}{'DELTA':>10}{'RATIO':>10}")
    for stat, row in comparison["latency_ms"].items():
        ratio = "n/a" if row["ratio"] is None else f"{row['ratio']:.2f}x"
        lines.append(
            f"{stat:22}{row['vector']:>10.2f}{row['hybrid']:>10.2f}"
            f"{row['delta']:>+10.2f}{ratio:>10}"
        )

    lines += [
        "",
        f"IMPROVED CASES ({len(comparison['improved_cases'])}): "
        + (", ".join(comparison["improved_cases"]) or "none"),
        f"REGRESSED CASES ({len(comparison['regressed_cases'])}): "
        + (", ".join(comparison["regressed_cases"]) or "none"),
        f"NEWLY PASSING ({len(comparison['newly_passing_cases'])}): "
        + (", ".join(comparison["newly_passing_cases"]) or "none"),
        f"NEWLY FAILING ({len(comparison['newly_failing_cases'])}): "
        + (", ".join(comparison["newly_failing_cases"]) or "none"),
        f"UNCHANGED FAILURES ({len(comparison['unchanged_failures'])}): "
        + (", ".join(comparison["unchanged_failures"]) or "none"),
        "",
        "Headline cases:",
    ]
    for case_id, ranks in comparison["headline_cases"].items():
        lines.append(
            f"  {case_id}: vector_rank={ranks['vector_rank']} hybrid_rank={ranks['hybrid_rank']}"
        )

    return "\n".join(lines)


def main() -> None:
    vector_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_VECTOR_PATH
    hybrid_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_HYBRID_PATH

    comparison = build_comparison(_load(vector_path), _load(hybrid_path))

    DEFAULT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT_PATH.write_text(render_json(comparison) + "\n")

    print(render_summary(comparison))
    print(f"\nFull comparison written to {DEFAULT_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
