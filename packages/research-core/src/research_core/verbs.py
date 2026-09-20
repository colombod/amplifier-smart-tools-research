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
from research_core.skill import ArgSpec, CapabilitySkill
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


#: Library-owned `--help` content for every common verb, keyed by verb name.
#:
#: This is the single source ``wire_verb_help`` reads from (via the
#: ``_capability_skill`` default stashed on each subparser below) instead of
#: deriving a document from the argparse subparser itself -- the subparser is
#: a CLI transport detail; a capability documents itself as a library concept.
#: Every ``ArgSpec.param`` here names the actual keyword in ``research_core.api``,
#: and ``tests/test_capability_skills.py`` cross-checks both directions: no
#: parser argument and no public library parameter can go undocumented.
_CAPABILITIES: dict[str, CapabilitySkill] = {
    "check": CapabilitySkill(
        verb="check",
        description=(
            "Look for everything this tool's manifest declares it requires, and say "
            "what was found. Reporting a problem IS this verb's success: it exits 0 "
            "whether the host is ready or not."
        ),
        spends_money=False,
        args=(
            ArgSpec(
                "--runs-dir",
                "runs_dir",
                help=(
                    "where runs live for this invocation, so `check` can also "
                    "report whether it is writable"
                ),
            ),
        ),
        invocation="{prog} check",
        result=(
            "`tool`, `version`, `ready` (bool -- true iff every non-optional "
            "requirement is satisfied), `requirements` (one entry per declared "
            "requirement: `name`, `state` one of `satisfied`/`absent`/`unknown`, "
            "`optional`, `detail`, `purpose`, `install`, `lost_without_it`), "
            "`deterministic_capabilities_available` (always true), `reduced_form` "
            "(present only when an optional requirement is unsatisfied -- what is "
            "lost, one line per requirement), `runs_dir` (present only when "
            "`--runs-dir` is given: `path`, `writable`, `detail`), `engine_home` "
            "(where the embedded agent engine would write, and whether it can), "
            "`credential_surfaces` (the surface names this tool understands), and "
            "-- when the manifest declares an `ai-provider` requirement -- "
            "`provider_availability`: one entry per candidate provider naming "
            "whether IT SPECIFICALLY is usable and, if not, what to install."
        ),
        failures=("None. `check` always exits 0; branch on `ready` for pass/fail logic.",),
    ),
    "list": CapabilitySkill(
        verb="list",
        description="Every run in the runs directory, newest first.",
        spends_money=False,
        args=(
            ArgSpec("--runs-dir", "runs_dir", help="where runs live for this invocation"),
            ArgSpec("--limit", "limit", help="at most N runs"),
            ArgSpec(
                "--status",
                "status",
                choices=("queued", "running", "complete", "failed"),
                help="only runs in this state",
            ),
            ArgSpec("--tool", "tool", help="only runs written by this tool"),
        ),
        invocation="{prog} list --status complete --limit 5",
        result=(
            "`runs_dir` (resolved), `count`, `runs` (one summary per run: `run_id`, "
            "`tool`, `status`, `query`, `created_at`, `sources`, `path`), and `note`."
        ),
        failures=(
            "RunsDirUnusableError (exit 1) if `--runs-dir` exists and is not a "
            "directory. An absent runs directory is NOT an error -- it means "
            "nothing has run yet, and `runs` comes back empty.",
        ),
    ),
    "status": CapabilitySkill(
        verb="status",
        description=(
            "What a run is doing or did: its state, which stages completed, how "
            "long they took, what was spent, and -- when it failed -- where and why."
        ),
        spends_money=False,
        args=(
            ArgSpec("run_id", "run_id", required=True, positional=True),
            ArgSpec("--runs-dir", "runs_dir", help="where runs live for this invocation"),
        ),
        invocation="{prog} status dr-82baa98f",
        result=(
            "`run_id`, `tool`, `status`, `stage`, `stages_complete`, `stages_total`, "
            "`stages` (one entry per stage with timing), `usage`, `duration_ms`, "
            "`failure` (present when failed: `stage`, `code`, `message`, `remedy`), "
            "`path`, `liveness` (`state` one of `growing`/`final`/`abandoned`/"
            "`unknown`, `why`, `poll_again_in_seconds`), `artifacts` (what exists "
            "and how big), and -- when complete -- `next` naming the exact `read` "
            "and `sources` commands to go further."
        ),
        failures=("RunNotFoundError (exit 1) if `run_id` is not in the runs directory.",),
    ),
    "read": CapabilitySkill(
        verb="read",
        description=(
            "A bounded view of a run's prose. Every response carries a completeness "
            "block: when a view is partial it SAYS it is partial and how much was "
            "left out, so a slice can never be mistaken for the whole."
        ),
        spends_money=False,
        args=(
            ArgSpec("run_id", "run_id", required=True, positional=True),
            ArgSpec(
                "--part",
                "part",
                default="report",
                choices=_runs.READABLE_PARTS,
                help="which document to read",
            ),
            ArgSpec("--lines", "lines", help="at most N lines"),
            ArgSpec(
                "--sections",
                "sections",
                help="a section like 2, or a range like 1-3 (numbered `## N. Title` headings)",
            ),
            ArgSpec("--runs-dir", "runs_dir", help="where runs live for this invocation"),
        ),
        invocation="{prog} read dr-82baa98f --part report --lines 50",
        result=(
            "`run_id`, `part`, `text`, and `completeness` (`complete`, "
            "`returned_lines`, `total_lines`, `max_read_lines`, `note`). A "
            "`--sections` request instead carries `sections` (the matched "
            "`number`/`title` pairs) in place of a line window."
        ),
        failures=(
            "UsageError (exit 2): an unknown `--part`, a `--lines` above the "
            "ceiling (raise `max_read_lines` in the config file or use "
            "`--sections` instead of accepting a silently capped slice), a "
            "malformed `--sections` range, or a `--sections` naming a section "
            "this part does not have.",
            "RunNotFoundError (exit 1): the run has no such part at all -- "
            "including a run that failed before writing it, in which case the "
            "message names the stage it failed during.",
        ),
    ),
    "sources": CapabilitySkill(
        verb="sources",
        description=(
            "A run's citations as structured data, so the evidence can be walked "
            "without pulling the whole report into context."
        ),
        spends_money=False,
        args=(
            ArgSpec("run_id", "run_id", required=True, positional=True),
            ArgSpec("--category", "category", choices=CATEGORIES, help="only sources of this kind"),
            ArgSpec("--runs-dir", "runs_dir", help="where runs live for this invocation"),
        ),
        invocation="{prog} sources dr-82baa98f --category academic",
        result=(
            "`run_id`, `count`, `sources` (list of `{id, url, title, category}`), `inherited_from`."
        ),
        failures=("RunNotFoundError (exit 1) if the run has no `sources.json`.",),
    ),
    "verdicts": CapabilitySkill(
        verb="verdicts",
        description=(
            "One entry per claim: the claim, its verdict, the confidence, the "
            "reasoning and the sources it rests on. `unverifiable` means checked "
            "and no adequate evidence either way -- never a synonym for refuted."
        ),
        spends_money=False,
        args=(
            ArgSpec("run_id", "run_id", required=True, positional=True),
            ArgSpec(
                "--verdict",
                "verdict",
                choices=("supported", "refuted", "unverifiable", "opinion"),
                help="only claims with this verdict",
            ),
            ArgSpec("--claim-index", "claim_index", help="only claim number N"),
            ArgSpec("--runs-dir", "runs_dir", help="where runs live for this invocation"),
        ),
        invocation="{prog} verdicts fc-1a2b3c4d --verdict refuted",
        result="`run_id`, `count`, `tally` (counts per verdict), `verdicts` (the filtered list).",
        failures=(
            "UsageError (exit 2) if this run is not a fact-check run and has no "
            "`verdicts.json` -- use `read` for a research run instead.",
        ),
    ),
    "render": CapabilitySkill(
        verb="render",
        description=(
            "Re-shape a run that is already on disk: markdown, json, or "
            "bibliography. Costs nothing -- the work was done when the run was made."
        ),
        spends_money=False,
        args=(
            ArgSpec("run_id", "run_id", required=True, positional=True),
            ArgSpec(
                "--format",
                "fmt",
                default="markdown",
                choices=_runs.RENDER_FORMATS,
                help="output shape",
            ),
            ArgSpec(
                "--out",
                "out",
                help="write the artifact here (absolute path returned) instead of inlining it",
            ),
            ArgSpec("--runs-dir", "runs_dir", help="where runs live for this invocation"),
        ),
        invocation="{prog} render dr-82baa98f --format json --out /tmp/dr-82baa98f.json",
        result=(
            "Without `--out`: `run_id`, `format`, `text` (the rendered document), "
            "`bytes`, `inline: true`. With `--out`: the same, but `path` (absolute) "
            "in place of `text`, and `inline: false`."
        ),
        failures=(
            "UsageError (exit 2) for an unknown `--format`.",
            "RunNotFoundError (exit 1) if the run does not exist.",
            "RunFailedError (exit 1) if the run failed: a failed run has nothing "
            "complete to assemble into a finished-shaped document. Run `status` "
            "for what happened, or `read`/`sources` for what survives.",
        ),
    ),
    "classify": CapabilitySkill(
        verb="classify",
        description=(
            "Sort URLs into academic, news, docs or other -- a pure table lookup, "
            "the same categorisation the reports use."
        ),
        spends_money=False,
        args=(
            ArgSpec(
                "--url",
                "urls",
                required=True,
                help="repeatable -- give it once per URL",
            ),
        ),
        invocation=(
            "{prog} classify --url https://arxiv.org/abs/1234 --url https://github.com/x/y"
        ),
        result=(
            "`count`, `by_category` (counts per category), `urls` (`{url, category}` per input)."
        ),
        failures=("None -- an unparseable or empty URL classifies as `other`, never an error.",),
    ),
    "estimate": CapabilitySkill(
        verb="estimate",
        description=(
            "What a run is expected to cost and how long it is expected to take, "
            "computed from the request alone before anything is spent."
        ),
        spends_money=False,
        args=(
            ArgSpec("--query", "query", help="the research question"),
            ArgSpec("--claims", "claims", help="how many claims to check"),
            ArgSpec("--depth", "depth", choices=DEPTHS, help="override the configured depth"),
            ArgSpec("--runs-dir", "runs_dir", help="where runs live for this invocation"),
            ArgSpec(
                "--no-scope",
                "scope",
                default=True,
                help=(
                    "price the run as it would be WITHOUT the question-sharpening "
                    "stage (measured ~27%% cheaper; NOT modelled: --max-sources)"
                ),
            ),
        ),
        invocation='{prog} estimate --query "impact of X on Y" --depth high',
        result=(
            "`depth`, `backend`, `claims`, `estimated_sources`, `estimated_seconds`, "
            "`estimated_tokens_in`, `estimated_tokens_out`, `estimated_cost_usd`, "
            "`estimated_cost_usd_range` (`low`/`high` -- a band, not a point), "
            "`scope`, `calibration_runs`, `basis`, `is_estimate: true`, `caveat`, "
            "and `query` (echoed back, or `null`)."
        ),
        failures=(
            "UsageError (exit 2) if neither `--query` nor `--claims` is given: "
            "there is nothing to estimate.",
        ),
    ),
}


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
    check.set_defaults(
        handler=cmd_check, _package=package, _capability_skill=_CAPABILITIES["check"]
    )

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
    listing.set_defaults(handler=cmd_list, _capability_skill=_CAPABILITIES["list"])

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
    status.set_defaults(handler=cmd_status, _prog=prog, _capability_skill=_CAPABILITIES["status"])

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
    read.set_defaults(handler=cmd_read, _capability_skill=_CAPABILITIES["read"])

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
    sources.set_defaults(handler=cmd_sources, _capability_skill=_CAPABILITIES["sources"])

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
        verdicts.set_defaults(handler=cmd_verdicts, _capability_skill=_CAPABILITIES["verdicts"])

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
    render.set_defaults(handler=cmd_render, _capability_skill=_CAPABILITIES["render"])

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
    classify.set_defaults(handler=cmd_classify, _capability_skill=_CAPABILITIES["classify"])

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
    estimate.set_defaults(handler=cmd_estimate, _capability_skill=_CAPABILITIES["estimate"])
