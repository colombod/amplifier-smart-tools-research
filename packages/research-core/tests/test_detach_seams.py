"""D3 and D4: the parent/child boundary a `--detach` request crosses.

Both are the same shape -- the detached path skips a validation the attached
path already makes -- caught here by driving the REAL `_detach()` function
(through the public `fact_check.check_claims(detach=True, ...)` entry point),
never a fixture standing in for it. `subprocess.Popen` is replaced so the test
never actually spawns a child needing a real credential; everything asserted
here happens in `_detach()` BEFORE that call, which is the point.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from research_core.backends.scripted import ScriptedBackend, sample_evidence
from research_core.config import CONFIG_PATH_ENV_VAR
from research_core.errors import RunNotFoundError
from research_core.reasoning import ScriptedReasoner

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


class _FakeChildProcess:
    pid = 999_999


def _stub_popen(monkeypatch):
    """Replace the real subprocess spawn with one that records its argv and
    never actually runs anything -- the detached child would need a real
    credentialed reasoner, which no test here should ever need.
    """
    captured: dict[str, object] = {}

    def fake(argv, **kwargs):
        captured["argv"] = argv
        captured["cwd"] = kwargs.get("cwd")
        return _FakeChildProcess()

    monkeypatch.setattr(subprocess, "Popen", fake)
    return captured


# -- D4: a nonexistent --from-run must be refused before anything is spawned -


def test_detach_refuses_a_from_run_that_does_not_exist(tmp_path, monkeypatch):
    """Attached refuses `dr-DOES-NOT-EXIST` immediately with `run_not_found`.
    Detached used to accept it and report it back as `inherited_from` --
    real provenance for a run that was never real.
    """
    _stub_popen(monkeypatch)

    with pytest.raises(RunNotFoundError):
        fact_check.check_claims(
            claim=["A claim."],
            from_run="dr-DOES-NOT-EXIST",
            runs_dir=str(tmp_path / "runs"),
            detach=True,
            quiet=True,
            reasoner=ScriptedReasoner(),
        )

    # No half-built fact-check run left behind by the refused request.
    runs_dir = tmp_path / "runs"
    if runs_dir.exists():
        assert not any(p.name.startswith("fc-") for p in runs_dir.iterdir())


def test_detach_still_accepts_a_from_run_that_does_exist(tmp_path, monkeypatch):
    """The fix must not turn into a refusal of the legitimate case."""
    captured = _stub_popen(monkeypatch)
    research_id = a_research_run(tmp_path)

    envelope = fact_check.check_claims(
        claim=["A claim."],
        from_run=research_id,
        runs_dir=str(tmp_path / "runs"),
        detach=True,
        quiet=True,
        reasoner=ScriptedReasoner(),
    )
    assert envelope["accepted"] is True
    assert envelope["inherited_from"] == research_id
    assert captured["argv"], "the child should still have been spawned"


# -- D3: a relative --claims-file must survive the parent/child cwd change --


def test_a_relative_claims_file_is_resolved_before_the_handoff(tmp_path, monkeypatch):
    """The child is spawned with cwd=runs_dir. A relative claims_file that
    resolves fine in the CALLER's cwd must still resolve inside the child --
    which only works if it is made absolute before the handoff.
    """
    captured = _stub_popen(monkeypatch)
    research_id = a_research_run(tmp_path)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    claims_path = workdir / "claims.txt"
    claims_path.write_text("CRDTs converge without coordination.\n", encoding="utf-8")
    monkeypatch.chdir(workdir)

    fact_check.check_claims(
        claims_file="claims.txt",  # relative -- exactly the reported shape
        from_run=research_id,
        runs_dir=str(tmp_path / "runs"),
        detach=True,
        quiet=True,
        reasoner=ScriptedReasoner(),
    )

    argv = captured["argv"]
    arguments = json.loads(argv[-1])
    handed_off = arguments["claims_file"]
    assert Path(handed_off).is_absolute(), (
        f"a relative claims_file must be resolved before the child (cwd="
        f"{captured['cwd']!r}) ever sees it: got {handed_off!r}"
    )
    assert Path(handed_off) == claims_path.resolve()
