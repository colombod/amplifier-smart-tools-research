"""The deterministic verbs, registered onto a tool's CLI.

Both tools expose the same navigation surface over the same run format, so it is
built once here rather than twice in two thin CLIs. The CLI still does only what a
CLI should -- argument parsing and output shaping -- and this module is library
code that any other caller can use directly.

Nothing here needs a credential or reaches a network.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from research_core import runs as _runs
from research_core.config import resolve_settings
from research_core.errors import UsageError
from research_core.estimate import DEPTHS, estimate_run
from research_core.urls import CATEGORIES, classify_urls


def _settings(args: argparse.Namespace):
    return resolve_settings(runs_dir=getattr(args, "runs_dir", None))


def _runs_dir(args: argparse.Namespace) -> str:
    return _settings(args)["runs_dir"]


def _add_runs_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--runs-dir",
        metavar="PATH",
        help="where runs live for this invocation; overrides the config file and the environment",
    )


def cmd_list(args: argparse.Namespace) -> dict[str, Any]:
    runs_dir = _runs_dir(args)
    found = _runs.list_runs(runs_dir, limit=args.limit, status=args.status, tool=args.tool)
    return {
        "runs_dir": runs_dir,
        "count": len(found),
        "runs": found,
        "note": (
            "Nothing reaps runs. An accumulating evidence store is the point, so "
            "the tool does not decide when evidence stops being useful."
        ),
    }


def cmd_status(args: argparse.Namespace) -> dict[str, Any]:
    run = _runs.load_run(_runs_dir(args), args.run_id)
    document = _runs.status_of(run)
    if run.status == "complete":
        document["next"] = {
            "read": f"{args._prog} read {run.run_id} --sections 1-2",
            "sources": f"{args._prog} sources {run.run_id}",
        }
    return document


def cmd_read(args: argparse.Namespace) -> dict[str, Any]:
    settings = _settings(args)
    run = _runs.load_run(settings["runs_dir"], args.run_id)
    return _runs.read_part(
        run,
        part=args.part,
        lines=args.lines,
        sections=args.sections,
        max_read_lines=settings["max_read_lines"],
    )


def cmd_sources(args: argparse.Namespace) -> dict[str, Any]:
    run = _runs.load_run(_runs_dir(args), args.run_id)
    return _runs.sources_of(run, category=args.category)


def cmd_verdicts(args: argparse.Namespace) -> dict[str, Any]:
    run = _runs.load_run(_runs_dir(args), args.run_id)
    return _runs.verdicts_of(run, verdict=args.verdict, index=args.claim_index)


def cmd_render(args: argparse.Namespace) -> dict[str, Any]:
    run = _runs.load_run(_runs_dir(args), args.run_id)
    rendered = _runs.render(run, fmt=args.format)
    if args.out:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
        # A capability that produces an artifact identifies it rather than
        # embedding it in a message the caller then has to carve up.
        return {
            "run_id": run.run_id,
            "format": args.format,
            "path": str(out),
            "bytes": len(rendered.encode("utf-8")),
            "inline": False,
        }
    return {
        "run_id": run.run_id,
        "format": args.format,
        "text": rendered,
        "bytes": len(rendered.encode("utf-8")),
        "inline": True,
    }


def cmd_classify(args: argparse.Namespace) -> dict[str, Any]:
    classified = classify_urls(args.url)
    counts: dict[str, int] = {}
    for entry in classified:
        counts[entry["category"]] = counts.get(entry["category"], 0) + 1
    return {"count": len(classified), "by_category": counts, "urls": classified}


def cmd_estimate(args: argparse.Namespace) -> dict[str, Any]:
    settings = _settings(args)
    depth = args.depth or settings["depth"]
    if args.query is None and args.claims is None:
        raise UsageError(
            "Nothing to estimate.",
            "Give --query for a research run, or --claims N for a fact-check.",
        )
    document = estimate_run(depth=depth, claims=args.claims, backend=settings["backend"])
    document["query"] = args.query
    return document


def register(verbs: Any, *, prog: str, include_verdicts: bool = False) -> None:
    """Add the deterministic navigation verbs to a tool's subparser set."""

    listing = verbs.add_parser(
        "list",
        help="runs in the runs directory, newest first (deterministic)",
        description=(
            "Every run in the runs directory. Runs accumulate and nothing reaps "
            "them, so this is how you find out what is already there -- including "
            "runs another caller wrote, if you share a runs directory."
        ),
    )
    _add_runs_dir(listing)
    listing.add_argument("--limit", type=int, metavar="N", help="at most N runs")
    listing.add_argument(
        "--status",
        choices=("queued", "running", "complete", "failed"),
        help="only runs in this state",
    )
    listing.add_argument("--tool", metavar="NAME", help="only runs written by this tool")
    listing.set_defaults(handler=cmd_list)

    status = verbs.add_parser(
        "status",
        help="one run's state, stage progress and usage (deterministic)",
        description=(
            "What a run is doing or did: its state, which stages completed, how "
            "long they took, what was spent, and -- when it failed -- where and "
            "why. Safe to poll."
        ),
    )
    _add_runs_dir(status)
    status.add_argument("run_id", metavar="<id>")
    status.set_defaults(handler=cmd_status, _prog=prog)

    read = verbs.add_parser(
        "read",
        help="a bounded slice of a run's prose, which says if it is partial (deterministic)",
        description=(
            "A bounded view of a run's prose. Every response carries a "
            "completeness block: when a view is partial it SAYS it is partial and "
            "how much was left out, so a slice can never be mistaken for the "
            "whole. A request above the ceiling is refused rather than silently "
            "capped."
        ),
    )
    _add_runs_dir(read)
    read.add_argument("run_id", metavar="<id>")
    read.add_argument("--part", choices=_runs.READABLE_PARTS, default="report", help="what to read")
    read.add_argument("--lines", type=int, metavar="N", help="at most N lines")
    read.add_argument("--sections", metavar="RANGE", help="a section like 2, or a range like 1-3")
    read.set_defaults(handler=cmd_read)

    sources = verbs.add_parser(
        "sources",
        help="a run's citations as structured data (deterministic)",
        description=(
            "The citations behind a run, as data rather than prose. This is how to "
            "walk the evidence without pulling the whole report into context."
        ),
    )
    _add_runs_dir(sources)
    sources.add_argument("run_id", metavar="<id>")
    sources.add_argument("--category", choices=CATEGORIES, help="only sources of this kind")
    sources.set_defaults(handler=cmd_sources)

    if include_verdicts:
        verdicts = verbs.add_parser(
            "verdicts",
            help="the per-claim results, filterable by verdict (deterministic)",
            description=(
                "One entry per claim: the claim, its verdict, the confidence, the "
                "reasoning and the sources it rests on. Audit one verdict without "
                "reading the others. `unverifiable` means checked and no adequate "
                "evidence either way -- it is never a synonym for refuted."
            ),
        )
        _add_runs_dir(verdicts)
        verdicts.add_argument("run_id", metavar="<id>")
        verdicts.add_argument(
            "--verdict",
            choices=("supported", "refuted", "unverifiable", "opinion"),
            help="only claims with this verdict",
        )
        verdicts.add_argument("--claim-index", type=int, metavar="N", help="only claim number N")
        verdicts.set_defaults(handler=cmd_verdicts)

    render = verbs.add_parser(
        "render",
        help="re-shape a stored run: markdown, json, bibliography (deterministic)",
        description=(
            "Re-shape a run that is already on disk. Costs nothing and spends no "
            "tokens, because the work was done when the run was made. --out writes "
            "the artifact and returns its path instead of inlining it."
        ),
    )
    _add_runs_dir(render)
    render.add_argument("run_id", metavar="<id>")
    render.add_argument(
        "--format", choices=_runs.RENDER_FORMATS, default="markdown", help="output shape"
    )
    render.add_argument("--out", metavar="PATH", help="write the artifact here")
    render.set_defaults(handler=cmd_render)

    classify = verbs.add_parser(
        "classify",
        help="sort URLs into academic, news, docs or other (deterministic)",
        description=(
            "Sort URLs the way this tool's reference lists are grouped. A pure "
            "table lookup: no network, no model, no credentials. Exposed because a "
            "caller assembling its own source list wants the same categorisation "
            "the reports use."
        ),
    )
    classify.add_argument("--url", action="append", required=True, metavar="URL")
    classify.set_defaults(handler=cmd_classify)

    estimate = verbs.add_parser(
        "estimate",
        help="what a run will cost and how long it will take (deterministic)",
        description=(
            "What a run is expected to cost and how long it is expected to take, "
            "computed from the request alone before anything is spent. It is an "
            "estimate and says so; the run's own record reports what was actually "
            "spent."
        ),
    )
    _add_runs_dir(estimate)
    estimate.add_argument("--query", metavar="TEXT", help="the research question")
    estimate.add_argument("--claims", type=int, metavar="N", help="how many claims to check")
    estimate.add_argument("--depth", choices=DEPTHS, help="override the configured depth")
    estimate.set_defaults(handler=cmd_estimate)
