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


def run_research(tmp_path, backend=None, **kwargs):
    return deep_research.research(
        kwargs.pop("query", "Does the property hold?"),
        backend=backend if backend is not None else ScriptedBackend(sample_evidence()),
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


def test_backend_citation_markers_are_rewritten_to_our_ids(tmp_path):
    envelope = run_research(tmp_path)
    report = (load_run(tmp_path / "runs", envelope["run_id"]).path / "report.md").read_text()
    assert "[s1]" in report and "[s3]" in report
    assert "[1]" not in report


def test_a_marker_with_no_source_behind_it_is_left_alone_and_reported(tmp_path):
    # Renaming it to [s9] would manufacture an id and hide the very failure the
    # dangling-citation check exists to catch.
    evidence = Evidence(
        text="A claim [1] and another with no source [9].",
        sources=[Source(url="https://arxiv.org/abs/1", title="One")],
        backend="scripted",
    )
    envelope = run_research(tmp_path, backend=ScriptedBackend(evidence))
    report = (load_run(tmp_path / "runs", envelope["run_id"]).path / "report.md").read_text()
    assert "[s1]" in report
    assert "[9]" in report
    assert envelope.get("warnings") is None  # [9] is not an sN marker, so not dangling


def test_a_dangling_source_id_is_surfaced_on_the_result(tmp_path):
    evidence = Evidence(
        text="Supported by the literature [s4].",
        sources=[Source(url="https://arxiv.org/abs/1", title="One")],
        backend="scripted",
    )
    envelope = run_research(tmp_path, backend=ScriptedBackend(evidence))
    warnings = envelope["warnings"]
    assert warnings[0]["code"] == "dangling_citations"
    assert warnings[0]["markers"] == ["s4"]


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
        runs_dir=str(tmp_path / "runs"),
        quiet=True,
        stream=stream,
    )
    assert stream.getvalue() == ""
    run = load_run(tmp_path / "runs", envelope["run_id"])
    assert (run.path / "events.jsonl").read_text().strip()


def test_a_small_report_comes_back_inline(tmp_path):
    envelope = run_research(tmp_path)
    assert envelope["inline"] is True
    assert envelope["report"].startswith("# ")


def test_no_inline_forces_the_pointer(tmp_path):
    envelope = run_research(tmp_path, inline=False)
    assert envelope["inline"] is False
    assert "report" not in envelope


def test_a_large_report_is_left_on_disk(tmp_path):
    evidence = Evidence(
        text="A long finding. " * 2000,
        sources=[Source(url="https://arxiv.org/abs/1", title="One")],
        backend="scripted",
    )
    envelope = run_research(tmp_path, backend=ScriptedBackend(evidence))
    assert envelope["report_bytes"] > 8_000
    assert envelope["inline"] is False
    assert "report" not in envelope


def test_usage_is_recorded_and_cost_stays_a_string(tmp_path):
    envelope = run_research(tmp_path)
    assert envelope["usage"]["tokens_in"] == 1200
    assert envelope["usage"]["cost_usd"] == "0.0087"
    assert isinstance(envelope["usage"]["cost_usd"], str)


def test_a_cost_the_backend_did_not_report_is_null_not_zero(tmp_path):
    # A silent 0.00 would be a claim, and a false one.
    evidence = Evidence(
        text="A finding.",
        sources=[],
        usage={"tokens_in": 10, "tokens_out": 5},
        backend="scripted",
    )
    envelope = run_research(tmp_path, backend=ScriptedBackend(evidence))
    assert envelope["usage"]["cost_usd"] is None


def test_a_failure_mid_gather_keeps_the_run_and_says_where(tmp_path):
    class Failing:
        name = "failing"

        def preflight(self) -> str:
            return "scripted"

        def gather(self, query, budget):
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


def test_the_backend_is_asked_the_question_with_the_configured_depth(tmp_path):
    backend = ScriptedBackend(sample_evidence())
    run_research(tmp_path, backend=backend, query="A specific question?", depth="high")
    assert backend.questions == ["A specific question?"]
    assert backend.budgets[0].depth == "high"


def test_the_deterministic_verbs_read_a_run_this_pipeline_wrote(tmp_path):
    # The loop that matters: one expensive call, then unlimited cheap navigation.
    from research_core import read_part, render, sources_of

    envelope = run_research(tmp_path)
    run = load_run(tmp_path / "runs", envelope["run_id"])
    assert read_part(run, lines=3)["completeness"]["returned_lines"] == 3
    assert sources_of(run, category="academic")["count"] == 1
    assert "## Academic" in render(run, fmt="bibliography")
