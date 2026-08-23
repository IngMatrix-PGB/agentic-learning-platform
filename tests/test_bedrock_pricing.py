import pytest

from agentic_learning_platform.infrastructure.answer_generation.bedrock_pricing import (
    estimate_cost_usd,
)

_KNOWN_MODEL = "anthropic.claude-3-5-haiku-20241022-v1:0"


@pytest.mark.parametrize(
    ("input_tokens", "output_tokens", "expected_cost_usd"),
    [
        # (1000/1000)*0.0008 + (1000/1000)*0.004 — independently verified
        # by hand against the pricing table during adversarial review.
        (1000, 1000, 0.0048),
        # (500/1000)*0.0008 + (2000/1000)*0.004 — same verification, with
        # asymmetric input/output token counts, so a coefficient mix-up
        # (e.g. swapped input/output prices) would not go undetected.
        (500, 2000, 0.0084),
    ],
)
def test_estimate_cost_usd_matches_the_known_pricing_formula_exactly(
    input_tokens: int, output_tokens: int, expected_cost_usd: float
) -> None:
    cost = estimate_cost_usd(_KNOWN_MODEL, input_tokens=input_tokens, output_tokens=output_tokens)

    assert cost == pytest.approx(expected_cost_usd)


def test_estimate_cost_usd_is_none_for_an_unknown_model() -> None:
    cost = estimate_cost_usd("some.unlisted-model-id:0", input_tokens=100, output_tokens=100)

    assert cost is None


def test_estimate_cost_usd_is_none_when_input_tokens_are_missing() -> None:
    cost = estimate_cost_usd(_KNOWN_MODEL, input_tokens=None, output_tokens=100)

    assert cost is None


def test_estimate_cost_usd_is_none_when_output_tokens_are_missing() -> None:
    cost = estimate_cost_usd(_KNOWN_MODEL, input_tokens=100, output_tokens=None)

    assert cost is None
