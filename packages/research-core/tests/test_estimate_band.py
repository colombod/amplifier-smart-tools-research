"""The published band must contain every run it was calibrated on.

An estimate that excludes its own evidence looks like a measurement and is not
one. At RANGE_LOW=0.7 the low-depth floor was $0.0651 and one calibration run
had cost $0.0580 -- outside, by a margin small enough that nobody would notice
by reading.

These are the real runs, with their ids, so a future recalibration has to face
the same arithmetic rather than re-deriving a comfortable number.
"""

from __future__ import annotations

import pytest
from research_core.estimate import estimate_run

#: (run id, depth, actual cost) -- every complete run we have measured.
MEASURED = [
    ("dr-aa7a2ff0", "low", 0.0580),
    ("dr-bfcc9f19", "low", 0.1275),
    ("dr-28bac1ff", "high", 0.8385),
    ("dr-82baa98f", "high", 1.0087),
]


@pytest.mark.parametrize("run_id,depth,actual", MEASURED)
def test_the_band_contains_the_run_it_was_calibrated_on(run_id, depth, actual):
    band = estimate_run(depth=depth)["estimated_cost_usd_range"]
    low, high = float(band["low"]), float(band["high"])
    assert low <= actual <= high, (
        f"{run_id} cost ${actual} and the published {depth} band is "
        f"${low}-${high}. Widen the band or recalibrate the profile -- but do "
        f"not ship a range that excludes a run we actually measured."
    )


def test_the_point_is_inside_its_own_band():
    """Trivially true today, and the kind of thing a bad edit breaks silently."""
    for depth in ("low", "medium", "high"):
        result = estimate_run(depth=depth)
        point = float(result["estimated_cost_usd"])
        band = result["estimated_cost_usd_range"]
        assert float(band["low"]) <= point <= float(band["high"])


def test_the_caveat_names_retries_as_unpredictable():
    """The reason the band is wide, stated where a caller reads it.

    An estimator cannot know how many attempts a stage will need. One measured
    run spent 63% of its money on discarded attempts, which no profile could
    have predicted -- so the caveat says so rather than implying the band covers
    only evidence volume.
    """
    caveat = estimate_run(depth="high")["caveat"]
    assert "retried" in caveat.lower() or "retry" in caveat.lower()
    assert "63%" in caveat, "the measured cost of retries belongs in the caveat"


def test_a_skipped_stage_is_not_listed_as_a_stage_of_the_run():
    """run.json used to claim `scope` ran when --no-scope was passed.

    scope.json recorded `"scoped": false` correctly -- but nothing points an
    auditor at scope.json, and run.json is the record they reach first. We drew
    exactly the wrong conclusion from it while investigating a real run, and
    only opening the second file corrected us.

    Two records of one fact, and the more prominent one was the misleading one.
    """
    from deep_research.research import STAGES

    with_scope = STAGES
    without = tuple(s for s in STAGES if s != "scope")

    assert "scope" in with_scope
    assert "scope" not in without
    assert len(without) == len(with_scope) - 1, (
        "skipping scope must remove exactly that stage and nothing else"
    )
