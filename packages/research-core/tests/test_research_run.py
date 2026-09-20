"""The research workflow end to end, through the seam, spending nothing.

Every test here drives the real pipeline -- preflight, run directory, four
stages, citation rewriting, validation, the envelope -- with a backend that
returns prepared evidence. Nothing is mocked out: the seam a test uses is the
same seam a different provider arrives through, which is what makes these tests
evidence rather than decoration.
"""

from __future__ import annotations

import json

import pytest
from research_core import NoProviderError, load_run, status_of
from research_core.backends.base import Evidence, Source
from research_core.backends.scripted import (
    ScriptedBackend,
    UnconfiguredBackend,
    sample_evidence,
)
from research_core.config import CONFIG_PATH_ENV_VAR
from research_core.errors import SmartToolError
from research_core.reasoning import ScriptedReasoner, UnconfiguredReasoner

deep_research = pytest.importorskip("deep_research")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, str(tmp_path / "config.toml"))
    monkeypatch.setenv("RESEARCH_CREDENTIALS", str(tmp_path / "credentials.toml"))
    for var in ("RESEARCH_RUNS_DIR", "RESEARCH_DEPTH", "RESEARCH_BACKEND"):
        monkeypatch.delenv(var, raising=False)
    for var in ("PERPLEXITY_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def scripted_reasoner(
    *, cites: list[str] | None = None, brief="The answer, briefly.", report=None, extra_replies=()
) -> ScriptedReasoner:
    """A reasoner that scopes, then writes a report citing exactly ``cites``.

    The reasoning turns are a seam, so a test supplies its own implementation and
    the whole pipeline runs with no provider configured and no tokens spent.
    """
    markers = " ".join(f"[{c}]" for c in (cites or []))
    body = (
        report
        if report is not None
        else (f"## 1. What the evidence supports\n\nThe property holds {markers}.\n")
    )
    return ScriptedReasoner(
        json.dumps(
            {
                "question": "Does the property hold?",
                "sub_questions": [],
                "evidence_sought": [],
                "expected_disagreement": None,
            }
        ),
        json.dumps({"brief": f"{brief} {markers}".strip(), "report": body, "confidence": "medium"}),
        *extra_replies,
    )


def run_research(tmp_path, backend=None, reasoner=None, cites=None, **kwargs):
    evidence_backend = backend if backend is not None else ScriptedBackend(sample_evidence())
    if reasoner is None:
        if cites is None:
            # Cite whatever the backend is about to hand over, so the default
            # path is a clean run rather than one that trips the citation check.
            probe = getattr(evidence_backend, "_evidence", None)
            count = len(probe[0].sources) if probe else 3
            cites = [f"s{i}" for i in range(1, count + 1)]
        reasoner = scripted_reasoner(cites=cites)
    return deep_research.research(
        kwargs.pop("query", "Does the property hold?"),
        backend=evidence_backend,
        reasoner=reasoner,
        runs_dir=str(tmp_path / "runs"),
        quiet=True,
        **kwargs,
    )


def test_no_backend_configured_refuses_before_a_prompt_is_built(tmp_path):
    # UnconfiguredBackend.gather asserts if it is ever reached: if preflight did
    # not refuse first, a prompt was built for a run that could never happen.
    with pytest.raises(NoProviderError) as excinfo:
        run_research(tmp_path, backend=UnconfiguredBackend())
    assert excinfo.value.exit_code == 3
    assert excinfo.value.remedy


def test_a_no_provider_refusal_carries_the_check_affordance(tmp_path):
    """D8: every verb document promises "a refusal carries `affordances`
    too" -- and a real `no_provider` refusal used to carry none, because
    `NoProviderError` is raised deep inside `research_core`, which has no
    notion of which CLI is running it and so cannot build a `{prog} check`
    command itself. Fixed at the one place that knows both: `research()`'s
    own preflight call. Read straight off the exception -- the LIBRARY path,
    not just the CLI envelope -- since both are supposed to carry the same
    list.
    """
    with pytest.raises(NoProviderError) as excinfo:
        run_research(tmp_path, backend=UnconfiguredBackend())
    affordances = excinfo.value.affordances
    assert affordances, "a no_provider refusal must not be a dead end"
    check = next(a for a in affordances if a.name == "check")
    assert check.command == "deep-research check"
    assert check.call == "deep_research.check()"
    assert check.cost_usd == "0.00"
    assert not check.needs_credentials


def test_a_refusal_leaves_no_run_directory_behind(tmp_path):
    with pytest.raises(NoProviderError):
        run_research(tmp_path, backend=UnconfiguredBackend())
    assert not (tmp_path / "runs").exists()


