"""Run artifacts, and every deterministic view over them.

A run is a directory. It is the result, and it outlives the call that produced it.
Only the model-backed verbs write one; everything here reads, which is what makes a
shared runs directory safe for several callers at once.

Nothing in this module needs a credential, reaches a network, or touches a model.
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_core.errors import RunFailedError, RunNotFoundError, RunsDirUnusableError, UsageError

RUN_FILE = "run.json"
BRIEF_FILE = "brief.md"
REPORT_FILE = "report.md"
SOURCES_FILE = "sources.json"
VERDICTS_FILE = "verdicts.json"
EVENTS_FILE = "events.jsonl"
RAW_DIR = "raw"

#: How many lines a bounded read returns when the caller does not say.
DEFAULT_READ_LINES = 120

READABLE_PARTS = ("report", "brief")
RENDER_FORMATS = ("markdown", "json", "bibliography")


@dataclass(frozen=True)
class Run:
    """One run on disk. Constructed by reading, never by guessing."""

    run_id: str
    path: Path
    record: dict[str, Any]

    @property
    def tool(self) -> str:
        return str(self.record.get("tool", "unknown"))

    @property
    def status(self) -> str:
        return str(self.record.get("status", "unknown"))

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    def file(self, name: str) -> Path:
        return self.path / name

    def summary(self) -> dict[str, Any]:
        """The shape `list` returns: enough to choose between runs, no more."""
        return {
            "run_id": self.run_id,
            "tool": self.tool,
            "status": self.status,
            "query": self.record.get("query"),
            "created_at": self.record.get("created_at"),
            "sources": (self.record.get("counts") or {}).get("sources"),
            "path": str(self.path),
        }


def _read_json(path: Path, what: str) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunNotFoundError(
            f"{what} is missing at {path}.",
            "The run directory is incomplete. A run that failed before writing it "
            "reports status 'failed' in run.json; this one does not.",
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RunNotFoundError(
            f"{what} at {path} could not be read: {exc}",
            "The run directory is corrupt. Nothing here rewrites it; move it aside.",
        ) from exc


def runs_root(runs_dir: str | Path) -> Path:
    """The runs directory, checked. Absent is fine; unusable is not."""
    path = Path(runs_dir).expanduser()
    if path.exists() and not path.is_dir():
        raise RunsDirUnusableError(
            f"The runs directory at {path} is not a directory.",
            "Point --runs-dir, the config file, or RESEARCH_RUNS_DIR somewhere else.",
        )
    return path


def list_runs(
    runs_dir: str | Path,
    *,
    limit: int | None = None,
    status: str | None = None,
    tool: str | None = None,
) -> list[dict[str, Any]]:
    """Every run in the directory, newest first.

    A directory that does not exist yet is an empty list, not an error: nothing has
    been run, which is a normal state and not a broken one.
    """
    root = runs_root(runs_dir)
    if not root.exists():
        return []

    runs: list[Run] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not (entry / RUN_FILE).exists():
            continue
        record = _read_json(entry / RUN_FILE, "run.json")
        runs.append(Run(run_id=record.get("run_id", entry.name), path=entry, record=record))

    runs.sort(key=lambda r: str(r.record.get("created_at") or ""), reverse=True)
    selected = [
        run
        for run in runs
        if (status is None or run.status == status) and (tool is None or run.tool == tool)
    ]
    if limit is not None:
        selected = selected[:limit]
    return [run.summary() for run in selected]


def load_run(runs_dir: str | Path, run_id: str) -> Run:
    """One run by id. Not found is a named refusal, never an empty result."""
    root = runs_root(runs_dir)
    path = root / run_id
    if not path.is_dir() or not (path / RUN_FILE).exists():
        raise RunNotFoundError(
            f"No run {run_id!r} in {root}.",
            "Run `list` to see what is there. A run lives in the runs directory it "
            "was written to, and several callers may be pointed at different ones.",
        )
    record = _read_json(path / RUN_FILE, "run.json")
    return Run(run_id=record.get("run_id", run_id), path=path, record=record)


#: What a caller actually needs to know when it rejoins a detached run. Not the
#: stage names -- those are detail -- but whether waiting longer is worth it.
GROWING = "growing"
FINAL = "final"
ABANDONED = "abandoned"


def liveness_of(run: Run) -> dict[str, Any]:
    """Is this run still working, finished, or gone?

    The one distinction that makes detaching safe. A run record says "running"
    until its own process writes otherwise, and a process that dies never writes
    anything -- so without this check every crashed run reads as busy, forever.
    A caller polling it would wait for a result that is never coming, which is
    strictly worse than having blocked in the first place.

    PID REUSE is the known hole: the operating system may hand our recorded pid
    to an unrelated process, and this would then report `growing` for a run that
    is dead. It is a much smaller hole than having no check at all, and we say so
    rather than implying more certainty than we have. A pid from another host is
    not checked at all, and reports `unknown` instead of guessing.
    """
    status = run.status
    if status in ("complete", "failed"):
        return {
            "state": FINAL,
            "why": f"the run finished with status {status!r}",
            "poll_again_in_seconds": None,
        }

    pid = run.record.get("pid")
    host = run.record.get("host")
    if host and host != socket.gethostname():
        return {
            "state": "unknown",
            "why": (
                f"this run was started on {host!r} and we are on "
                f"{socket.gethostname()!r}, so its process cannot be checked from here"
            ),
            "poll_again_in_seconds": 30,
        }
    if not isinstance(pid, int):
        return {
            "state": "unknown",
            "why": "the run record carries no pid, so liveness cannot be established",
            "poll_again_in_seconds": 30,
        }

    if _process_alive(pid):
        return {
            "state": GROWING,
            "why": f"process {pid} is alive and the run has not finished",
            "poll_again_in_seconds": 10,
        }
    return {
        "state": ABANDONED,
        "why": (
            f"the run record says {status!r} but process {pid} is gone, so nothing "
            "is going to finish it. Whatever reached disk is all there will be."
        ),
        "poll_again_in_seconds": None,
    }


def _process_alive(pid: int) -> bool:
    """Signal 0 asks the kernel about a pid without disturbing it."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # It exists; it just is not ours to signal. Alive is the honest answer.
        return True
    except OSError:
        return False
    return True


