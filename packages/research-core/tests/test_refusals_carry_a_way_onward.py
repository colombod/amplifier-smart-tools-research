"""A refusal is a response, and a response owes the caller a next move.

Hypermedia learned this the expensive way with `204 No Content`: a response
carrying no representation carries no links, so the client is stranded exactly
when it most needs direction. Ours had the same defect -- an error envelope and
nothing else.

This is the check we proposed the conformance kit adopt, applied to ourselves
first: EVERY response a tool can return, including an error, carries at least
one way onward.
"""

from __future__ import annotations

import json
import tempfile

import pytest
from research_core.backends.base import Evidence
from research_core.backends.scripted import ScriptedBackend
from research_core.errors import NoEvidence, SmartToolError
from research_core.reasoning import ScriptedReasoner


def _refuse_for_lack_of_evidence():
    """Drive a real refusal with no model, no network and no credential."""
    import deep_research

    with tempfile.TemporaryDirectory() as runs, pytest.raises(NoEvidence) as caught:
        deep_research.research(
            "a question whose evidence never arrives",
            backend=ScriptedBackend(
                Evidence(text="nothing found", sources=[], usage={}, backend="fixture")
            ),
            reasoner=ScriptedReasoner(
                json.dumps({"question": "q"}),
                json.dumps({"brief": "b", "report": "r", "confidence": "low"}),
            ),
            runs_dir=runs,
            quiet=True,
            depth="low",
        )
    return caught.value


def test_a_refusal_is_not_a_dead_end():
    assert _refuse_for_lack_of_evidence().affordances, (
        "a refusal with no affordances strands the caller -- the 204 defect"
    )


def test_every_way_onward_is_free_and_needs_no_credential():
    # A caller that has just been refused may be on a host with nothing
    # configured. Offering it something it cannot run is offering it nothing.
    for affordance in _refuse_for_lack_of_evidence().affordances:
        assert affordance.cost_usd == "0.00", f"{affordance.name} costs money"
        assert not affordance.needs_credentials, f"{affordance.name} needs a credential"


def test_both_consumption_paths_are_first_class():
    # The library is the tool. A caller using it should never have to shell out
    # to follow its own tool's advice.
    for affordance in _refuse_for_lack_of_evidence().affordances:
        assert affordance.command.strip(), f"{affordance.name} has no CLI form"
        assert affordance.call.strip(), f"{affordance.name} has no library form"


def test_the_refusal_points_at_its_own_run():
    # The run record survives the refusal, and it is the most specific thing the
    # tool knows. A refusal that does not mention it makes the caller guess.
    failure = _refuse_for_lack_of_evidence()
    assert any(a.name == "status" for a in failure.affordances)
    assert any("dr-" in a.command for a in failure.affordances)


def test_the_base_error_defaults_to_an_empty_list_not_none():
    # So every caller can iterate without a None check, which is how a field
    # meant to be read ends up unread.
    assert SmartToolError("m", "r").affordances == []


def test_the_vocabulary_carries_content_this_tool_will_never_produce():
    """The generality test, and the only one that matters for the pattern.

    A vocabulary invented for research reports that needs special-casing to
    describe a thumbnail is research plumbing with a general name on it. So:
    express an image response with the same types, and check nothing strains.
    """
    from research_core.affordances import Affordance, Completeness, Navigation, Rung

    image = Navigation(
        affordances=[
            Affordance(
                name="fetch",
                does="retrieve this image at a chosen rung",
                command="image-tool fetch img-8f2e --rung original",
                call="image_tool.fetch('img-8f2e', rung='original')",
                returns="bytes",
                bytes=21_400_000,
            ),
            Affordance(
                name="describe",
                does="caption the image",
                command="image-tool describe img-8f2e",
                call="image_tool.describe('img-8f2e')",
                returns="text",
                cost_usd="0.004",
                needs_credentials=True,
            ),
        ],
        ladder=[
            Rung("thumbnail", "enough to see what it is", bytes=18_400),
            Rung("web", "enough to show someone", bytes=240_000),
            Rung("original", "the file itself", bytes=21_400_000),
        ],
    )

    document = image.to_dict()
    assert document["ladder"][0]["bytes"] == 18_400
    assert document["ladder"][-1]["bytes"] == 21_400_000

    # The point of the whole design: an agent can decide it does NOT want 21MB
    # without first fetching 21MB.
    affordable = [r for r in document["ladder"] if (r["bytes"] or 0) < 1_000_000]
    assert len(affordable) == 2

    # And a caller on an unconfigured host can tell which actions it may take.
    free_actions = [a for a in document["affordances"] if not a["needs_credentials"]]
    assert [a["name"] for a in free_actions] == ["fetch"]

    # Partial-ness is expressible for bytes exactly as it is for lines.
    assert (
        Completeness(complete=False, returned=18_400, total=21_400_000).to_dict()["complete"]
        is False
    )
