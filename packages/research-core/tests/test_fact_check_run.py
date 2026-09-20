"""The checking workflow end to end, through the seams, spending nothing.

The sharpest thing here is the distinction between two outcomes that a careless
tool collapses into one: `unverifiable` means the claim was CHECKED and the
evidence was inadequate -- a finding a caller can act on -- while a claim the
tool could not check for a mechanical reason is a FAILED RUN. Recording the
second as the first would put a fabricated finding in the record.
"""

from __future__ import annotations

import json

import pytest
from research_core import load_run
from research_core.backends.scripted import ScriptedBackend, sample_evidence
from research_core.config import CONFIG_PATH_ENV_VAR
from research_core.errors import SmartToolError, UsageError
from research_core.reasoning import ScriptedReasoner, UnconfiguredReasoner

deep_research = pytest.importorskip("deep_research")
fact_check = pytest.importorskip("fact_check")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, str(tmp_path / "config.toml"))
    monkeypatch.setenv("RESEARCH_CREDENTIALS", str(tmp_path / "credentials.toml"))
    for var in ("RESEARCH_RUNS_DIR", "RESEARCH_DEPTH", "RESEARCH_BACKEND"):
        monkeypatch.delenv(var, raising=False)
    for var in ("PERPLEXITY_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def a_research_run(tmp_path) -> str:
    """A real research run in the shared runs directory, written by the other tool."""
    envelope = deep_research.research(
        "Do state-based CRDTs converge?",
        backend=ScriptedBackend(sample_evidence()),
        reasoner=ScriptedReasoner(
            json.dumps({"question": "Do state-based CRDTs converge?"}),
            json.dumps(
                {
                    "brief": "They do [s1].",
                    "report": "## 1. Yes\n\nThey converge [s1][s2].",
                    "confidence": "medium",
                }
            ),
        ),
        runs_dir=str(tmp_path / "runs"),
        quiet=True,
    )
    return envelope["run_id"]


def checking_reasoner(
    *verdicts: dict, claim_types: list[str] | None = None, brief="1 checked.", extra=()
) -> ScriptedReasoner:
    """Scripted triage, one reply per claim, then the compile turn."""
    types = claim_types or ["simple"] * len(verdicts)
    return ScriptedReasoner(
        json.dumps(
            {
                "claims": [
                    {"index": i, "text": f"claim {i}", "type": t, "reason": "scripted"}
                    for i, t in enumerate(types)
                ]
            }
        ),
        *[json.dumps(v) for v in verdicts],
        *extra,
        json.dumps({"brief": brief, "report": "## 1. Summary\n\nDone.", "confidence": "medium"}),
    )


def check(tmp_path, claims, reasoner, *, from_run=None, **kwargs):
    return fact_check.check_claims(
        claim=claims,
        from_run=from_run if from_run is not None else a_research_run(tmp_path),
        reasoner=reasoner,
        runs_dir=str(tmp_path / "runs"),
        quiet=True,
        **kwargs,
    )


# -- --from-run: the payoff of one shared, accumulating runs directory --------


def test_from_run_consumes_another_runs_evidence_without_gathering(tmp_path):
    research_id = a_research_run(tmp_path)
    envelope = check(
        tmp_path,
        ["CRDTs converge."],
        checking_reasoner(
            {
                "verdict": "supported",
                "confidence": "high",
                "reasoning": "Both sources agree [s1].",
                "sources": ["s1"],
            }
        ),
        from_run=research_id,
    )
    assert envelope["source_count"] == 3
    assert envelope["inherited_from"] == research_id

    # and the run records where the evidence came from, so a verdict can be
    # audited back to the run that actually found it
    run = load_run(tmp_path / "runs", envelope["run_id"])
    sources = json.loads((run.path / "sources.json").read_text())
    assert sources["inherited_from"] == research_id
    assert [s["id"] for s in sources["sources"]] == ["s1", "s2", "s3"]


def test_no_evidence_source_is_a_usage_error_not_a_silent_empty_check(tmp_path):
    with pytest.raises(UsageError) as excinfo:
        fact_check.check_claims(
            claim=["Anything."],
            from_run=None,
            reasoner=checking_reasoner(),
            runs_dir=str(tmp_path / "runs"),
            quiet=True,
        )
    assert "--from-run" in excinfo.value.remedy


def test_a_claim_that_could_not_be_checked_reports_what_every_rejected_attempt_cost(
    tmp_path,
):
    """D1 sibling: verify's own AttemptsExhausted is converted to
    ClaimUncheckable, and that conversion used to happen before any usage was
    recorded -- the same "wasted money reported as zero" shape as
    deep-research's exhausted path, one layer deeper. Drives the real
    failing path (not `record_usage` called directly) and reads run.json off
    disk, which is what a caller actually sees.
    """
    reasoner = ScriptedReasoner(
        json.dumps({"claims": [{"index": 0, "text": "claim 0", "type": "simple", "reason": "x"}]}),
        *[json.dumps({"verdict": "not-a-verdict"}) for _ in range(2)],
    )
    with pytest.raises(SmartToolError):
        check(tmp_path, ["A claim."], reasoner, max_attempts=2)

    run = next((tmp_path / "runs").iterdir())
    record = json.loads((run / "run.json").read_text())
    usage = record["usage"]

    # 1 accepted triage attempt + 2 rejected verify attempts.
    assert usage["attempts"] == 3
    assert usage["attempts_discarded"] == 2
    assert usage["discarded_cost_usd"] is not None
    assert float(usage["discarded_cost_usd"]) == pytest.approx(0.0020)


def test_a_run_with_no_sources_is_refused(tmp_path):
    from research_core.errors import NoEvidence

    empty = tmp_path / "runs" / "dr-empty"
    empty.mkdir(parents=True)
    (empty / "run.json").write_text(
        json.dumps(
            {
                "schema": "research-run/v1",
                "run_id": "dr-empty",
                "tool": "deep-research",
                "status": "complete",
                "stages": [],
            }
        )
    )
    (empty / "sources.json").write_text(
        json.dumps({"schema": "research-sources/v1", "run_id": "dr-empty", "sources": []})
    )
    with pytest.raises(NoEvidence):
        check(tmp_path, ["Anything."], checking_reasoner(), from_run="dr-empty")


# -- unverifiable is a verdict, not a failure, and never a refutation ---------


def test_unverifiable_is_recorded_as_itself(tmp_path):
    envelope = check(
        tmp_path,
        ["Something nobody wrote about."],
        checking_reasoner(
            {
                "verdict": "unverifiable",
                "confidence": "low",
                "reasoning": "Nothing in the sources addresses this either way.",
                "sources": [],
            }
        ),
    )
    assert envelope["tally"]["unverifiable"] == 1
    assert envelope["tally"]["refuted"] == 0
    assert envelope["status"] == "complete"


def test_a_refutation_resting_on_no_source_is_rejected_and_repaired(tmp_path):
    # The characteristic failure: "I could not confirm it" dressed up as
    # "it is false". A refutation must name the source that contradicts.
    reasoner = checking_reasoner(
        {
            "verdict": "refuted",
            "confidence": "high",
            "reasoning": "I found nothing supporting it.",
            "sources": [],
        },
        extra=(
            json.dumps(
                {
                    "verdict": "unverifiable",
                    "confidence": "low",
                    "reasoning": "No adequate evidence either way.",
                    "sources": [],
                }
            ),
        ),
    )
    envelope = check(tmp_path, ["A contested claim."], reasoner)
    assert envelope["tally"]["refuted"] == 0
    assert envelope["tally"]["unverifiable"] == 1

    repair = reasoner.prompts[-2]
    assert "REJECTED" in repair
    assert "unverifiable" in repair


def test_a_verdict_citing_a_source_the_run_lacks_is_rejected(tmp_path):
    reasoner = checking_reasoner(
        {
            "verdict": "supported",
            "confidence": "high",
            "reasoning": "Stated plainly in [s9].",
            "sources": ["s9"],
        },
        extra=(
            json.dumps(
                {
                    "verdict": "supported",
                    "confidence": "medium",
                    "reasoning": "Stated in [s1].",
                    "sources": ["s1"],
                }
            ),
        ),
    )
    envelope = check(tmp_path, ["A claim."], reasoner)
    assert envelope["tally"]["supported"] == 1
    assert "s9" in reasoner.prompts[-2]


# -- the distinction the whole tool turns on ---------------------------------


def test_a_claim_that_could_not_be_checked_fails_the_run(tmp_path):
    # Not recorded as `unverifiable`. The tool never got as far as looking, and
    # filing that under a verdict would fabricate a finding.
    reasoner = checking_reasoner(
        *[{"verdict": "nonsense", "confidence": "high", "reasoning": "x"}] * 3
    )
    with pytest.raises(SmartToolError):
        check(tmp_path, ["A claim."], reasoner, max_attempts=3)

    run = next(p for p in (tmp_path / "runs").iterdir() if p.name.startswith("fc-"))
    record = json.loads((run / "run.json").read_text())
    assert record["status"] == "failed"
    assert record["failure"]["code"] == "claim_uncheckable"
    assert "NOT the same as `unverifiable`" in record["failure"]["remedy"]
    assert not (run / "report.md").exists()


def test_verdicts_already_reached_survive_a_later_claim_failing(tmp_path):
    # Each verdict is written as it lands, so an interrupted run leaves real
    # verdicts rather than nothing.
    reasoner = ScriptedReasoner(
        json.dumps(
            {
                "claims": [
                    {"index": 0, "text": "a", "type": "simple", "reason": "x"},
                    {"index": 1, "text": "b", "type": "simple", "reason": "x"},
                ]
            }
        ),
        json.dumps(
            {
                "verdict": "supported",
                "confidence": "high",
                "reasoning": "Clear in [s1].",
                "sources": ["s1"],
            }
        ),
        *[json.dumps({"verdict": "nope", "reasoning": "x"})] * 3,
    )
    with pytest.raises(SmartToolError):
        check(tmp_path, ["First claim.", "Second claim."], reasoner, max_attempts=3)

    run = next(p for p in (tmp_path / "runs").iterdir() if p.name.startswith("fc-"))
    verdicts = json.loads((run / "verdicts.json").read_text())
    assert verdicts["complete"] is False
    assert len(verdicts["verdicts"]) == 1
    assert verdicts["verdicts"][0]["verdict"] == "supported"

    # The `verdicts` CAPABILITY -- not the raw file -- must say the same
    # thing: a partial result is a failure unless it names which parts
    # succeeded, and a caller reading it must not mistake it for a finished
    # run.
    found = fact_check.verdicts(run.name, runs_dir=str(tmp_path / "runs"))
    assert found["complete"] is False
    assert found["run_status"] == "failed"
    assert found["expected_claims"] == 2
    assert found["missing_claim_indexes"] == [1]


# -- triage ------------------------------------------------------------------


def test_strict_escalates_every_claim_without_paying_for_a_turn(tmp_path):
    # The caller already decided. Buying a classification turn to be told so is
    # waste, so triage short-circuits and spends nothing.
    reasoner = ScriptedReasoner(
        json.dumps(
            {
                "verdict": "opinion",
                "confidence": "high",
                "reasoning": "A value judgment.",
                "sources": [],
            }
        ),
        json.dumps({"brief": "1 checked.", "report": "## 1. S\n\nx", "confidence": "low"}),
    )
    envelope = check(tmp_path, ["Rust is the best language."], reasoner, strict=True)
    run = load_run(tmp_path / "runs", envelope["run_id"])
    claims = json.loads((run.path / "claims.json").read_text())
    assert claims["claims"][0]["type"] == "complex"
    assert claims["claims"][0]["reason"] == "--strict was requested"


def test_a_claim_triage_forgot_is_rejected_rather_than_dropped(tmp_path):
    # Silently dropping a claim would understate the tally, and nobody would
    # notice the one that vanished.
    reasoner = ScriptedReasoner(
        json.dumps({"claims": [{"index": 0, "text": "a", "type": "simple", "reason": "x"}]}),
        json.dumps(
            {
                "claims": [
                    {"index": 0, "text": "a", "type": "simple", "reason": "x"},
                    {"index": 1, "text": "b", "type": "opinion", "reason": "x"},
                ]
            }
        ),
        json.dumps(
            {
                "verdict": "supported",
                "confidence": "high",
                "reasoning": "In [s1].",
                "sources": ["s1"],
            }
        ),
        json.dumps(
            {
                "verdict": "opinion",
                "confidence": "high",
                "reasoning": "A preference.",
                "sources": [],
            }
        ),
        json.dumps({"brief": "2 checked.", "report": "## 1. S\n\nx", "confidence": "low"}),
    )
    envelope = check(tmp_path, ["A fact.", "A preference."], reasoner)
    assert envelope["claim_count"] == 2
    assert "[1]" in reasoner.prompts[1]


# -- the result shape --------------------------------------------------------


def test_the_tally_travels_inline_and_the_detail_stays_on_disk(tmp_path):
    envelope = check(
        tmp_path,
        ["A claim."],
        checking_reasoner(
            {
                "verdict": "supported",
                "confidence": "high",
                "reasoning": "In [s1].",
                "sources": ["s1"],
            }
        ),
    )
    assert envelope["tally"] == {"supported": 1, "refuted": 0, "unverifiable": 0, "opinion": 0}
    assert set(envelope["next"]) == {"read_verdicts", "read_refuted", "list_sources"}
    assert all(envelope["run_id"] in c for c in envelope["next"].values())


def test_every_command_in_the_next_block_actually_runs(tmp_path):
    from fact_check.cli import main

    envelope = check(
        tmp_path,
        ["A claim."],
        checking_reasoner(
            {
                "verdict": "supported",
                "confidence": "high",
                "reasoning": "In [s1].",
                "sources": ["s1"],
            }
        ),
    )
    for command in envelope["next"].values():
        argv = command.split()[1:] + ["--runs-dir", str(tmp_path / "runs")]
        assert main(argv) == 0, command


def test_the_deterministic_verdicts_verb_reads_what_this_wrote(tmp_path):
    envelope = check(
        tmp_path,
        ["A claim.", "Another."],
        checking_reasoner(
            {
                "verdict": "supported",
                "confidence": "high",
                "reasoning": "In [s1].",
                "sources": ["s1"],
            },
            {
                "verdict": "unverifiable",
                "confidence": "low",
                "reasoning": "Nothing either way.",
                "sources": [],
            },
            claim_types=["simple", "complex"],
        ),
    )
    found = fact_check.verdicts(
        envelope["run_id"], verdict="unverifiable", runs_dir=str(tmp_path / "runs")
    )
    assert found["count"] == 1
    assert found["verdicts"][0]["claim"] == "Another."


def test_the_reasoning_seam_refuses_before_a_prompt_is_built(tmp_path):
    from research_core import NoProviderError

    research_id = a_research_run(tmp_path)
    with pytest.raises(NoProviderError):
        check(tmp_path, ["A claim."], UnconfiguredReasoner(), from_run=research_id)
    # the refusal left no fact-check run behind
    assert not any(p.name.startswith("fc-") for p in (tmp_path / "runs").iterdir())


def test_a_no_provider_refusal_carries_the_check_affordance(tmp_path):
    """D8 sibling: same fix, same shape, the other tool."""
    from research_core import NoProviderError

    research_id = a_research_run(tmp_path)
    with pytest.raises(NoProviderError) as excinfo:
        check(tmp_path, ["A claim."], UnconfiguredReasoner(), from_run=research_id)
    affordances = excinfo.value.affordances
    assert affordances, "a no_provider refusal must not be a dead end"
    check_affordance = next(a for a in affordances if a.name == "check")
    assert check_affordance.command == "fact-check check"
    assert check_affordance.call == "fact_check.check()"