def status_of(run: Run) -> dict[str, Any]:
    """State, stage progress and usage. Safe to poll."""
    stages = run.record.get("stages") or []
    done = [s for s in stages if s.get("status") == "complete"]
    current = next((s for s in stages if s.get("status") == "running"), None)
    return {
        "run_id": run.run_id,
        "tool": run.tool,
        "status": run.status,
        "stage": (current or {}).get("name") or (run.record.get("failure") or {}).get("stage"),
        "stages_complete": len(done),
        "stages_total": len(stages),
        "stages": stages,
        "usage": run.record.get("usage"),
        "duration_ms": run.record.get("duration_ms"),
        "failure": run.record.get("failure"),
        "path": str(run.path),
        # Growing, final, or gone -- the question a rejoining caller is actually
        # asking, answered without making it infer anything from stage names.
        "liveness": liveness_of(run),
        # How big the artifacts are, so a caller can size a read BEFORE making
        # one. Without this the only way to learn a report's length was to read
        # part of it and look at the completeness block -- a throwaway call to
        # discover how to make the real one.
        "artifacts": _artifacts_of(run),
    }


def _artifacts_of(run: Run) -> list[dict[str, Any]]:
    """What exists in this run, how big it is, and how to ask for it."""
    out: list[dict[str, Any]] = []
    for name in ("brief.md", "report.md", "sources.json", "verdicts.json"):
        path = run.file(name)
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            size, lines = path.stat().st_size, len(raw.splitlines())
        except OSError:
            continue
        out.append({"name": name, "bytes": size, "lines": lines})
    return out


def _completeness(returned: int, total: int, ceiling: int, what: str) -> dict[str, Any]:
    complete = returned >= total
    if complete:
        note = f"read is COMPLETE: all {total} lines of {what} are here."
    else:
        note = (
            f"read is INCOMPLETE: {total - returned} lines of {what} sit beyond this "
            f"window. Widen --lines (up to {ceiling}) or ask for specific --sections "
            "rather than presenting this slice as the whole."
        )
    return {
        "complete": complete,
        "returned_lines": returned,
        "total_lines": total,
        "max_read_lines": ceiling,
        "note": note,
    }


