"""Aggregates an `EvalRun` into the final report structure: the
`eval_results.json` payload and a human-readable terminal summary.

`baseline: "vector_only"` is stamped explicitly so a future PR-006 (Hybrid
Retrieval) run can be told apart unambiguously when comparing
`eval_results.json` files side by side.
"""

import json
import subprocess
from datetime import UTC, datetime
from typing import Any

from agentic_learning_platform.evals.dataset import GOLDEN_DATASET_PATH
from agentic_learning_platform.evals.metrics import (
    citation_is_correct,
    groundedness_score,
    latency_stats,
    mean_reciprocal_rank,
    rate,
    recall_at_k,
)
from agentic_learning_platform.evals.runner import EvalRun

BASELINE_LABEL = "vector_only"


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def build_report(run: EvalRun) -> dict[str, Any]:
    answerable = [sample for sample in run.samples if sample.case.expected_answerable]
    unanswerable = [sample for sample in run.samples if not sample.case.expected_answerable]

    ranks = [sample.rank for sample in answerable]
    citation_flags = [
        citation_is_correct(
            sample.has_sufficient_evidence,
            sample.citations,
            sample.case.expected_source,
            sample.case.expected_pages,
        )
        for sample in answerable
    ]
    grounded_scores = [
        groundedness_score(sample.answer_text, sample.evidence_contents)
        for sample in answerable
        if sample.has_sufficient_evidence
    ]

    metrics = {
        "recall_at_1": recall_at_k(ranks, 1),
        "recall_at_3": recall_at_k(ranks, 3),
        "recall_at_5": recall_at_k(ranks, 5),
        "mrr": mean_reciprocal_rank(ranks),
        "citation_accuracy": rate(citation_flags),
        "no_evidence_accuracy": rate([not s.has_sufficient_evidence for s in unanswerable]),
        "false_positive_rate": rate([s.has_sufficient_evidence for s in unanswerable]),
        "false_negative_rate": rate([not s.has_sufficient_evidence for s in answerable]),
        "groundedness_local": (
            sum(grounded_scores) / len(grounded_scores) if grounded_scores else None
        ),
    }

    return {
        "baseline": BASELINE_LABEL,
        "dataset": _dataset_filename(),
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "config": {
            "retrieval_strategy": BASELINE_LABEL,
            "runtime_mode": run.settings.runtime_mode,
            "retrieval_top_k": run.settings.retrieval_top_k,
            "retrieval_score_threshold": run.settings.retrieval_score_threshold,
            "embedding_model": run.adapters.embedding.get_model_name(),
            "embedding_dimension": run.adapters.embedding.get_dimension(),
        },
        "num_cases": len(run.dataset),
        # A case count alone overstates dataset diversity: some cases share
        # the exact same question text by design (e.g. a cross-course pair
        # that intentionally asks the identical question against two
        # different scopes — see docs/architecture.md's PR-005 section on
        # G1/A1). This is the actual count of distinct question strings.
        "num_unique_questions": len({case.question for case in run.dataset}),
        "num_answerable": len(answerable),
        "num_unanswerable": len(unanswerable),
        "metrics": metrics,
        "latency_ms": latency_stats([sample.retrieval_latency_ms for sample in run.samples]),
        "per_case": [
            {
                "id": sample.case.id,
                "category": sample.case.category,
                "expected_answerable": sample.case.expected_answerable,
                "rank": sample.rank,
                "has_sufficient_evidence": sample.has_sufficient_evidence,
                "citation_correct": citation_is_correct(
                    sample.has_sufficient_evidence,
                    sample.citations,
                    sample.case.expected_source,
                    sample.case.expected_pages,
                ),
                "retrieval_latency_ms": round(sample.retrieval_latency_ms, 2),
            }
            for sample in run.samples
        ],
    }


def _dataset_filename() -> str:
    return GOLDEN_DATASET_PATH.name


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)


def render_summary(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    latency = report["latency_ms"]
    config = report["config"]

    def fmt(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.3f}"

    lines = [
        f"PR-005 RAG Eval — baseline={report['baseline']}",
        f"dataset={report['dataset']}  commit={report['git_commit']}"
        f"  generated_at={report['generated_at']}",
        f"retrieval_strategy={config['retrieval_strategy']}  "
        f"runtime_mode={config['runtime_mode']}  "
        f"embedding={config['embedding_model']} (dim={config['embedding_dimension']})  "
        f"top_k={config['retrieval_top_k']}  threshold={config['retrieval_score_threshold']}",
        f"cases: {report['num_cases']} total, {report['num_unique_questions']} unique questions "
        f"({report['num_answerable']} answerable, {report['num_unanswerable']} no-evidence)",
        "",
        "Retrieval quality (raw, pre-threshold):",
        f"  Recall@1 = {fmt(metrics['recall_at_1'])}",
        f"  Recall@3 = {fmt(metrics['recall_at_3'])}",
        f"  Recall@5 = {fmt(metrics['recall_at_5'])}",
        f"  MRR      = {fmt(metrics['mrr'])}",
        "",
        "End-to-end quality (post-threshold):",
        f"  Citation Accuracy    = {fmt(metrics['citation_accuracy'])}",
        f"  No-Evidence Accuracy = {fmt(metrics['no_evidence_accuracy'])}",
        f"  False Positive Rate  = {fmt(metrics['false_positive_rate'])}",
        f"  False Negative Rate  = {fmt(metrics['false_negative_rate'])}",
        f"  Groundedness (local) = {fmt(metrics['groundedness_local'])}",
        "    (expected ~1.0 by construction: local mode is EXTRACTIVE, not generative —",
        "     this is not a measure of LLM answer quality; see docs/architecture.md)",
        "",
        "Retrieval latency (ms):",
        f"  mean = {latency['mean']:.2f}  p50 = {latency['p50']:.2f}  p95 = {latency['p95']:.2f}",
    ]
    return "\n".join(lines)
