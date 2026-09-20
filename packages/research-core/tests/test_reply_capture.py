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


def test_a_malformed_json_reply_is_repaired_with_the_specific_parse_error():
    """D6: an unescaped quote inside a string is genuinely-unparseable JSON,
    not prose-around-JSON -- and the old generic finding ("carried no JSON
    document... no prose around it") sent a model chasing the wrong defect.
    Real run dr-dd376b7d burned three attempts and $0.34 on exactly this:
    every rejected reply added a ```json fence (acting on the wrong
    instruction) and kept the one unescaped quote that actually broke it.

    This drives the real `run_stage` repair loop, not `extract_json` in
    isolation, so it proves the specific parse error actually reaches the
    next prompt.
    """
    # A literal, unescaped quote inside a string value -- the exact defect
    # from dr-dd376b7d ("... The only "package" source given ..."). This is
    # genuinely malformed JSON, not prose-around-JSON: the parser gets 22
    # characters in before it breaks.
    malformed = '{"report": "The only "package" source given here is fine"}'
    reasoner = _Scripted(malformed, json.dumps({"report": "ok"}))

    result = run_stage("synthesise", reasoner, "prompt", validate=lambda document: document)

    assert result.value == {"report": "ok"}
    repair_prompt = reasoner.asked[1]
    assert "REJECTED" in repair_prompt
    # The specific json.JSONDecodeError detail -- byte offset and expected
    # token -- must reach the next attempt, not a generic complaint.
    assert "Expecting" in repair_prompt or "delimiter" in repair_prompt, (
        "the repair must carry the parser's own diagnosis, not a guess"
    )
    # And the generic, WRONG finding ("carried no JSON document... no prose
    # around it") must not be what a genuinely-malformed-but-present JSON
    # document gets told -- that finding caused the model to add a ```json
    # fence three times while the actual defect (the unescaped quote) survived.
    assert "no prose around it" not in repair_prompt


def test_an_empty_or_prose_only_reply_still_gets_the_generic_finding():
    """The generic finding is correct when there is truly nothing JSON-shaped
    to point at -- D6's fix must not remove it for the case it is right for.
    """
    reasoner = _Scripted("I'd be happy to help! Here's my analysis.", json.dumps({"ok": True}))
    run_stage("synthesise", reasoner, "prompt", validate=lambda document: document)
    assert "no prose around it" in reasoner.asked[1]


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


def _writer(tmp_path):
    from research_core.writer import RunWriter

    return RunWriter(
        runs_dir=tmp_path,
        run_id="dr-test0001",
        tool="deep-research",
        query="q",
        depth="low",
        backend="perplexity",
        stages=("scope", "synthesise"),
        quiet=True,
    )


def _usage_on_disk(tmp_path):
    """Read run.json, because that is what a caller actually sees."""
    return json.loads((tmp_path / "dr-test0001" / "run.json").read_text())["usage"]


def test_cost_accumulates_across_stages_instead_of_being_overwritten(tmp_path):
    """Every run this tool ever reported under-stated what it cost.

    `record_usage` accumulated tokens and ASSIGNED cost, two lines apart, so a
    run reported whatever the LAST stage to record had spent. Run dr-82baa98f
    reported $1.008705 -- exactly the synthesise stage's three attempts summed,
    with scope's $0.031287 silently overwritten.

    Reading the code did not catch it. Summing attempts.json and comparing it to
    the reported total did, which is the only reason we know.
    """
    writer = _writer(tmp_path)
    writer.record_usage({"tokens_in": 100, "tokens_out": 10, "cost_usd": "0.031287"})
    writer.record_usage({"tokens_in": 900, "tokens_out": 90, "cost_usd": "1.008705"})

    usage = _usage_on_disk(tmp_path)
    assert usage["tokens_in"] == 1000, "tokens always accumulated; that half was fine"
    assert float(usage["cost_usd"]) == pytest.approx(1.039992), (
        "a run's cost must be the SUM of its stages, not whichever recorded last"
    )


def test_a_caller_can_see_what_it_paid_for_work_that_was_thrown_away(tmp_path):
    """ "Cost $1.01" and "cost $1.01, of which $0.66 was discarded" differ.

    Only the second lets a caller act -- lower the depth, change the question, or
    report that a stage is unreliable. The first reads like the price of the
    answer.
    """
    writer = _writer(tmp_path)
    writer.record_usage({"cost_usd": "0.031287", "attempts": 1, "attempts_discarded": 0})
    writer.record_usage(
        {
            "cost_usd": "1.008705",
            "attempts": 3,
            "attempts_discarded": 2,
            "discarded_cost_usd": "0.658962",
        }
    )

    usage = _usage_on_disk(tmp_path)
    assert usage["attempts"] == 4
    assert usage["attempts_discarded"] == 2
    assert float(usage["discarded_cost_usd"]) == pytest.approx(0.658962)
    # 63% of that run bought nothing, and the record now says so.
    assert float(usage["discarded_cost_usd"]) / float(usage["cost_usd"]) > 0.6


def test_a_captured_reply_is_the_reply_and_not_a_json_string_literal(tmp_path):
    """`raw/` promises "verbatim". json.dumps on a str is not verbatim.

    The first capture shipped wrote `"```json\\n{\\n  \\"brief\\": ..."` -- the
    reply wrapped in quotes with every newline escaped. Harmless for an SDK
    object, ruinous here: the whole point is to read a REJECTED reply and see its
    exact shape, and escaping is what hides the shape.
    """
    writer = _writer(tmp_path)
    reply = '```json\n{\n  "brief": "line one\\nline two"\n}\n```'

    path = writer.write_raw("synthesise-01-rejected.txt", reply)

    assert path.read_text(encoding="utf-8") == reply, "a str must be written as itself"
    assert not path.read_text(encoding="utf-8").startswith('"'), (
        "the reply was JSON-encoded rather than written verbatim"
    )
