"""What a run will cost, before anything is spent.

Pure computation over the request: no network, no model, no credentials. The
numbers come from the cost guidance the bundle this tool grew out of carried as
prose -- turning that into something callable is the point, because knowledge a
caller has to read and apply by hand is knowledge that stays outside the tool.

It is an ESTIMATE and says so in its own output. A run that gathers an unusually
large or small amount of evidence will land outside these numbers, and the honest
thing is to publish the basis rather than a single confident figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

DEPTHS = ("low", "medium", "high")


@dataclass(frozen=True)
class DepthProfile:
    """What one depth setting is expected to do."""

    depth: str
    sources: int
    seconds: int
    tokens_in: int
    tokens_out: int


PROFILES: dict[str, DepthProfile] = {
    "low": DepthProfile("low", sources=8, seconds=60, tokens_in=6_000, tokens_out=1_500),
    "medium": DepthProfile("medium", sources=18, seconds=150, tokens_in=14_000, tokens_out=3_200),
    "high": DepthProfile("high", sources=34, seconds=300, tokens_in=26_000, tokens_out=5_500),
}

#: US dollars per thousand tokens. Deliberately a single blended figure rather
#: than a per-provider table: a table nobody updates is worse than an estimate
#: that admits it is one.
COST_PER_1K_IN = Decimal("0.003")
COST_PER_1K_OUT = Decimal("0.015")


def estimate_run(
    *, depth: str = "medium", claims: int | None = None, backend: str = "perplexity"
) -> dict[str, Any]:
    """Estimate one run. ``claims`` scales the estimate for a fact-check."""
    if depth not in PROFILES:
        from research_core.errors import UsageError

        raise UsageError(
            f"There is no depth {depth!r}.",
            f"Depths: {', '.join(DEPTHS)}.",
        )

    profile = PROFILES[depth]
    # Claims are verified independently, so a fact-check scales with how many
    # there are -- but they share the gathered evidence, so it is not linear.
    scale = 1.0 if not claims else 1.0 + 0.6 * (claims - 1)
    tokens_in = int(profile.tokens_in * scale)
    tokens_out = int(profile.tokens_out * scale)
    cost = (
        Decimal(tokens_in) / 1000 * COST_PER_1K_IN + Decimal(tokens_out) / 1000 * COST_PER_1K_OUT
    ).quantize(Decimal("0.0001"))

    return {
        "depth": depth,
        "backend": backend,
        "claims": claims,
        "estimated_sources": int(profile.sources * (1 if not claims else 1)),
        "estimated_seconds": int(profile.seconds * scale),
        "estimated_tokens_in": tokens_in,
        "estimated_tokens_out": tokens_out,
        "estimated_cost_usd": str(cost),
        "basis": (
            f"depth={depth} profile, scaled for {claims} claims"
            if claims
            else f"depth={depth} profile"
        ),
        "is_estimate": True,
        "caveat": (
            "An estimate from the request alone. A question whose evidence is "
            "unusually plentiful or unusually scarce will land outside these "
            "numbers; the run's own run.json records what was actually spent."
        ),
    }
