"""Every capability, as plain Python.

The specification is not subtle about this: *"Everything the tool can do is
reachable from the library... The rule is one-directional and absolute: no
capability exists only in a wrapper. If the CLI can do it, the library can do
it."*

This module is where that rule is kept. Each function here takes ordinary
arguments, resolves settings the same way the CLI does, and returns the same
document the CLI prints. The CLI is one caller of these; a service, a notebook or
a scheduled job is another, and none of them is privileged.

An earlier version of this package failed that rule quietly. The verbs existed,
but only as argparse handlers taking a Namespace -- so a non-CLI caller could
reach the pieces and not the capability, and the tool's own library exposed two
functions where its CLI exposed ten. Nothing was missing; it was just only
assembled inside the wrapper, which is exactly what the rule forbids.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research_core import runs as _runs
from research_core.config import effective_configuration, resolve_settings
from research_core.errors import SmartToolError, UsageError
from research_core.estimate import estimate_run
from research_core.manifest import load_manifest
from research_core.prerequisites import check as _check
from research_core.urls import classify_urls


def _settings(**overrides: Any):
    return resolve_settings(**overrides)


def _runs_dir(runs_dir: str | None) -> str:
    return _settings(runs_dir=runs_dir)["runs_dir"]


def config(
    *,
    runs_dir: str | None = None,
    backend: str | None = None,
    depth: str | None = None,
) -> dict[str, Any]:
    """The effective settings and which tier each came from."""
    return effective_configuration(runs_dir=runs_dir, backend=backend, depth=depth)


def check(package: str, *, runs_dir: str | None = None) -> dict[str, Any]:
    """Whether this host has what ``package``'s manifest declares it needs."""
    return _check(load_manifest(package), runs_dir=_runs_dir(runs_dir))


def manifest(package: str) -> dict[str, Any]:
    """A tool's own manifest as structured data."""
    return load_manifest(package).to_dict()


def list_runs(
    *,
    runs_dir: str | None = None,
    limit: int | None = None,
    status: str | None = None,
    tool: str | None = None,
) -> dict[str, Any]:
    """Runs in the runs directory, newest first."""
    resolved = _runs_dir(runs_dir)
    found = _runs.list_runs(resolved, limit=limit, status=status, tool=tool)
    return {
        "runs_dir": resolved,
        "count": len(found),
        "runs": found,
        "note": (
            "Nothing reaps runs. An accumulating evidence store is the point, so "
            "the tool does not decide when evidence stops being useful."
        ),
    }


def status(run_id: str, *, runs_dir: str | None = None, prog: str = "") -> dict[str, Any]:
    """One run's state, stage progress and usage."""
    run = _runs.load_run(_runs_dir(runs_dir), run_id)
    document = _runs.status_of(run)
    if run.status == "complete" and prog:
        document["next"] = {
            "read": f"{prog} read {run.run_id}",
            "sources": f"{prog} sources {run.run_id}",
        }
    return document


def read(
    run_id: str,
    *,
    part: str = "report",
    lines: int | None = None,
    sections: str | None = None,
    runs_dir: str | None = None,
) -> dict[str, Any]:
    """A bounded view of a run's prose, which always says whether it is whole."""
    settings = _settings(runs_dir=runs_dir)
    run = _runs.load_run(settings["runs_dir"], run_id)
    return _runs.read_part(
        run,
        part=part,
        lines=lines,
        sections=sections,
        max_read_lines=settings["max_read_lines"],
    )


