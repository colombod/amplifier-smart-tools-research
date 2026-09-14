"""deep-research: answers a research question with evidence.

**The library is the tool.** Everything the CLI can do is reachable from here,
with ordinary Python arguments and ordinary return values -- no capability exists
only in the wrapper. The CLI is one caller of this module; a service, a notebook
or a scheduled job is another, and none of them is privileged.

Nothing here requires a credential to import, and no engine or backend is
imported at module level.

    >>> import deep_research
    >>> deep_research.check()["ready"]
    >>> run = deep_research.research(query="...")
    >>> deep_research.sources(run["run_id"], category="academic")
"""

from __future__ import annotations

from typing import Any

from research_core import Manifest, api, load_manifest

from deep_research.research import research

__version__ = "0.1.0"

PACKAGE = "deep_research"
PROG = "deep-research"


def manifest() -> Manifest:
    """This tool's own manifest, read from the copy built into the package."""
    return load_manifest(PACKAGE)


def check(*, runs_dir: str | None = None) -> dict[str, Any]:
    """Whether this host has what the manifest says this tool needs."""
    return api.check(PACKAGE, runs_dir=runs_dir)


def config(
    *,
    runs_dir: str | None = None,
    backend: str | None = None,
    depth: str | None = None,
) -> dict[str, Any]:
    """The effective settings, and which tier each came from."""
    return api.config(runs_dir=runs_dir, backend=backend, depth=depth)


def list_runs(
    *,
    runs_dir: str | None = None,
    limit: int | None = None,
    status: str | None = None,
    tool: str | None = None,
) -> dict[str, Any]:
    """Runs in the runs directory, newest first."""
    return api.list_runs(runs_dir=runs_dir, limit=limit, status=status, tool=tool)


def run_status(run_id: str, *, runs_dir: str | None = None) -> dict[str, Any]:
    """One run's state, stage progress and usage."""
    return api.status(run_id, runs_dir=runs_dir, prog=PROG)


def read(
    run_id: str,
    *,
    part: str = "report",
    lines: int | None = None,
    sections: str | None = None,
    runs_dir: str | None = None,
) -> dict[str, Any]:
    """A bounded view of a run's prose, which always says whether it is whole."""
    return api.read(run_id, part=part, lines=lines, sections=sections, runs_dir=runs_dir)


def sources(
    run_id: str, *, category: str | None = None, runs_dir: str | None = None
) -> dict[str, Any]:
    """A run's citations as structured data."""
    return api.sources(run_id, category=category, runs_dir=runs_dir)


def render(
    run_id: str,
    *,
    fmt: str = "markdown",
    out: str | None = None,
    runs_dir: str | None = None,
) -> dict[str, Any]:
    """Re-shape a stored run: markdown, json or bibliography."""
    return api.render(run_id, fmt=fmt, out=out, runs_dir=runs_dir)


def classify(urls: list[str]) -> dict[str, Any]:
    """Sort URLs into academic, news, docs or other."""
    return api.classify(urls)


def estimate(
    *,
    query: str | None = None,
    depth: str | None = None,
    runs_dir: str | None = None,
) -> dict[str, Any]:
    """What a run will cost and how long it will take, before anything is spent."""
    return api.estimate(query=query, depth=depth, runs_dir=runs_dir)


#: Every capability, by the name the CLI uses for it. A test asserts this covers
#: the CLI's whole verb table, so a verb cannot be added to the wrapper without
#: also being reachable here.
CAPABILITIES: dict[str, Any] = {
    "manifest": manifest,
    "check": check,
    "config": config,
    "list": list_runs,
    "status": run_status,
    "read": read,
    "sources": sources,
    "render": render,
    "classify": classify,
    "estimate": estimate,
    "research": research,
}

__all__ = [
    "CAPABILITIES",
    "PACKAGE",
    "PROG",
    "Manifest",
    "__version__",
    "check",
    "classify",
    "config",
    "estimate",
    "list_runs",
    "manifest",
    "read",
    "render",
    "research",
    "run_status",
    "sources",
]
