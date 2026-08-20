"""Tests for the eval runner's pre-flight configuration guard — pure, no
DB. Confirms `RETRIEVAL_TOP_K` below what the report needs for Recall@5
fails fast with a clear error instead of silently reporting a capped
value as if it were a true top-5 measurement (flagged in code review).
"""

import pytest

from agentic_learning_platform.evals.runner import EvalConfigurationError, validate_top_k


@pytest.mark.parametrize("top_k", [0, 1, 3, 4])
def test_rejects_top_k_below_five(top_k: int) -> None:
    with pytest.raises(EvalConfigurationError, match="retrieval_top_k"):
        validate_top_k(top_k)


@pytest.mark.parametrize("top_k", [5, 6, 10])
def test_accepts_top_k_five_or_above(top_k: int) -> None:
    validate_top_k(top_k)  # must not raise
