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


def skill() -> str:
    """This tool rendered as an Agent Skill, for a host that consumes skills.

    The same contract `--help` states, arranged for a reader deciding whether
    and how to CALL something rather than whether to install it.
    """
    from research_core.skill import render_skill

    return render_skill(
        manifest(),
        verbs={
            "research": "answer a research question with evidence",
            "estimate": "what a run will cost and how long, BEFORE spending",
            "check": "whether this host has what the tool needs, and what each gap costs you",
            "config": "the effective settings and which tier each came from",
            "list": "runs in the runs directory, newest first",
            "status": "one run's state, stage progress and usage",
            "read": "a bounded slice of a run's prose; says if it is partial",
            "sources": "a run's citations as structured data",
            "render": "re-shape a stored run: markdown, json, bibliography",
            "classify": "sort URLs into academic, news, docs or other",
            "manifest": "this tool's own manifest",
        },
        model_backed=("research",),
        result_shape=(
            'One JSON document on stdout. Success is {"result": ...}; failure is'
            '{"error": {"code", "message", "remedy"}} with a non-zero exit. Progress'
            "and diagnostics go to stderr, never stdout, so you can parse one without "
            "filtering the other. A research result is a BRIEF plus a POINTER: `brief` "
            "is short and IS the answer, not a teaser; `path` names a run directory "
            "that outlives the call; `inline` says whether the full report came back "
            "with the envelope or was left on disk because it was too large. "
            "`confidence` is one of low, medium or high and reflects what the evidence "
            "actually supports -- when it says low, believe it."
        ),
        navigation=(
            "Never swallow a whole run. Every response -- INCLUDING A REFUSAL -- "
            "carries `affordances`: named next moves, each with a CLI form, a library "
            "form, what it returns, what it costs, and whether it needs a credential. "
            "They are all $0.00 and all credential-free, so an agent on an unconfigured "
            "host can still explore a result someone else paid for. A successful run "
            "also carries a `ladder` -- brief, report, sources, raw -- with each rung's "
            "REAL size in bytes, so you can decide what to pull before pulling it. SIZE "
            "THE READ FIRST. `status <id>` is free and lists every artifact with its "
            "bytes and line count, so you never need a throwaway read to discover how "
            "long a report is. Then `read <id> --lines N` for a bounded slice, or `read "
            "<id> --sections 1-3` for specific numbered sections -- a single section "
            "like `2` or a range like `1-3`. A read response carries a `sections` list "
            "naming the number and title of everything it returned, which is how you "
            "learn what sections exist. EVERY read carries a completeness block: when a "
            "view is partial it says so and by how much, and an over-ceiling request is "
            "refused rather than silently truncated -- so never present a slice as the "
            "whole. `sources <id> --category academic` returns citations as filterable "
            "data. `render <id> --format bibliography` reshapes a stored run without "
            "re-running it. FOR A LONG RUN, use `--detach`. It returns in under a "
            "second with part one: the run id, where the rest will appear, and an "
            "explicit `not_yet_true` list -- read that before treating an accepted "
            "request as an answer. Then ask `status <id>` and read `liveness.state`: "
            "`growing` means wait `poll_again_in_seconds` and ask again, `final` means "
            "the work is done, and `abandoned` means the process is gone and nothing "
            "more is coming. Poll `liveness.state`, never the stage names."
            "CONTROLLING WHAT IT COSTS AND WHAT COMES BACK. `--no-scope` skips the "
            "question-sharpening stage. Measured both ways: on a question already clear "
            "and bounded it saves ~37% of the cost and ~69% of the wall-clock and "
            "changes nothing a blind judge could see; on a vague one it LOSES a blind "
            "comparison 6 for 6. Pass it when you know exactly what you are asking -- "
            "typically when a program composed the question -- and leave it off when a "
            "person phrased it. `--max-sources N` caps evidence gathering. `--backend` "
            "picks where evidence comes from. `--no-inline` keeps the full report OUT "
            "of the response and returns only the pointer, which is what you want when "
            "your context is tight; `--inline` forces it in. `--runs-dir PATH` is the "
            "shared evidence store -- point several callers at one directory and `fact- "
            "check --from-run <id>` can reuse evidence this tool already paid for, "
            "instead of gathering it again. `read <id> --part brief` returns just the "
            "short answer when that is all you need."
        ),
        examples=(
            (
                "Find out what is known, cheaply, before committing to a decision:",
                (
                    "deep-research estimate --query 'do state-based CRDTs converge?' --depth "
                    "low\n deep-research research --query 'do state-based CRDTs converge?' "
                    "--depth low"
                ),
            ),
            (
                "Read a large result without pulling all of it into context:",
                (
                    "deep-research read dr-70ce2d29 --lines 40\n deep-research sources "
                    "dr-70ce2d29 --category academic"
                ),
            ),
            ("Check what this host can actually do, spending nothing:", "deep-research check"),
        ),
    )


CAPABILITIES["skill"] = skill