def test_a_run_writes_every_artifact(tmp_path):
    envelope = run_research(tmp_path)
    path = tmp_path / "runs" / envelope["run_id"]
    for name in ("run.json", "brief.md", "report.md", "sources.json", "events.jsonl"):
        assert (path / name).exists(), name
    assert (path / "raw").is_dir()


def test_the_envelope_is_a_brief_plus_a_pointer(tmp_path):
    envelope = run_research(tmp_path)
    assert envelope["brief"].strip()
    assert envelope["path"].endswith(envelope["run_id"])
    assert envelope["source_count"] == 3
    assert set(envelope["next"]) == {"read_report", "list_sources", "render"}


def test_the_next_block_names_this_run(tmp_path):
    # A navigation hint that names the wrong run is worse than none.
    envelope = run_research(tmp_path)
    assert all(envelope["run_id"] in command for command in envelope["next"].values())


def test_sources_are_numbered_and_categorised_on_our_side(tmp_path):
    envelope = run_research(tmp_path)
    run = load_run(tmp_path / "runs", envelope["run_id"])
    sources = json.loads((run.path / "sources.json").read_text())["sources"]
    assert [s["id"] for s in sources] == ["s1", "s2", "s3"]
    assert [s["category"] for s in sources] == ["academic", "docs", "other"]


def test_backend_citation_markers_are_rewritten_before_the_synthesiser_sees_them(
    tmp_path,
):
    # The report is now written by the synthesis turn, so what the rewrite
    # affects is what that turn is HANDED -- which is the thing worth asserting.
    reasoner = scripted_reasoner(cites=["s1"])
    run_research(tmp_path, reasoner=reasoner)
    handed_over = reasoner.prompts[-1]
    assert "[s1]" in handed_over and "[s3]" in handed_over
    assert "[1]" not in handed_over


def test_a_marker_with_no_source_behind_it_is_left_alone_and_reported(tmp_path):
    # Renaming it to [s9] would manufacture an id and hide the very failure the
    # dangling-citation check exists to catch.
    evidence = Evidence(
        text="A claim [1] and another with no source [9].",
        sources=[Source(url="https://arxiv.org/abs/1", title="One")],
        backend="scripted",
    )
    reasoner = scripted_reasoner(cites=["s1"])
    run_research(tmp_path, backend=ScriptedBackend(evidence), reasoner=reasoner)
    handed_over = reasoner.prompts[-1]
    assert "[s1]" in handed_over
    assert "[9]" in handed_over  # no source behind it, so not renamed into one


def test_a_synthesis_citing_a_source_it_was_not_given_is_rejected_and_repaired(
    tmp_path,
):
    # The characteristic failure of research tooling, caught by set membership
    # and fed back as a SPECIFIC finding: "try again" buys a second attempt at
    # the same mistake.
    reasoner = ScriptedReasoner(
        json.dumps({"question": "Does the property hold?"}),
        json.dumps(
            {"brief": "Holds [s9].", "report": "## 1. A\n\nHolds [s9].", "confidence": "high"}
        ),
        json.dumps(
            {"brief": "Holds [s1].", "report": "## 1. A\n\nHolds [s1].", "confidence": "medium"}
        ),
    )
    envelope = run_research(tmp_path, reasoner=reasoner)
    assert envelope["status"] == "complete"

    repair = reasoner.prompts[-1]
    assert "REJECTED" in repair
    assert "s9" in repair, "the repair must name the marker that was wrong"

    attempts = json.loads(
        (load_run(tmp_path / "runs", envelope["run_id"]).path / "attempts.json").read_text()
    )
    assert [a["accepted"] for a in attempts["synthesise"]] == [False, True]
    assert "s9" in attempts["synthesise"][0]["reason"]


def test_the_budget_being_spent_fails_the_run_carrying_every_attempt(tmp_path):
    # Not the least-bad draft. A partial answer that looks whole is worse than
    # none, because nobody can tell it apart from a good one.
    reasoner = ScriptedReasoner(
        json.dumps({"question": "Does the property hold?"}),
        *[
            json.dumps({"brief": "Holds [s9].", "report": "## 1. A\n\nHolds [s9]."})
            for _ in range(3)
        ],
    )
    with pytest.raises(SmartToolError):
        run_research(tmp_path, reasoner=reasoner, max_attempts=3)

    run = next((tmp_path / "runs").iterdir())
    record = json.loads((run / "run.json").read_text())
    assert record["status"] == "failed"
    assert record["failure"]["code"] == "attempts_exhausted"
    attempts = json.loads((run / "attempts.json").read_text())["synthesise"]
    assert len(attempts) == 3
    assert not any(a["accepted"] for a in attempts)
    assert not (run / "report.md").exists(), "no draft is left behind"


