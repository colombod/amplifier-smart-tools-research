"""A run whose process died must not read as still working.

This is the one check that makes detaching safe. A run record says "running"
until its own process writes otherwise, and a process that dies never writes
anything -- so without this, every crashed run reads as busy forever and a
polling caller waits for a result that is never coming. That is strictly worse
than having blocked in the first place, which is why it is tested before the
detach flag it exists to support.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

from research_core.runs import ABANDONED, FINAL, GROWING, Run, liveness_of


def _run(tmp_path: Path, **overrides) -> Run:
    record = {
        "schema": "research-run/v1",
        "run_id": "dr-test0001",
        "tool": "deep-research",
        "status": "running",
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "stages": [],
    }
    record.update(overrides)
    path = tmp_path / record["run_id"]
    path.mkdir(parents=True, exist_ok=True)
    (path / "run.json").write_text(json.dumps(record), encoding="utf-8")
    return Run(run_id=record["run_id"], path=path, record=record)


def test_our_own_process_reads_as_growing(tmp_path):
    state = liveness_of(_run(tmp_path))
    assert state["state"] == GROWING
    assert state["poll_again_in_seconds"] > 0


def test_a_dead_process_reads_as_ABANDONED_not_growing(tmp_path):
    """THE test. Everything else here is scaffolding around this one line."""
    # A pid that cannot be alive: claimed by nothing, above any real range.
    state = liveness_of(_run(tmp_path, pid=0x7FFFFFFF))
    assert state["state"] == ABANDONED, (
        "a run whose process is gone read as still working -- the exact "
        "silent-failure shape detach must not introduce"
    )
    assert "gone" in state["why"]
    # Nothing is coming, so telling a caller to poll again would be a lie.
    assert state["poll_again_in_seconds"] is None


def test_a_finished_run_is_final_regardless_of_its_pid(tmp_path):
    for status in ("complete", "failed"):
        state = liveness_of(_run(tmp_path, status=status, pid=0x7FFFFFFF))
        assert state["state"] == FINAL
        assert state["poll_again_in_seconds"] is None


def test_a_run_from_another_host_is_unknown_rather_than_guessed(tmp_path):
    state = liveness_of(_run(tmp_path, host="some-other-machine"))
    assert state["state"] == "unknown"
    assert "cannot be checked from here" in state["why"]


def test_a_record_with_no_pid_is_unknown_rather_than_assumed_alive(tmp_path):
    record = _run(tmp_path)
    del record.record["pid"]
    assert liveness_of(record)["state"] == "unknown"


def test_detach_returns_part_one_and_says_what_is_not_yet_true(tmp_path):
    """The shape of part one, without waiting for the work.

    The child process is spawned and will fail fast on this host or succeed
    slowly; either way the PARENT's obligation is discharged the moment it
    returns, and that is what this pins. The three liveness states are covered
    above with no subprocess at all, and end-to-end on a real run in the
    resolution for smart_tools-31a.
    """
    import deep_research

    part_one = deep_research.research(
        "a question we never wait for",
        runs_dir=str(tmp_path),
        depth="low",
        detach=True,
        quiet=True,
    )

    assert part_one["accepted"] is True
    assert part_one["detached"] is True
    assert part_one["run_id"].startswith("dr-")
    assert isinstance(part_one["pid"], int)

    # An accepted request looks a great deal like an answer if nobody says
    # otherwise. This is the field that says otherwise.
    assert part_one["not_yet_true"], "part one must state what it is not"
    assert any("no report" in claim for claim in part_one["not_yet_true"])

    # And a way onward, since part one is a response like any other.
    names = [a["name"] for a in part_one["affordances"]]
    assert "status" in names, "part one must name how to find out when it is done"
    assert all(a["cost_usd"] == "0.00" for a in part_one["affordances"])

    # The run directory exists immediately, so a caller asking for status the
    # instant it returns finds a record rather than a gap.
    assert (tmp_path / part_one["run_id"] / "run.json").exists()