def _split_sections(text: str) -> list[tuple[int, str, list[str]]]:
    """Split a report on its numbered `## N. Title` headings."""
    sections: list[tuple[int, str, list[str]]] = []
    current: tuple[int, str, list[str]] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            number = len(sections) + 1
            head, _, rest = heading.partition(".")
            if head.strip().isdigit():
                number = int(head.strip())
                heading = rest.strip() or heading
            current = (number, heading, [line])
            sections.append(current)
        elif current is not None:
            current[2].append(line)
    return sections


def parse_section_range(spec: str) -> tuple[int, int]:
    """Parse `3` or `1-3`. A malformed range is refused, never guessed at."""
    text = spec.strip()
    try:
        if "-" in text:
            first, _, last = text.partition("-")
            start, end = int(first), int(last)
        else:
            start = end = int(text)
    except ValueError as exc:
        raise UsageError(
            f"--sections {spec!r} is not a section or a range.",
            "Give a section number like 2, or a range like 1-3.",
        ) from exc
    if start < 1 or end < start:
        raise UsageError(
            f"--sections {spec!r} is not a range that can exist.",
            "Sections are numbered from 1, and a range runs forwards.",
        )
    return start, end


def read_part(
    run: Run,
    *,
    part: str = "report",
    lines: int | None = None,
    sections: str | None = None,
    max_read_lines: int = 5000,
) -> dict[str, Any]:
    """A bounded view of a run's prose, which always says whether it is whole.

    An over-ceiling request is REFUSED rather than silently capped. Silently
    capping is how a caller ends up presenting a slice as the whole thing,
    which is the failure this entire verb exists to prevent.
    """
    if part not in READABLE_PARTS:
        raise UsageError(
            f"There is no part {part!r}.",
            f"Readable parts: {', '.join(READABLE_PARTS)}.",
        )
    if lines is not None and lines > max_read_lines:
        raise UsageError(
            f"--lines {lines} is above the ceiling of {max_read_lines}.",
            "Raise max_read_lines in the config file if you genuinely want more, "
            "or ask for specific --sections. Refusing beats returning a silently "
            "capped slice.",
        )
    if lines is not None and lines < 1:
        raise UsageError("--lines must be at least 1.", "Ask for one or more lines.")

    path = run.file(REPORT_FILE if part == "report" else BRIEF_FILE)
    if not path.exists():
        failure = run.record.get("failure")
        if run.failed and failure:
            raise RunNotFoundError(
                f"Run {run.run_id} has no {part}: it failed during the "
                f"{failure.get('stage')} stage.",
                "Run `status` to see how far it got. The evidence gathered before "
                "the failure is kept in this run.",
            )
        raise RunNotFoundError(
            f"Run {run.run_id} has no {part} at {path}.",
            "Run `status` to see what this run actually contains.",
        )

    text = path.read_text(encoding="utf-8")
    all_lines = text.splitlines()

    if sections is not None:
        start, end = parse_section_range(sections)
        found = _split_sections(text)
        if not found:
            raise UsageError(
                f"Run {run.run_id}'s {part} has no numbered sections.",
                "Use --lines instead.",
            )
        chosen = [s for s in found if start <= s[0] <= end]
        if not chosen:
            available = ", ".join(str(s[0]) for s in found)
            raise UsageError(
                f"No section in {sections!r}. This {part} has sections: {available}.",
                "Ask for one of the sections that exists.",
            )
        body = [line for _, _, lines_ in chosen for line in lines_]
        return {
            "run_id": run.run_id,
            "part": part,
            "sections": [{"number": n, "title": t} for n, t, _ in chosen],
            "text": "\n".join(body),
            "completeness": _completeness(len(body), len(all_lines), max_read_lines, f"the {part}"),
        }

    window = lines if lines is not None else min(DEFAULT_READ_LINES, max_read_lines)
    body = all_lines[:window]
    return {
        "run_id": run.run_id,
        "part": part,
        "text": "\n".join(body),
        "completeness": _completeness(len(body), len(all_lines), max_read_lines, f"the {part}"),
    }


def sources_of(run: Run, *, category: str | None = None) -> dict[str, Any]:
    """A run's citations as structured data."""
    document = _read_json(run.file(SOURCES_FILE), "sources.json")
    sources = document.get("sources", [])
    if category is not None:
        sources = [s for s in sources if s.get("category") == category]
    return {
        "run_id": run.run_id,
        "count": len(sources),
        "sources": sources,
        "inherited_from": document.get("inherited_from"),
    }