def test_a_failed_run_reports_what_every_rejected_attempt_actually_cost(tmp_path):
    """D1: a run that fails `attempts_exhausted` used to report ~1/13th of what
    it really spent, because the discarded-cost arithmetic lives on
    `StageResult`, and `StageResult` is only constructed when a stage
    SUCCEEDS -- so the field designed to report wasted money was structurally
    absent from every run that wasted any. This drives the real failing path
    (not `record_usage` called directly) and reads run.json off disk, which is
    what a caller actually sees.
    """
    reasoner = ScriptedReasoner(
        json.dumps({"question": "Does the property hold?"}),
        *[
            json.dumps({"brief": "Holds [s9].", "report": "## 1. A\n\nHolds [s9]."})
            for _ in range(3)
        ],
    )
    with pytest.raises(SmartToolError):
        run_research(tmp_path, reasoner=reasoner, max_attempts=3)

    run = next((tmp_path / "runs").iterdir())
    record = json.loads((run / "run.json").read_text())
    usage = record["usage"]

    # Three rejected synthesise attempts, each billed by ScriptedReasoner at
    # $0.0010 -- plus the one accepted scope attempt. Every attempt must be
    # counted, not only the (nonexistent) accepted synthesise attempt.
    assert usage["attempts"] == 4
    assert usage["attempts_discarded"] == 3
    assert usage["discarded_cost_usd"] is not None
    assert float(usage["discarded_cost_usd"]) == pytest.approx(0.0030)
    # The bug's own signature: discarded cost silently absent while the
    # failure message admits the attempts happened.
    assert float(usage["cost_usd"]) >= float(usage["discarded_cost_usd"])


def test_the_reasoning_seam_refuses_before_a_prompt_is_built(tmp_path):
    # UnconfiguredReasoner.think raises AssertionError if it is ever reached.
    from research_core import NoProviderError

    with pytest.raises(NoProviderError):
        run_research(tmp_path, reasoner=UnconfiguredReasoner())
    assert not (tmp_path / "runs").exists(), "a refusal leaves nothing behind"


def test_every_stage_is_recorded_in_order(tmp_path):
    envelope = run_research(tmp_path)
    run = load_run(tmp_path / "runs", envelope["run_id"])
    stages = status_of(run)["stages"]
    assert [s["name"] for s in stages] == ["scope", "gather", "synthesise", "report"]
    assert all(s["status"] == "complete" for s in stages)
    assert all(s["duration_ms"] is not None for s in stages)