def sources(
    run_id: str,
    *,
    category: str | None = None,
    runs_dir: str | None = None,
    verify: bool = False,
    verify_timeout: float = 5.0,
) -> dict[str, Any]:
    """A run's citations as structured data.

    ``verify`` reaches the network -- HEAD (falling back to GET) every
    source's URL and reports whether it currently resolves. Off by default:
    this verb is otherwise a deterministic, no-network read, and a caller who
    only wants to list what a run recorded should not pay for N round trips it
    never asked for. Reachability is not support -- a source can resolve and
    still not say what a citation claims; this only catches the case where it
    does not resolve at all. Never raises on network failure: a source that
    could not be checked is reported as `reachable: None` with why, distinct
    from one that resolved and said 404.
    """
    document = _runs.sources_of(_runs.load_run(_runs_dir(runs_dir), run_id), category=category)
    if verify:
        from research_core.url_reachability import verify_source_urls

        checks = verify_source_urls(document["sources"], timeout=verify_timeout)
        by_id = {check["id"]: check for check in checks}
        for entry in document["sources"]:
            check = by_id.get(entry.get("id"))
            if check is None:
                continue
            entry["reachable"] = check["reachable"]
            entry["checked_at"] = check["checked_at"]
            entry["status_code"] = check["status_code"]
            if check["error"]:
                entry["check_error"] = check["error"]
        document["verified"] = True
        document["reachable_count"] = sum(1 for c in checks if c["reachable"] is True)
        document["unreachable_count"] = sum(1 for c in checks if c["reachable"] is False)
        document["unknown_count"] = sum(1 for c in checks if c["reachable"] is None)
    return document


def verdicts(
    run_id: str,
    *,
    verdict: str | None = None,
    claim_index: int | None = None,
    runs_dir: str | None = None,
) -> dict[str, Any]:
    """A fact-check run's per-claim results."""
    return _runs.verdicts_of(
        _runs.load_run(_runs_dir(runs_dir), run_id),
        verdict=verdict,
        index=claim_index,
    )


def render(
    run_id: str,
    *,
    fmt: str = "markdown",
    out: str | None = None,
    runs_dir: str | None = None,
) -> dict[str, Any]:
    """Re-shape a stored run. Costs nothing: the work was done when it was made."""
    run = _runs.load_run(_runs_dir(runs_dir), run_id)
    rendered = _runs.render(run, fmt=fmt)
    if out:
        # Resolved, not just expanded: a caller running from an arbitrary
        # working directory gets back a path that means the same thing
        # wherever it is read, not one that is only correct relative to a
        # directory the reader may not share.
        path = Path(out).expanduser().resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            # Loud, and naming the exact path that would not take the write --
            # not a bare traceback escaping from underneath a directory this
            # call may have just created. The render itself already succeeded;
            # only the destination failed, so nothing here is lost, only
            # unwritten.
            raise SmartToolError(
                f"Could not write the rendered {fmt} to {path}: {exc}",
                f"Choose a writable --out path, or drop --out to get the {fmt} "
                "back inline instead.",
            ) from exc
        # A capability that produces an artifact identifies it rather than
        # embedding it in a message the caller then has to carve up.
        return {
            "run_id": run.run_id,
            "format": fmt,
            "path": str(path),
            "bytes": len(rendered.encode("utf-8")),
            "inline": False,
        }
    return {
        "run_id": run.run_id,
        "format": fmt,
        "text": rendered,
        "bytes": len(rendered.encode("utf-8")),
        "inline": True,
    }


def classify(urls: list[str]) -> dict[str, Any]:
    """Sort URLs into academic, news, docs or other."""
    classified = classify_urls(urls)
    counts: dict[str, int] = {}
    for entry in classified:
        counts[entry["category"]] = counts.get(entry["category"], 0) + 1
    return {"count": len(classified), "by_category": counts, "urls": classified}


def estimate(
    *,
    query: str | None = None,
    claims: int | None = None,
    depth: str | None = None,
    runs_dir: str | None = None,
    scope: bool = True,
) -> dict[str, Any]:
    """What a run will cost and how long it will take, before anything is spent."""
    settings = _settings(runs_dir=runs_dir, depth=depth)
    if query is None and claims is None:
        raise UsageError(
            "Nothing to estimate.",
            "Give a query for a research run, or a claim count for a fact-check.",
        )
    document = estimate_run(
        depth=settings["depth"],
        claims=claims,
        backend=settings["backend"],
        scope=scope,
    )
    document["query"] = query
    return document
