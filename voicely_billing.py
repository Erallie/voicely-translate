"""Exact arithmetic helpers for Voicely usage accounting."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


MICRO_USD_PER_USD = Decimal(1_000_000)


def token_cost_microusd(
    input_tokens: int,
    output_tokens: int,
    input_usd_per_million: Decimal,
    output_usd_per_million: Decimal,
    multiplier: Decimal,
) -> int:
    """Calculate a token charge without binary floating-point drift."""
    raw = (
        Decimal(max(0, input_tokens)) * input_usd_per_million
        + Decimal(max(0, output_tokens)) * output_usd_per_million
    ) * multiplier
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
