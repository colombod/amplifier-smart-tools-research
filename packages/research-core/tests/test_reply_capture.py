"""A rejected reply is the one worth keeping.

A real run failed synthesis twice at $0.38 an attempt, and the replies were
discarded at the instant they became the only evidence of why. `raw/` is
documented as "the backend's own replies, verbatim, for audit" and held exactly
one file, for one stage, in deep-research -- and nothing at all in fact-check.

So the cause of that failure is permanently undiagnosable. These tests exist so
the next one is not.
"""

from __future__ import annotations

import json

import pytest
from research_core.reasoning import Thought
from research_core.staging import AttemptsExhausted, run_stage


class _Scripted:
    """A reasoner that says exactly what it is told to, in order."""

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.asked: list[str] = []

    def think(self, prompt: str, on_event=None) -> Thought:
        self.asked.append(prompt)
        text = self._replies.pop(0) if self._replies else ""
        return Thought(
            text=text, usage={"cost_usd": "0.38", "tokens_in": 9618, "tokens_out": 23711}
        )


def test_a_rejected_reply_is_handed_to_on_reply_verbatim():
    """The exact bytes, not a summary and not the exception message.

    This is the case we could not diagnose: the model replied with prose where a
    JSON document was required. Reading "no JSON document was found" tells you
    nothing about WHY. Reading what it actually said tells you everything.
    """
    prose = "I'd be happy to help! Here's my analysis of the sources...\n\nNo JSON here."
    reasoner = _Scripted(prose, json.dumps({"brief": "ok"}))
    seen: list[tuple[int, str, bool]] = []

    result = run_stage(
        "synthesise",
        reasoner,
        "prompt",
        validate=lambda document: document,
        on_reply=lambda attempt, text, accepted: seen.append((attempt, text, accepted)),
    )

    assert result.value == {"brief": "ok"}
    assert len(seen) == 2, "every attempt should be offered, not only the accepted one"

    attempt, text, accepted = seen[0]
    assert (attempt, accepted) == (1, False)
    assert text == prose, "the rejected reply must arrive VERBATIM, or it cannot be diagnosed"

    assert seen[1][0] == 2
    assert seen[1][2] is True


def test_every_reply_survives_even_when_the_stage_never_succeeds():
    """The total failure is the case most in need of evidence, and most likely to lose it."""
    replies = ("prose one", "prose two", "prose three")
    reasoner = _Scripted(*replies)
    seen: list[tuple[int, str, bool]] = []

    with pytest.raises(AttemptsExhausted):
        run_stage(
            "synthesise",
            reasoner,
            "prompt",
            validate=lambda document: document,
            max_attempts=3,
            on_reply=lambda attempt, text, accepted: seen.append((attempt, text, accepted)),
        )

    assert [text for _, text, _ in seen] == list(replies)
    assert not any(accepted for _, _, accepted in seen)


def test_an_empty_reply_is_still_recorded():
    """ "The reply was empty" is a different diagnosis from "the reply was prose".

    Both raise NoStructureFound and both cost the same money. Only the recorded
    text distinguishes a model that said nothing from one that said the wrong
    thing, and they have different fixes.
    """
    reasoner = _Scripted("", json.dumps({"ok": True}))
    seen: list[tuple[int, str, bool]] = []

    run_stage(
        "scope",
        reasoner,
        "prompt",
        validate=lambda document: document,
        on_reply=lambda attempt, text, accepted: seen.append((attempt, text, accepted)),
    )

    assert seen[0] == (1, "", False)


def test_capture_is_optional_so_a_library_caller_is_not_forced_to_take_it():
    """No on_reply, no crash. The hook is an offer, not a requirement."""
    reasoner = _Scripted("nonsense", json.dumps({"ok": True}))
    assert run_stage("scope", reasoner, "prompt", validate=lambda document: document).value == {
        "ok": True
    }
