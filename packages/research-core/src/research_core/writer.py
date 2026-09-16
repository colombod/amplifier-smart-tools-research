"""Writing a run, and reporting its progress twice.

The run directory is created BEFORE the first stage and updated as stages
complete, so a process that dies leaves evidence rather than nothing. That is the
difference between a run that failed and a run that never happened, and a caller
is entitled to tell them apart.

Progress goes to two places at once. Newline-delimited JSON on stderr for whoever
is watching live, and the same records appended to events.jsonl for whoever was
not. A stream nobody was listening to is gone forever; a persisted record can be
read afterwards, which is why this is the honest answer to a call that takes
minutes rather than a nicety on top of one.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO

from research_core.errors import RunsDirUnusableError
from research_core.runs import EVENTS_FILE, RAW_DIR, RUN_FILE

SCHEMA = "research-run/v1"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id(prefix: str) -> str:
    """A run id: the tool's prefix plus eight hex characters."""
    return f"{prefix}-{secrets.token_hex(4)}"


class RunWriter:
    """Creates a run directory and keeps it honest as the run proceeds."""

    def __init__(
        self,
        *,
        runs_dir: str | Path,
        run_id: str,
        tool: str,
        query: str,
        depth: str,
        backend: str,
        stages: tuple[str, ...],
        stream: TextIO | None = None,
        quiet: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> None:
        root = Path(runs_dir).expanduser()
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RunsDirUnusableError(
                f"The runs directory at {root} could not be created: {exc}",
                "Point --runs-dir, the config file, or RESEARCH_RUNS_DIR somewhere writable.",
            ) from exc

        self.path = root / run_id
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / RAW_DIR).mkdir(exist_ok=True)

        self.run_id = run_id
        self._stream = stream if stream is not None else sys.stderr
        self._quiet = quiet
        self._started = datetime.now(UTC)
        self._record: dict[str, Any] = {
            "schema": SCHEMA,
            "run_id": run_id,
            "tool": tool,
            "status": "running",
            # Who is doing the work. A detached run's record says "running" until
            # its process says otherwise -- and a process that dies never says
            # anything. Without a pid there is no way to tell a run that is
            # working from one whose process is gone, which is the silent-failure
            # shape this project has hit four times and the single thing that
            # would make detach worse than simply blocking.
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "query": query,
            "depth": depth,
            "backend": backend,
            "created_at": _now(),
            "updated_at": _now(),
            "duration_ms": None,
            "stages": [{"name": name, "status": "not_started"} for name in stages],
            "counts": {},
            "usage": {},
            "confidence": None,
            "failure": None,
            **(extra or {}),
        }
        self._flush_record()
        self.event("run", status="started", query=query, depth=depth, backend=backend)

    # -- writing -------------------------------------------------------------

    def _flush_record(self) -> None:
        self._record["updated_at"] = _now()
        (self.path / RUN_FILE).write_text(
            json.dumps(self._record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def event(self, kind: str, **fields: Any) -> dict[str, Any]:
        """Append one progress record, and stream it unless asked not to."""
        record = {"type": kind, "run_id": self.run_id, "at": _now(), **fields}
        line = json.dumps(record, sort_keys=True)
        with (self.path / EVENTS_FILE).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        if not self._quiet:
            # stderr, never stdout: the result is the only thing on stdout, so a
            # caller can parse it without filtering progress out first.
            self._stream.write(line + "\n")
            self._stream.flush()
        return record

    def _stage(self, name: str) -> dict[str, Any]:
        for stage in self._record["stages"]:
            if stage["name"] == name:
                return stage
        stage = {"name": name, "status": "not_started"}
        self._record["stages"].append(stage)
        return stage

    def start_stage(self, name: str) -> None:
        stage = self._stage(name)
        stage["status"] = "running"
        stage["started_at"] = _now()
        self._flush_record()
        index = self._record["stages"].index(stage) + 1
        self.event(
            "stage",
            stage=name,
            index=index,
            of=len(self._record["stages"]),
            status="started",
        )

    def finish_stage(self, name: str, **fields: Any) -> None:
        stage = self._stage(name)
        started = stage.get("started_at")
        stage["status"] = "complete"
        stage["ended_at"] = _now()
        if started:
            stage["duration_ms"] = int(
                (
                    datetime.strptime(stage["ended_at"], "%Y-%m-%dT%H:%M:%SZ")
                    - datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ")
                ).total_seconds()
                * 1000
            )
        self._flush_record()
        index = self._record["stages"].index(stage) + 1
        self.event(
            "stage",
            stage=name,
            index=index,
            of=len(self._record["stages"]),
            status="complete",
            duration_ms=stage.get("duration_ms"),
            **fields,
        )

    def fail_stage(self, name: str) -> None:
        stage = self._stage(name)
        stage["status"] = "failed"
        stage["ended_at"] = _now()
        self._flush_record()

    def write_file(self, name: str, text: str) -> Path:
        path = self.path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_json(self, name: str, document: Any) -> Path:
        return self.write_file(name, json.dumps(document, indent=2, sort_keys=True) + "\n")

    def write_raw(self, name: str, payload: Any) -> Path:
        """Keep a backend response verbatim, for audit and for replay in tests.

        An SDK response is usually a model object rather than a plain dict, and
        json.dumps(default=str) turns the whole thing into one repr string --
        which is neither verbatim nor replayable, and so defeats the only two
        reasons this file exists. Ask the object for its own serialisation first.
        """
        # PLAIN TEXT IS ALREADY VERBATIM. Falling through to json.dumps wrapped a
        # model's reply in quotes and escaped every newline, so a file promising
        # "the backend's own replies, verbatim" held a JSON string literal
        # instead. Harmless for an SDK object; ruinous for the case this exists
        # to serve, where the reply IS the evidence and its exact shape -- fenced
        # or not, truncated or not -- is the thing being diagnosed.
        if isinstance(payload, str):
            return self.write_file(f"{RAW_DIR}/{name}", payload)

        text: str | None = None
        for method in ("model_dump_json", "to_json"):
            serialise = getattr(payload, method, None)
            if callable(serialise):
                try:
                    text = serialise(indent=2) if method == "model_dump_json" else serialise()
                    break
                except (TypeError, ValueError):
                    text = None
        if text is None:
            for method in ("model_dump", "to_dict", "dict"):
                convert = getattr(payload, method, None)
                if callable(convert):
                    try:
                        text = json.dumps(convert(), indent=2, sort_keys=True, default=str)
                        break
                    except (TypeError, ValueError):
                        text = None
        if text is None:
            try:
                text = json.dumps(payload, indent=2, sort_keys=True, default=str)
            except (TypeError, ValueError):
                text = repr(payload)
        return self.write_file(f"{RAW_DIR}/{name}", text)

    def record_usage(self, usage: dict[str, Any]) -> None:
        merged = dict(self._record.get("usage") or {})
        for key in ("tokens_in", "tokens_out", "attempts", "attempts_discarded"):
            if usage.get(key) is not None:
                merged[key] = merged.get(key, 0) + int(usage[key])

        # COST ACCUMULATES. It used to be ASSIGNED here while tokens beside it
        # accumulated, so a run reported whatever the LAST stage to record spent
        # rather than its own total. Run dr-82baa98f reported $1.008705 -- exactly
        # the synthesise stage, with scope's $0.031287 silently overwritten. Every
        # run this tool ever reported under-stated what it cost.
        #
        # Two lines above sits a comment about not under-stating a run's cost. The
        # reasoning was right for attempts within a stage and the code beside it
        # was wrong across stages, which is why reading did not catch it: only
        # summing attempts.json and comparing did.
        for key in ("cost_usd", "discarded_cost_usd"):
            if usage.get(key) is not None:
                merged[key] = str(Decimal(str(merged.get(key) or "0")) + Decimal(str(usage[key])))
            elif key not in merged:
                # Unknown, said out loud. A silent 0.00 would be a claim, and false.
                merged[key] = None
        self._record["usage"] = merged
        self._flush_record()
        self.event("usage", **merged)

    def set(self, **fields: Any) -> None:
        self._record.update(fields)
        self._flush_record()

    def count(self, **counts: Any) -> None:
        self._record["counts"] = {**(self._record.get("counts") or {}), **counts}
        self._flush_record()

    # -- finishing -----------------------------------------------------------

    def _duration_ms(self) -> int:
        return int((datetime.now(UTC) - self._started).total_seconds() * 1000)

    def complete(self, **fields: Any) -> dict[str, Any]:
        self._record["status"] = "complete"
        self._record["duration_ms"] = self._duration_ms()
        self._record.update(fields)
        self._flush_record()
        self.event("run", status="complete", duration_ms=self._record["duration_ms"])
        return dict(self._record)

    def fail(self, *, stage: str, code: str, message: str, remedy: str) -> dict[str, Any]:
        """Mark the run failed, keeping everything gathered before the failure."""
        self.fail_stage(stage)
        self._record["status"] = "failed"
        self._record["duration_ms"] = self._duration_ms()
        self._record["failure"] = {
            "stage": stage,
            "code": code,
            "message": message,
            "remedy": remedy,
        }
        self._flush_record()
        self.event("error", stage=stage, code=code, message=message)
        self.event("run", status="failed", duration_ms=self._record["duration_ms"])
        return dict(self._record)

    @property
    def record(self) -> dict[str, Any]:
        return dict(self._record)


def default_runs_dir_is_writable(runs_dir: str | Path) -> bool:
    """Whether runs can be written where the settings point. Used by `check`.

    The directory usually does not exist yet, and neither do its parents: the
    writer creates the whole chain on first use. So the honest question is
    whether the nearest ancestor that DOES exist can be written to -- checking
    only the immediate parent reports a fresh machine as broken when it is
    merely new.
    """
    path = Path(runs_dir).expanduser()
    probe = path
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            return False
        probe = parent
    return os.access(probe, os.W_OK)
