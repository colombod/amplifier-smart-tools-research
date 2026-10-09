"""A gather that called no tool is refused, not returned.

The defect this guards lived through three milestones and no test could see
it, because every test supplied evidence through a scripted seam. With
`tool-web` silently failing to load, the agent answered from memory and
recorded URLs it never opened as sources -- one live run said in its own
words "No live access to the two listed sources" while two sat in the record.

It passed every downstream check because a source was PRESENT. The only
evidence that search actually happened is that search happened.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from research_core import NoEvidence
from research_core.backends.agent import AgentBackend
from research_core.backends.base import Budget
from research_core.engine import TurnResult
from research_core.parsing import extract_json


@pytest.fixture
def budget() -> Budget:
    return Budget(depth="low", max_sources=8, timeout_ms=1000)


def _turn(monkeypatch, *, tool_calls: int) -> None:
    """Replay a recorded real turn, not a hand-written Agent response."""
    import research_core.engine as engine

    recording = json.loads(
        (Path(__file__).parent / "fixtures" / "agent-v022-events.json").read_text()
    )
    result = recording["zero_tool_result" if tool_calls == 0 else "gather_result"]
    result = {
        **result,
        "tool_successes": 0
        if tool_calls == 0
        else sum(
            e["type"] == "tool_result" and e["payload"]["resolution"]["outcome"] == "completed"
            for e in recording["events"]
        ),
    }
    assert extract_json(result["text"])["sources"], "recording must carry the source being refused"

    def replay_run_turn(prompt, **kwargs):
        return TurnResult(**result)

    monkeypatch.setattr(engine, "run_turn", replay_run_turn)
    monkeypatch.setattr(engine, "preflight", lambda **kw: "fake")


def test_a_gather_that_called_no_tool_is_refused(monkeypatch, budget):
    _turn(monkeypatch, tool_calls=0)
    with pytest.raises(NoEvidence) as excinfo:
        AgentBackend().gather("anything", budget)
    assert "without calling a single tool" in str(excinfo.value)
    # the remedy must name the likely cause, because the engine's own failure
    # is a line on stderr nobody reads
    assert "failed to load" in excinfo.value.remedy


def test_the_refusal_fires_even_though_the_reply_carried_a_source(monkeypatch, budget):
    # The whole point: a plausible source was present, which is exactly why
    # every other guard let it through.
    _turn(monkeypatch, tool_calls=0)
    with pytest.raises(NoEvidence):
        AgentBackend().gather("anything", budget)


def test_a_gather_that_used_tools_is_returned(monkeypatch, budget):
    _turn(monkeypatch, tool_calls=1)
    evidence = AgentBackend().gather("anything", budget)
    assert evidence.sources[0].url == (
        "https://raw.githubusercontent.com/microsoft/amplifier-agent/v0.22.0/docs/python/reference.md"
    )


def test_the_counter_comes_from_the_display_not_from_a_guess():
    # The public event counter is tested against the real-runtime recording,
    # not against a fabricated event dictionary.
    from test_display_events import test_recorded_runtime_events_reach_progress_and_count_calls

    test_recorded_runtime_events_reach_progress_and_count_calls()
