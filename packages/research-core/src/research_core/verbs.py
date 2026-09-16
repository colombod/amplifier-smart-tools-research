"""The deterministic verbs, registered onto a tool's CLI.

Both tools expose the same navigation surface over the same run format, so it is
built once here rather than twice in two thin CLIs. The CLI still does only what a
CLI should -- argument parsing and output shaping -- and this module is library
code that any other caller can use directly.

Nothing here needs a credential or reaches a network.
"""

from __future__ import annotations

import argparse
from typing import Any

from research_core import api
from research_core import runs as _runs
from research_core.estimate import DEPTHS
from research_core.urls import CATEGORIES


def _add_runs_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--runs-dir",
        metavar="PATH",
        help="where runs live for this invocation; overrides the config file and the environment",
    )


# Every handler below is one library call plus the shaping of its result. If one
# of them ever grows a branch, the capability has started living in the wrapper
# and belongs in research_core.api instead.


def cmd_check(args: argparse.Namespace) -> dict[str, Any]:
    return api.check(args._package, runs_dir=args.runs_dir)


def cmd_list(args: argparse.Namespace) -> dict[str, Any]:
    return api.list_runs(
        runs_dir=args.runs_dir, limit=args.limit, status=args.status, tool=args.tool
    )


def cmd_status(args: argparse.Namespace) -> dict[str, Any]:
    return api.status(args.run_id, runs_dir=args.runs_dir, prog=args._prog)


def cmd_read(args: argparse.Namespace) -> dict[str, Any]:
    return api.read(
        args.run_id,
        part=args.part,
        lines=args.lines,
        sections=args.sections,
        runs_dir=args.runs_dir,
    )


def cmd_sources(args: argparse.Namespace) -> dict[str, Any]:
    return api.sources(args.run_id, category=args.category, runs_dir=args.runs_dir)


def cmd_verdicts(args: argparse.Namespace) -> dict[str, Any]:
    return api.verdicts(
        args.run_id,
        verdict=args.verdict,
        claim_index=args.claim_index,
        runs_dir=args.runs_dir,
    )


def cmd_render(args: argparse.Namespace) -> dict[str, Any]:
    return api.render(args.run_id, fmt=args.format, out=args.out, runs_dir=args.runs_dir)


def cmd_classify(args: argparse.Namespace) -> dict[str, Any]:
    return api.classify(args.url)


def cmd_estimate(args: argparse.Namespace) -> dict[str, Any]:
    return api.estimate(
        query=args.query,
        claims=args.claims,
        depth=args.depth,
        runs_dir=args.runs_dir,
        scope=getattr(args, "scope", True),
    )


def register(verbs: Any, *, prog: str, package: str, include_verdicts: bool = False) -> None:
    """Add the deterministic navigation verbs to a tool's subparser set.

    ``package`` is the importable package holding the tool's own SMART_TOOL.md,
    so `check` can look for exactly what that manifest declares rather than what
    a second list somewhere says it declares.
    """

    check = verbs.add_parser(
        "check",
        help="whether this host has what the manifest says this tool needs (deterministic)",
        description=(
            "Look for everything this tool's manifest declares it requires, and "
            "say what was found. The manifest only DECLARES -- reading it runs "
            "nothing -- so detecting whether a prerequisite is actually present "
            "is this verb's job. Reporting a problem is this verb's success: it "
            "exits 0 whether the host is ready or not, because the report is the "
            "deliverable. Branch on `ready` if you want otherwise."
        ),
    )
    _add_runs_dir(check)
    check.set_defaults(handler=cmd_check, _package=package)

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
    estimate.add_argument(
        "--no-scope",
        dest="scope",
        action="store_false",
        help=(
            "price the run as it would be WITHOUT the question-sharpening stage. "
            "Measured over six interleaved live runs: a run costs ~37%% more with "
            "scope than without, so skipping it saves ~27%%. NOT MODELLED, and "
            "said plainly so you stop looking: --max-sources. We have no measured "
            "cost-per-source, and an estimator that silently accepted the flag "
            "while ignoring it would be worse than one that rejects it."
        ),
    )
    estimate.set_defaults(handler=cmd_estimate)