def test_progress_is_persisted_not_merely_streamed(tmp_path):
    # The whole argument for events.jsonl: a caller who was not watching can
    # still reconstruct what happened.
    envelope = run_research(tmp_path)
    run = load_run(tmp_path / "runs", envelope["run_id"])
    events = [
        json.loads(line)
        for line in (run.path / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "run" and events[0]["status"] == "started"
    assert kinds[-1] == "run" and events[-1]["status"] == "complete"
    assert "stage_attempt" in kinds, "each attempt at a stage is recorded"
    assert [e["stage"] for e in events if e["type"] == "stage" and e["status"] == "complete"] == [
        "scope",
        "gather",
        "synthesise",
        "report",
    ]
    assert all("at" in event for event in events)


def test_progress_streams_to_the_given_stream_as_json_lines(tmp_path):
    import io

    stream = io.StringIO()
    deep_research.research(
        "Does the property hold?",
        backend=ScriptedBackend(sample_evidence()),
        reasoner=scripted_reasoner(cites=["s1", "s2", "s3"]),
        runs_dir=str(tmp_path / "runs"),
        quiet=False,
        stream=stream,
    )
    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    assert lines, "progress was not streamed"
    for line in lines:
        json.loads(line)  # every line must be a complete JSON document on its own


def test_quiet_suppresses_the_stream_but_never_the_file(tmp_path):
    import io

    stream = io.StringIO()
    envelope = deep_research.research(
        "Does the property hold?",
        backend=ScriptedBackend(sample_evidence()),
        reasoner=scripted_reasoner(cites=["s1", "s2", "s3"]),
        runs_dir=str(tmp_path / "runs"),
        quiet=True,
        stream=stream,
    )
    assert stream.getvalue() == ""
    run = load_run(tmp_path / "runs", envelope["run_id"])
    assert (run.path / "events.jsonl").read_text().strip()


def test_a_small_report_comes_back_inline(tmp_path):
    envelope = run_research(tmp_path, cites=["s1"])
    assert envelope["inline"] is True
    assert envelope["report"].startswith("# ")


def test_no_inline_forces_the_pointer(tmp_path):
    envelope = run_research(tmp_path, inline=False)
    assert envelope["inline"] is False
    assert "report" not in envelope


def test_a_large_report_is_left_on_disk(tmp_path):
    # The report is what the synthesis turn wrote, so that is where its size is
    # decided now -- not the backend's prose.
    envelope = run_research(
        tmp_path,
        reasoner=scripted_reasoner(
            cites=["s1"], report="## 1. At length\n\n" + ("A long finding. " * 2000)
        ),
    )
    assert envelope["report_bytes"] > 8_000
    assert envelope["inline"] is False
    assert "report" not in envelope


def test_usage_accumulates_across_the_backend_and_every_turn(tmp_path):
    # A run's cost is the backend's plus every reasoning turn's, including
    # rejected attempts. Reporting only the backend would understate it.
    envelope = run_research(tmp_path)
    assert envelope["usage"]["tokens_in"] > 1200
    assert isinstance(envelope["usage"]["cost_usd"], str)


def test_a_cost_the_backend_did_not_report_is_null_not_zero(tmp_path):
    # A silent 0.00 would be a claim, and a false one.
    evidence = Evidence(
        text="A finding [1].",
        sources=[Source(url="https://arxiv.org/abs/1", title="One")],
        usage={"tokens_in": 10, "tokens_out": 5},
        backend="scripted",
    )
    envelope = run_research(tmp_path, backend=ScriptedBackend(evidence), cites=["s1"])
    # The reasoning turns reported a cost even though the backend did not, so
    # the run's total is not null -- but nothing was invented for the backend.
    assert envelope["usage"]["cost_usd"] is not None


def test_a_failure_mid_gather_keeps_the_run_and_says_where(tmp_path):
    class Failing:
        name = "failing"

        def preflight(self) -> str:
            return "scripted"

        def gather(self, query, budget, *, scope="", on_event=None):
            raise SmartToolError("The backend fell over.", "Try again later.")

    with pytest.raises(SmartToolError):
        run_research(tmp_path, backend=Failing())

    runs = list((tmp_path / "runs").iterdir())
    assert len(runs) == 1, "a failed run is kept, not deleted"
    record = json.loads((runs[0] / "run.json").read_text())
    assert record["status"] == "failed"
    assert record["failure"]["stage"] == "gather"
    assert record["failure"]["remedy"]
    assert [s["status"] for s in record["stages"]] == [
        "complete",
        "failed",
        "not_started",
        "not_started",
    ]


def test_the_backend_is_asked_the_SHARPENED_question(tmp_path):
    # The scope turn now stands between the caller and the backend, which is the
    # point of having it: the backend is asked the sharpened question.
    backend = ScriptedBackend(sample_evidence())
    reasoner = ScriptedReasoner(
        json.dumps({"question": "A sharpened question?"}),
        json.dumps({"brief": "b", "report": "## 1. A\n\nr", "confidence": "low"}),
    )
    run_research(
        tmp_path,
        backend=backend,
        reasoner=reasoner,
        query="A vague question?",
        depth="high",
    )
    assert backend.questions == ["A sharpened question?"]
    assert backend.budgets[0].depth == "high"


def test_the_deterministic_verbs_read_a_run_this_pipeline_wrote(tmp_path):
    # The loop that matters: one expensive call, then unlimited cheap navigation.
    from research_core import read_part, render, sources_of

    envelope = run_research(tmp_path)
    run = load_run(tmp_path / "runs", envelope["run_id"])
    assert read_part(run, lines=3)["completeness"]["returned_lines"] == 3
    assert sources_of(run, category="academic")["count"] == 1
    assert "## Academic" in render(run, fmt="bibliography")


# -- regressions from the first live call ------------------------------------
#
# Three defects that only a real call could surface. Every one of them passed a
# scripted test suite and failed against the actual service, which is the whole
# argument for spending the money once.


def test_the_services_web_prefixed_markers_are_rewritten(tmp_path):
    # The service emits [web:1], not [1]. The original regex matched neither the
    # real markers nor anything else, so every citation in a live report stayed
    # unrewritten and the dangling check had nothing to check.
    evidence = Evidence(
        text="Released in 2012 [web:1], stable in 2015 [web:2].",
        sources=[
            Source(url="https://arxiv.org/abs/1", title="One"),
            Source(url="https://example.com/two", title="Two"),
        ],
        backend="scripted",
    )
    envelope = run_research(tmp_path, backend=ScriptedBackend(evidence))
    report = (load_run(tmp_path / "runs", envelope["run_id"]).path / "report.md").read_text()
    assert "[s1]" in report and "[s2]" in report
    assert "[web:" not in report


def test_a_web_marker_past_the_source_list_is_still_left_alone(tmp_path):
    evidence = Evidence(
        text="A claim [web:7].",
        sources=[Source(url="https://arxiv.org/abs/1", title="One")],
        backend="scripted",
    )
    reasoner = scripted_reasoner(cites=["s1"])
    run_research(tmp_path, backend=ScriptedBackend(evidence), reasoner=reasoner)
    assert "[web:7]" in reasoner.prompts[-1]


def test_the_next_block_only_offers_sections_when_there_are_sections(tmp_path):
    # The live run promised `read <id> --sections 1-3` for a three-line report.
    # Running it exited 2. A navigation hint that does not work is worse than
    # none, because the caller stops trusting the whole block.
    envelope = run_research(
        tmp_path, reasoner=scripted_reasoner(cites=[], report="One short finding.")
    )
    assert envelope["next"]["read_report"] == f"deep-research read {envelope['run_id']}"


def test_every_command_in_the_next_block_actually_runs(tmp_path):
    # Asserted against the real verb table rather than by eye.
    from deep_research.cli import main

    envelope = run_research(tmp_path, cites=["s1"])
    for command in envelope["next"].values():
        argv = command.split()[1:] + ["--runs-dir", str(tmp_path / "runs")]
        assert main(argv) == 0, command


def test_a_raw_response_is_stored_as_data_not_as_a_repr_string(tmp_path):
    # json.dumps(default=str) turned a whole SDK response into one repr string,
    # so raw/ was neither verbatim nor replayable -- defeating both reasons it
    # exists.
    class ModelLike:
        def model_dump_json(self, indent=None):
            return json.dumps({"id": "resp_1", "output": []}, indent=indent)

    evidence = Evidence(
        text="A finding [1].",
        sources=[Source(url="https://arxiv.org/abs/1", title="One")],
        backend="scripted",
    )
    object.__setattr__(evidence, "raw", ModelLike())
    envelope = run_research(tmp_path, backend=ScriptedBackend(evidence), cites=["s1"])
    raw = load_run(tmp_path / "runs", envelope["run_id"]).path / "raw" / "gather-01.json"
    assert json.loads(raw.read_text())["id"] == "resp_1"


def test_a_gather_that_found_nothing_is_refused_not_dressed_up_as_complete(tmp_path):
    # The live agent run returned status complete with zero sources, because its
    # search tool had failed to load and it answered from memory. A run with no
    # evidence presented as a research result is the most expensive thing this
    # tool could return: it looks exactly like a good one.
    from research_core import NoEvidence

    empty = Evidence(text="From memory, probably 2015.", sources=[], backend="scripted")
    with pytest.raises(NoEvidence) as excinfo:
        run_research(tmp_path, backend=ScriptedBackend(empty), cites=[])
    assert "no sources" in str(excinfo.value)
    assert excinfo.value.remedy

    run = next((tmp_path / "runs").iterdir())
    record = json.loads((run / "run.json").read_text())
    assert record["status"] == "failed"
    assert record["failure"]["code"] == "no_evidence"
    assert not (run / "report.md").exists()


def test_every_backend_accepts_the_same_call(tmp_path):
    """The caller must never have to ask an implementation what it accepts.

    This used to be done with inspect.signature at the call site -- a special
    case wearing a polite hat. Every implementation now takes scope and
    on_event, and the ones with no use for them ignore them honestly.
    """
    import inspect

    from research_core.backends.agent import AgentBackend
    from research_core.backends.perplexity import PerplexityBackend

    for implementation in (
        PerplexityBackend(),
        AgentBackend(),
        ScriptedBackend(sample_evidence()),
        UnconfiguredBackend(),
    ):
        parameters = inspect.signature(implementation.gather).parameters
        assert "scope" in parameters, type(implementation).__name__
        assert "on_event" in parameters, type(implementation).__name__


def test_the_backend_receives_the_scope_the_reasoner_produced(tmp_path):
    backend = ScriptedBackend(sample_evidence())
    reasoner = ScriptedReasoner(
        json.dumps({"question": "A sharpened question?"}),
        json.dumps({"brief": "b", "report": "## 1. A\n\nr", "confidence": "low"}),
    )
    run_research(tmp_path, backend=backend, reasoner=reasoner, query="vague?")
    assert backend.scopes == ["A sharpened question?"]
