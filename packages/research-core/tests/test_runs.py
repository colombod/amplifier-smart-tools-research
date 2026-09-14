"""The deterministic surface, against hand-authored fixture runs.

Every test here runs with no credential configured and spends no tokens. That is
not a convenience -- it is the property the whole layering exists to produce, and
these tests are where it is actually demonstrated.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from research_core import (
    RunNotFoundError,
    UsageError,
    citation_ids,
    dangling_citations,
    list_runs,
    load_run,
    read_part,
    render,
    sources_of,
    status_of,
    verdicts_of,
)

FIXTURES = Path(__file__).parent / "fixtures" / "runs"

CLEAN = "dr-1a2b3c4d"
DANGLING = "dr-7f3e9a21"
FAILED = "dr-c0ffee11"
FACT_CHECK = "fc-9f8e7d6c"


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    """Prove, not assume, that nothing here reaches for a credential."""
    for var in (
        "PERPLEXITY_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "AZURE_OPENAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def test_listing_finds_every_fixture_run():
    found = list_runs(FIXTURES)
    assert {r["run_id"] for r in found} == {CLEAN, DANGLING, FAILED, FACT_CHECK}


def test_listing_is_newest_first():
    created = [r["created_at"] for r in list_runs(FIXTURES)]
    assert created == sorted(created, reverse=True)


def test_listing_filters_by_status_and_tool():
    assert [r["run_id"] for r in list_runs(FIXTURES, status="failed")] == [FAILED]
    assert [r["run_id"] for r in list_runs(FIXTURES, tool="fact-check")] == [FACT_CHECK]


def test_a_runs_directory_that_does_not_exist_yet_is_empty_not_broken(tmp_path):
    # Nothing has been run. That is a normal state, not an error.
    assert list_runs(tmp_path / "nothing-here-yet") == []


def test_an_unknown_run_is_a_named_refusal_not_an_empty_result():
    with pytest.raises(RunNotFoundError) as excinfo:
        load_run(FIXTURES, "dr-does-not-exist")
    # Several callers may be pointed at different runs directories, so the
    # message has to say which one it looked in.
    assert str(FIXTURES) in str(excinfo.value)
    assert excinfo.value.remedy


def test_status_reports_stage_progress():
    document = status_of(load_run(FIXTURES, CLEAN))
    assert document["status"] == "complete"
    assert document["stages_complete"] == document["stages_total"] == 4
    assert document["usage"]["cost_usd"] == "0.2841"


def test_a_failed_run_says_where_it_failed_and_keeps_what_it_gathered():
    run = load_run(FIXTURES, FAILED)
    document = status_of(run)
    assert document["status"] == "failed"
    assert document["failure"]["stage"] == "gather"
    assert document["failure"]["remedy"]
    assert document["stages_complete"] == 1
    # The evidence gathered before the failure is kept, not discarded.
    assert sources_of(run)["count"] == 1


def test_reading_a_failed_run_explains_rather_than_returning_nothing():
    with pytest.raises(RunNotFoundError) as excinfo:
        read_part(load_run(FIXTURES, FAILED))
    assert "failed during the gather stage" in str(excinfo.value)


def test_a_bounded_read_says_it_is_partial():
    document = read_part(load_run(FIXTURES, CLEAN), lines=12)
    completeness = document["completeness"]
    assert completeness["complete"] is False
    assert completeness["returned_lines"] == 12
    assert completeness["total_lines"] > 12
    assert "INCOMPLETE" in completeness["note"]
    assert str(completeness["total_lines"] - 12) in completeness["note"]


def test_a_read_that_reaches_the_end_says_it_is_whole():
    document = read_part(load_run(FIXTURES, CLEAN), lines=500)
    assert document["completeness"]["complete"] is True
    assert "COMPLETE" in document["completeness"]["note"]


def test_a_read_above_the_ceiling_is_refused_not_capped():
    # Silently capping is how a caller ends up presenting a slice as the whole
    # thing, which is the failure this verb exists to prevent.
    with pytest.raises(UsageError) as excinfo:
        read_part(load_run(FIXTURES, CLEAN), lines=99_999, max_read_lines=5_000)
    assert "above the ceiling" in str(excinfo.value)


def test_reading_by_section():
    document = read_part(load_run(FIXTURES, CLEAN), sections="2-3")
    assert [s["number"] for s in document["sections"]] == [2, 3]
    assert document["text"].startswith("## 2.")


def test_a_section_that_does_not_exist_names_the_ones_that_do():
    with pytest.raises(UsageError) as excinfo:
        read_part(load_run(FIXTURES, CLEAN), sections="9")
    assert "sections:" in str(excinfo.value)


@pytest.mark.parametrize("spec", ["nonsense", "0", "3-1", "-2"])
def test_a_malformed_section_range_is_refused_not_guessed_at(spec):
    with pytest.raises(UsageError):
        read_part(load_run(FIXTURES, CLEAN), sections=spec)


def test_sources_come_back_as_data_and_filter_by_category():
    run = load_run(FIXTURES, CLEAN)
    assert sources_of(run)["count"] == 6
    academic = sources_of(run, category="academic")
    assert academic["count"] == 2
    assert all(s["category"] == "academic" for s in academic["sources"])


def test_a_fact_check_run_can_inherit_its_sources():
    # The payoff of one shared evidence store: a check need not re-gather what a
    # research run already found.
    assert sources_of(load_run(FIXTURES, FACT_CHECK))["inherited_from"] == CLEAN


def test_citation_ids_are_found_in_order_without_duplicates():
    assert citation_ids("a [s2] b [s1] c [s2]") == ["s2", "s1"]


def test_a_clean_run_has_no_dangling_citations():
    assert dangling_citations(load_run(FIXTURES, CLEAN)) == []


def test_a_dangling_citation_is_caught():
    # The characteristic failure of research tooling -- a model citing a source
    # it was never given -- caught by set membership, with no judgment required.
    assert dangling_citations(load_run(FIXTURES, DANGLING)) == ["s7"]


def test_verdicts_filter_and_carry_the_tally():
    document = verdicts_of(load_run(FIXTURES, FACT_CHECK))
    assert document["count"] == 3
    assert document["tally"]["refuted"] == 1
    only = verdicts_of(load_run(FIXTURES, FACT_CHECK), verdict="unverifiable")
    assert only["count"] == 1
    assert only["verdicts"][0]["index"] == 3


def test_unverifiable_is_its_own_verdict_and_not_a_refutation():
    entry = verdicts_of(load_run(FIXTURES, FACT_CHECK), verdict="unverifiable")["verdicts"][0]
    assert entry["verdict"] == "unverifiable"
    assert "not established" in entry["reasoning"]


def test_asking_a_research_run_for_verdicts_explains_rather_than_failing_blankly():
    with pytest.raises(UsageError) as excinfo:
        verdicts_of(load_run(FIXTURES, CLEAN))
    assert "fact-check runs" in excinfo.value.remedy


@pytest.mark.parametrize("fmt", ["markdown", "json", "bibliography"])
def test_every_render_format_produces_something_and_spends_nothing(fmt):
    rendered = render(load_run(FIXTURES, CLEAN), fmt=fmt)
    assert rendered.strip()


def test_the_bibliography_groups_by_category():
    rendered = render(load_run(FIXTURES, CLEAN), fmt="bibliography")
    assert "## Academic" in rendered
    assert "## Docs" in rendered
    assert "arxiv.org" in rendered


def test_an_unknown_render_format_is_refused():
    with pytest.raises(UsageError):
        render(load_run(FIXTURES, CLEAN), fmt="pdf")
