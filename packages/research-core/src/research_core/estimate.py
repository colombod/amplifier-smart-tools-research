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


#: CALIBRATED AGAINST REAL RUNS, because the first numbers were guesses dressed
#: as arithmetic. Every measured run exceeded its estimate -- not one came in
#: under -- and the miss grew with depth:
#:
#:     depth  old estimate   observed            ratio
#:     low    $0.0405        $0.0580 - $0.1275   1.4x - 3.1x
#:     high   $0.1605        $0.8385 - $1.0087   5.2x - 6.3x
#:
#: Observed source counts were roughly double the profile at low (15 against 8)
#: and two to three times at high (69 and 98 against 34), with wall-clock
#: similarly over. The profiles below are scaled to the observed MEAN of each
#: depth. `medium` has no observations at all and is interpolated -- said out
#: loud rather than presented as measured.
PROFILES: dict[str, DepthProfile] = {
    "low": DepthProfile("low", sources=15, seconds=100, tokens_in=13_000, tokens_out=3_600),
    "medium": DepthProfile("medium", sources=40, seconds=350, tokens_in=45_000, tokens_out=12_000),
    "high": DepthProfile("high", sources=84, seconds=720, tokens_in=140_000, tokens_out=42_000),
}

#: How far either side of the point a run may reasonably land. Not invented: the
#: low-depth runs spanned 2.2x between themselves on the SAME depth setting, and
#: a stage that retries is billed for every attempt -- one measured run spent 63%
#: of its money on work it discarded. A single number implies a precision nobody
#: can deliver, so the estimate publishes a band and names why it is wide.
#: 0.6, not 0.7, and the difference is the whole point: at 0.7 the published
#: band EXCLUDED one of the four runs it was calibrated on ($0.0580 against a
#: floor of $0.0651). A band that does not contain its own evidence is worse
#: than no band, because it looks like a measurement.
RANGE_LOW = Decimal("0.6")
RANGE_HIGH = Decimal("2.2")

#: Runs behind the calibration. Small, and stated rather than hidden, because a
#: caller deciding whether to trust this number deserves to know it rests on
#: single digits.
CALIBRATION_RUNS = 4

#: US dollars per thousand tokens. Deliberately a single blended figure rather
#: than a per-provider table: a table nobody updates is worse than an estimate
#: that admits it is one.
COST_PER_1K_IN = Decimal("0.003")
COST_PER_1K_OUT = Decimal("0.015")


#: What skipping the question-sharpening stage actually costs, measured over six
#: interleaved live runs (evaluation/TUNING-LOG.md entry 006): scope on averaged
#: $0.5463, scope off $0.3996, with non-overlapping ranges. A caller that passes
#: --no-scope pays 0.7315 of what it would otherwise pay.
#:
#: NOTE THE DIRECTION, because we got it wrong in prose first: the run costs ~37%
#: MORE with scope than without, which is a ~27% SAVING when you turn it off.
#: Those are the same measurement and different numbers, and quoting the larger
#: one as the saving overstates it by ten points.
NO_SCOPE_COST_RATIO = Decimal("0.7315")


def estimate_run(
    *,
    depth: str = "medium",
    claims: int | None = None,
    backend: str = "perplexity",
    scope: bool = True,
) -> dict[str, Any]:
    """Estimate one run. ``claims`` scales the estimate for a fact-check.

    ``scope`` models the question-sharpening stage, because an estimator that
    cannot price the decision a caller is about to make is answering a question
    nobody asked. Two independent agents hit that wall in testing.
    """
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
    cost = Decimal(tokens_in) / 1000 * COST_PER_1K_IN + Decimal(tokens_out) / 1000 * COST_PER_1K_OUT
    if not scope:
        cost *= NO_SCOPE_COST_RATIO
        tokens_in = int(tokens_in * float(NO_SCOPE_COST_RATIO))
        tokens_out = int(tokens_out * float(NO_SCOPE_COST_RATIO))
    cost = cost.quantize(Decimal("0.0001"))
    low = (cost * RANGE_LOW).quantize(Decimal("0.0001"))
    high = (cost * RANGE_HIGH).quantize(Decimal("0.0001"))

    return {
        "depth": depth,
        "backend": backend,
        "claims": claims,
        "estimated_sources": int(profile.sources * (1 if not claims else 1)),
        "estimated_seconds": int(profile.seconds * scale),
        "estimated_tokens_in": tokens_in,
        "estimated_tokens_out": tokens_out,
        "estimated_cost_usd": str(cost),
        "scope": scope,
        # A BAND, NOT A POINT. Two runs at the SAME depth setting spanned 2.2x
        # between themselves, and a stage that retries is billed for every
        # attempt -- one measured run spent 63% of its money on discarded work.
        # An estimator cannot know how many attempts a stage will need, so a
        # single figure would promise a precision nobody can deliver.
        "estimated_cost_usd_range": {"low": str(low), "high": str(high)},
        "calibration_runs": CALIBRATION_RUNS,
        "basis": (
            (
                f"depth={depth} profile, scaled for {claims} claims"
                if claims
                else f"depth={depth} profile"
            )
            + (
                ""
                if scope
                else f", x{NO_SCOPE_COST_RATIO} for --no-scope (measured, TUNING-LOG 006)"
            )
        ),
        "is_estimate": True,
        "caveat": (
            "An estimate from the request alone, calibrated against "
            f"{CALIBRATION_RUNS} real runs -- single digits, so treat the point "
            "figure as the middle of the range rather than a promise. Two runs "
            "at the same depth spanned 2.2x between themselves. A stage that "
            "fails validation is retried AND BILLED FOR EVERY ATTEMPT, which no "
            "estimate can predict: one measured run spent 63% of its money on "
            "work it discarded. The run's own run.json records what was "
            "actually spent, including attempts_discarded and "
            "discarded_cost_usd."
        ),
    }
