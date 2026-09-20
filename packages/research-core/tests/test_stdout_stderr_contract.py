"""D7: both tools' contracts said the error envelope was on stdout. It has
always actually been on stderr (`research_core.envelope.emit_error`) -- the
code was a deliberate, correct fix; only the documents drifted. These tests
pin the REAL, on-the-wire behaviour through each tool's actual `main()`, so a
future change that puts the envelope back on stdout (matching the OLD, wrong
documents) fails here rather than only being noticed by re-reading prose.
"""

from __future__ import annotations

import json

import pytest
from research_core.config import CONFIG_PATH_ENV_VAR

deep_research_cli = pytest.importorskip("deep_research.cli")
fact_check_cli = pytest.importorskip("fact_check.cli")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, str(tmp_path / "config.toml"))
    monkeypatch.setenv("RESEARCH_CREDENTIALS", str(tmp_path / "credentials.toml"))
    for var in ("RESEARCH_RUNS_DIR", "RESEARCH_DEPTH", "RESEARCH_BACKEND"):
        monkeypatch.delenv(var, raising=False)
    for var in ("PERPLEXITY_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def test_deep_research_failure_is_silent_on_stdout_and_on_stderr_instead(tmp_path, capsys):
    exit_code = deep_research_cli.main(["status", "dr-does-not-exist", "--runs-dir", str(tmp_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == "", "a failure must never write to stdout"
    envelope = json.loads(captured.err)
    assert envelope["error"]["code"] == "run_not_found"
    assert envelope["error"]["remedy"]


def test_fact_check_failure_is_silent_on_stdout_and_on_stderr_instead(tmp_path, capsys):
    exit_code = fact_check_cli.main(["verdicts", "fc-does-not-exist", "--runs-dir", str(tmp_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == "", "a failure must never write to stdout"
    envelope = json.loads(captured.err)
    assert envelope["error"]["code"] == "run_not_found"


def test_a_usage_error_is_also_silent_on_stdout(tmp_path, capsys):
    """A different exit code (2, refused), same stream contract."""
    exit_code = deep_research_cli.main(
        ["research", "--query", "q", "--backend", "bogus", "--runs-dir", str(tmp_path)]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    envelope = json.loads(captured.err)
    assert envelope["error"]["code"] == "usage"


def test_a_success_is_on_stdout_and_never_duplicated_onto_stderr(tmp_path, capsys):
    """The other half of the contract: a real success carries the result on
    stdout, and stderr -- when anything is there at all -- is never the
    result envelope itself.
    """
    exit_code = deep_research_cli.main(["manifest"])
    captured = capsys.readouterr()

    assert exit_code == 0
    envelope = json.loads(captured.out)
    assert "result" in envelope

    if captured.err.strip():
        try:
            stderr_document = json.loads(captured.err)
        except json.JSONDecodeError:
            stderr_document = None  # plain progress text -- fine
        assert not (isinstance(stderr_document, dict) and "result" in stderr_document), (
            "the success envelope must never also land on stderr"
        )
