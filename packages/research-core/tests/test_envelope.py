"""Stdout carries the result. Stderr carries everything else, failures included.

A caller pipes stdout to a parser. If a failure envelope ever lands there, the
parser either chokes on it or -- worse -- silently accepts it as a result, and
the one property this whole envelope module exists to guarantee (stdout is
ONLY ever `{"result": ...}`) is gone.
"""

from __future__ import annotations

import io
import json

from research_core.envelope import emit, emit_error
from research_core.errors import SmartToolError


def _capture(func, *args, **kwargs) -> tuple[str, str]:
    """Run ``func`` with stdout/stderr replaced by buffers; return both."""
    import contextlib

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        func(*args, **kwargs)
    return out.getvalue(), err.getvalue()


def test_a_successful_result_writes_only_to_stdout():
    out, err = _capture(emit, {"ok": True})
    assert json.loads(out) == {"result": {"ok": True}}
    assert err == ""


def test_a_failure_writes_only_to_stderr_never_stdout():
    # THE deviation: a caught SmartToolError used to be routed through the
    # same stdout writer as a success, so a caller piping stdout for a result
    # would receive an error envelope instead -- indistinguishable from a
    # (wrong) success by anything only watching stdout.
    out, err = _capture(emit_error, "failed", "it broke", "try again")
    assert out == "", "a failing invocation must write NOTHING to stdout"
    assert json.loads(err) == {
        "error": {"code": "failed", "message": "it broke", "remedy": "try again"}
    }


def test_a_failure_exits_the_pipe_clean_for_a_downstream_parser():
    # The property a caller actually depends on: `tool ... | jq .result` sees
    # nothing at all on a failure (jq errors on empty input, which is exactly
    # the signal a caller wants), rather than an error envelope masquerading
    # as parseable result data.
    out, _ = _capture(emit_error, "failed", "message", "remedy")
    assert out == ""


def test_emit_error_carries_an_absolute_artifact_path_when_given():
    _, err = _capture(emit_error, "failed", "message", "remedy", artifact_path="relative/run-dir")
    document = json.loads(err)
    path = document["error"]["artifact"]["path"]
    assert path.startswith("/"), f"artifact.path must be absolute, got {path!r}"
    assert path.endswith("relative/run-dir")


def test_emit_error_omits_artifact_when_none_given():
    _, err = _capture(emit_error, "failed", "message", "remedy")
    assert "artifact" not in json.loads(err)["error"]


def test_smart_tool_error_carries_an_absolute_artifact_path():
    exc = SmartToolError("m", "r", artifact_path="some/run/dir")
    assert exc.artifact_path is not None
    assert exc.artifact_path.startswith("/")
    assert exc.artifact_path.endswith("some/run/dir")


def test_with_artifact_attaches_the_path_after_construction_and_returns_self():
    exc = SmartToolError("m", "r")
    assert exc.artifact_path is None
    same = exc.with_artifact("later/known/dir")
    assert same is exc
    assert exc.artifact_path is not None
    assert exc.artifact_path.endswith("later/known/dir")


def test_smart_tool_error_with_no_artifact_stays_none():
    assert SmartToolError("m", "r").artifact_path is None
