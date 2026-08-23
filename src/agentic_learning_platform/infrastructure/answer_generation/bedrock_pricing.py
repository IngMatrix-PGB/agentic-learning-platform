"""Reference pricing data for estimating Bedrock generation cost.

This is versioned reference data, not business logic: AWS Bedrock pricing
changes independently of this codebase and is not guaranteed to stay
accurate. ``estimate_cost_usd`` returns ``None`` for any ``model_id`` not
listed here (or for missing token counts) — a request must never fail, and
a cost estimate must never be silently fabricated, because pricing is
unknown or stale.

Update this table when Bedrock pricing changes; there is no mechanism here
that fetches live pricing.
"""

# {model_id: (usd_per_1k_input_tokens, usd_per_1k_output_tokens)}
# Source: AWS Bedrock on-demand pricing, us-east-1, recorded at the time
# this file was last updated — always verify against the current AWS
# pricing page before relying on this for real cost tracking.
_PRICING_USD_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    "anthropic.claude-3-5-haiku-20241022-v1:0": (0.0008, 0.004),
}


def estimate_cost_usd(
    model_id: str, *, input_tokens: int | None, output_tokens: int | None
) -> float | None:
    """Best-effort cost estimate. Returns ``None`` (never raises, never
    guesses) when the model isn't in the pricing table or token counts are
    unavailable."""
    if input_tokens is None or output_tokens is None:
        return None
    pricing = _PRICING_USD_PER_1K_TOKENS.get(model_id)
    if pricing is None:
        return None
    input_price_per_1k, output_price_per_1k = pricing
    return (input_tokens / 1000) * input_price_per_1k + (output_tokens / 1000) * output_price_per_1k
