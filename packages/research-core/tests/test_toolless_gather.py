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

import pytest
from research_core import NoEvidence
from research_core.backends.agent import AgentBackend
from research_core.backends.base import Budget
from research_core.engine import TurnResult


@pytest.fixture
def budget() -> Budget:
    return Budget(depth="low", max_sources=8, timeout_ms=1000)


def _turn(monkeypatch, *, tool_calls: int, text: str) -> None:
    """Replace the engine turn. No model, no credential, no spend."""
    import research_core.engine as engine

    def fake_run_turn(prompt, **kwargs):
        return TurnResult(text=text, usage={}, provider="fake", tool_calls=tool_calls)

    monkeypatch.setattr(engine, "run_turn", fake_run_turn)
    monkeypatch.setattr(engine, "preflight", lambda **kw: "fake")


REPLY = (
    '{"findings": "The capital is Lisbon [1].", '
    '"sources": [{"url": "https://en.wikipedia.org/wiki/Lisbon", "title": "Lisbon"}], '
    '"confidence": "high"}'
)


def test_a_gather_that_called_no_tool_is_refused(monkeypatch, budget):
    _turn(monkeypatch, tool_calls=0, text=REPLY)
    with pytest.raises(NoEvidence) as excinfo:
        AgentBackend().gather("anything", budget)
    assert "without calling a single tool" in str(excinfo.value)
    # the remedy must name the likely cause, because the engine's own failure
    # is a line on stderr nobody reads
    assert "failed to load" in excinfo.value.remedy


def test_the_refusal_fires_even_though_the_reply_carried_a_source(monkeypatch, budget):
    # The whole point: a plausible source was present, which is exactly why
    # every other guard let it through.
    _turn(monkeypatch, tool_calls=0, text=REPLY)
    with pytest.raises(NoEvidence):
        AgentBackend().gather("anything", budget)


def test_a_gather_that_used_tools_is_returned(monkeypatch, budget):
    _turn(monkeypatch, tool_calls=3, text=REPLY)
    evidence = AgentBackend().gather("anything", budget)
    assert evidence.sources[0].url == "https://en.wikipedia.org/wiki/Lisbon"


def test_the_counter_comes_from_the_display_not_from_a_guess():
    # tool_calls is incremented by _Display on a real engine event, so the
    # count is the engine's own report rather than anything we inferred.
    import asyncio

    from research_core.engine import _Display

    display = _Display(None)
    assert display.tool_calls == 0
    asyncio.run(display.emit({"type": "tool/started", "name": "web_search"}))
    asyncio.run(display.emit({"type": "tool/completed", "name": "web_search"}))
    asyncio.run(display.emit({"type": "irrelevant"}))
    assert display.tool_calls == 1