def verdicts_of(
    run: Run, *, verdict: str | None = None, index: int | None = None
) -> dict[str, Any]:
    """A fact-check run's per-claim results."""
    path = run.file(VERDICTS_FILE)
    if not path.exists():
        raise UsageError(
            f"Run {run.run_id} has no verdicts: it is a {run.tool} run.",
            "Verdicts belong to fact-check runs. Use `read` for a research run.",
        )
    document = _read_json(path, "verdicts.json")
    entries = document.get("verdicts", [])
    if verdict is not None:
        entries = [v for v in entries if v.get("verdict") == verdict]
    if index is not None:
        entries = [v for v in entries if v.get("index") == index]
    return {
        "run_id": run.run_id,
        "count": len(entries),
        "tally": run.record.get("tally"),
        "verdicts": entries,
    }


def citation_ids(text: str) -> list[str]:
    """Every `[sN]` marker in order, deduplicated."""
    import re

    seen: list[str] = []
    for match in re.findall(r"\[(s\d+)\]", text):
        if match not in seen:
            seen.append(match)
    return seen


def dangling_citations(run: Run) -> list[str]:
    """Citation markers in the prose that no source in this run defines.

    The deterministic spine's sharpest check, and the cheapest: a model citing a
    source it was never given is the characteristic failure of research tooling,
    and it is a set membership test rather than a judgment.
    """
    known = {s.get("id") for s in sources_of(run)["sources"]}
    cited: list[str] = []
    for name in (BRIEF_FILE, REPORT_FILE):
        path = run.file(name)
        if path.exists():
            for marker in citation_ids(path.read_text(encoding="utf-8")):
                if marker not in cited:
                    cited.append(marker)
    return [marker for marker in cited if marker not in known]


def render(run: Run, *, fmt: str = "markdown") -> str:
    """Re-shape a stored run. Costs nothing: the run is already on disk.

    Refused outright for a failed run, in every format. A failed run keeps
    whatever brief/report material was written before the failure -- that
    material is real and `read`/`sources` can still see it directly -- but
    assembling it into a document shaped like a FINISHED run (this verb's
    whole job) would silently present a partial result as complete, which is
    exactly the failure mode this project refuses rather than softens. `json`
    is refused too even though it already embeds ``run.record["status"]``:
    one rule for the verb, not one rule per format a caller has to remember.
    """
    if fmt not in RENDER_FORMATS:
        raise UsageError(
            f"There is no format {fmt!r}.",
            f"Formats: {', '.join(RENDER_FORMATS)}.",
        )
    if run.failed:
        failure = run.record.get("failure") or {}
        stage = failure.get("stage", "an earlier stage")
        raise RunFailedError(
            f"Run {run.run_id} failed during the {stage!r} stage; there is "
            "nothing complete to render.",
            "Run `status` to see what happened and what survives. Use `read` "
            "or `sources` to inspect whatever evidence was written before the "
            "failure -- `render` only assembles a finished-shaped document, "
            "which this run does not have.",
        )

    sources = sources_of(run)["sources"]

    if fmt == "json":
        document = {"run": run.record, "sources": sources}
        for name, key in ((REPORT_FILE, "report"), (BRIEF_FILE, "brief")):
            path = run.file(name)
            if path.exists():
                document[key] = path.read_text(encoding="utf-8")
        if run.file(VERDICTS_FILE).exists():
            document["verdicts"] = _read_json(run.file(VERDICTS_FILE), "verdicts.json")
        return json.dumps(document, indent=2, sort_keys=True) + "\n"

    if fmt == "bibliography":
        lines = [f"# Sources for {run.run_id}", ""]
        for category in ("academic", "news", "docs", "other"):
            grouped = [s for s in sources if s.get("category") == category]
            if not grouped:
                continue
            lines.append(f"## {category.title()}")
            lines.append("")
            for source in grouped:
                lines.append(f"- [{source.get('id')}] {source.get('title')}")
                lines.append(f"  {source.get('url')}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    parts: list[str] = []
    for name in (BRIEF_FILE, REPORT_FILE):
        path = run.file(name)
        if path.exists():
            parts.append(path.read_text(encoding="utf-8").rstrip())
    parts.append(render(run, fmt="bibliography").rstrip())
    return "\n\n".join(parts) + "\n"
