"""Pure, dependency-free metric calculations for the RAG eval harness.

Deliberately not using an external eval framework (Ragas, DeepEval, ...):
Recall@K, MRR, and simple confusion-matrix rates are a handful of
straightforward formulas over data this codebase already produces
(`SearchResult.source_name`/`page_number`, `QueryAnswer.has_sufficient_evidence`)
— pulling in a framework's runtime (and its own dependency tree) would add
weight and a semantic-eval surface (LLM-as-judge) this PR explicitly does
not need yet (see docs/architecture.md's PR-005 section).
"""

from collections.abc import Sequence

from agentic_learning_platform.domain.models import Citation, SearchResult

_EXTRACTIVE_JOIN_SEPARATOR = "\n\n---\n\n"


def find_rank(
    results: Sequence[SearchResult], expected_source: str | None, expected_pages: Sequence[int]
) -> int | None:
    """1-indexed rank of the first result matching `(expected_source, a page
    in expected_pages)`, or None if no result in `results` matches at all."""
    if not expected_source or not expected_pages:
        return None
    for index, result in enumerate(results, start=1):
        if result.source_name == expected_source and result.page_number in expected_pages:
            return index
    return None


def recall_at_k(ranks: Sequence[int | None], k: int) -> float | None:
    """Fraction of answerable cases whose expected evidence was found within
    the top `k` retrieved results. `None` (not `0.0`) when `ranks` is empty —
    the metric is undefined, not zero, with no answerable cases."""
    if not ranks:
        return None
    hits = sum(1 for rank in ranks if rank is not None and rank <= k)
    return hits / len(ranks)


def mean_reciprocal_rank(ranks: Sequence[int | None]) -> float | None:
    if not ranks:
        return None
    reciprocals = [1.0 / rank if rank is not None else 0.0 for rank in ranks]
    return sum(reciprocals) / len(reciprocals)


def citation_is_correct(
    has_sufficient_evidence: bool,
    citations: Sequence[Citation],
    expected_source: str | None,
    expected_pages: Sequence[int],
) -> bool:
    """A citation is only "correct" if the system actually claimed
    sufficient evidence AND at least one returned citation matches the
    expected source/page — a citation list is never inspected in isolation
    from the sufficiency decision that produced it."""
    if not has_sufficient_evidence or not expected_source or not expected_pages:
        return False
    return any(
        citation.source == expected_source and citation.page in expected_pages
        for citation in citations
    )


def rate(flags: Sequence[bool]) -> float | None:
    """Fraction of `flags` that are True. `None` when empty."""
    if not flags:
        return None
    return sum(1 for flag in flags if flag) / len(flags)


def groundedness_score(answer: str, evidence_contents: Sequence[str]) -> float:
    """Fraction of the answer's extractive segments (split on the same
    `"\\n\\n---\\n\\n"` separator `ExtractiveAnswerGeneratorAdapter` joins
    multiple pieces of evidence with) that appear verbatim among the
    retrieved evidence's own content.

    In `runtime_mode=local`, this is expected to always be 1.0: the
    extractive generator never paraphrases, it returns retrieved content
    verbatim, so there is nothing for it to hallucinate. Measuring it here
    is a sanity check on that construction, not a discovery — the same
    check on a future real-generation (Bedrock) answer would be genuinely
    informative, which is why it is defined generally rather than hardcoded
    to `1.0`.
    """
    if not answer:
        return 0.0
    segments = [segment for segment in answer.split(_EXTRACTIVE_JOIN_SEPARATOR) if segment]
    if not segments:
        return 0.0
    grounded = sum(1 for segment in segments if segment in evidence_contents)
    return grounded / len(segments)


def _percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Linear-interpolation percentile (the same convention numpy's default
    `interpolation="linear"` uses) — no new dependency for this alone."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]

    rank = (len(sorted_values) - 1) * (pct / 100)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    if lower == upper:
        return sorted_values[lower]
    fraction = rank - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def latency_stats(samples_ms: Sequence[float]) -> dict[str, float]:
    if not samples_ms:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0}
    sorted_samples = sorted(samples_ms)
    return {
        "mean": sum(sorted_samples) / len(sorted_samples),
        "p50": _percentile(sorted_samples, 50),
        "p95": _percentile(sorted_samples, 95),
    }
