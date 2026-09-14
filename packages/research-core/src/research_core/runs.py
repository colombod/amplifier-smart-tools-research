"""Run artifacts, and every deterministic view over them.

A run is a directory. It is the result, and it outlives the call that produced it.
Only the model-backed verbs write one; everything here reads, which is what makes a
shared runs directory safe for several callers at once.

Nothing in this module needs a credential, reaches a network, or touches a model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_core.errors import RunNotFoundError, RunsDirUnusableError, UsageError

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
    }


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
    """Re-shape a stored run. Costs nothing: the run is already on disk."""
    if fmt not in RENDER_FORMATS:
        raise UsageError(
            f"There is no format {fmt!r}.",
            f"Formats: {', '.join(RENDER_FORMATS)}.",
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
