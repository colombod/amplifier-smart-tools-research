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
from research_core.skill import ArgSpec, CapabilitySkill

from deep_research.research import research

__version__ = "0.10.0"

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
    run_id: str,
    *,
    category: str | None = None,
    runs_dir: str | None = None,
    verify: bool = False,
    verify_timeout: float = 5.0,
) -> dict[str, Any]:
    """A run's citations as structured data.

    ``verify`` reaches the network -- see `research_core.api.sources` for what
    it checks and why it defaults off.
    """
    return api.sources(
        run_id,
        category=category,
        runs_dir=runs_dir,
        verify=verify,
        verify_timeout=verify_timeout,
    )


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
    claims: int | None = None,
    depth: str | None = None,
    runs_dir: str | None = None,
    scope: bool = True,
) -> dict[str, Any]:
    """What a run will cost and how long it will take, before anything is spent.

    ``claims`` and ``scope`` price a fact-check-shaped or scope-skipped request;
    they exist here because the CLI's `estimate --claims` and `estimate
    --no-scope` do, and the library must reach everything the CLI reaches.
    """
    return api.estimate(query=query, claims=claims, depth=depth, runs_dir=runs_dir, scope=scope)


#: Library-owned `--help` content for this tool's PRIMARY capability, in the
#: same shape `research_core.verbs._CAPABILITIES` gives the shared verbs --
#: built from `research`'s own signature and behaviour, not derived from the
#: argparse subparser in `cli.py`. `research` is this tool's own reason to
#: exist, so it is the one capability an agent most needs the full document
#: for, and `tests/test_capability_skills.py` cross-checks this against both
#: the parser and the public library signature so neither can drift
#: undocumented. LIVES HERE, in the library, rather than in `cli.py`: the CLI
#: only wires it into the parser, it does not define it.
#:
#: `reasoner`, `stream` and `run_id` are excluded from `args` on purpose: the
#: first two are Python-embedding test seams (a `Reasoner` object and a
#: writable stream have no CLI spelling), and `run_id` is wiring the detached
#: child uses to resume the identifier its parent already published -- never a
#: caller's own choice.
RESEARCH_CAPABILITY = CapabilitySkill(
    verb="research",
    description=(
        "Research a question and leave the evidence on disk: a brief plus a "
        "pointer to the full report, the numbered sources and the backend's "
        "raw replies. Model-backed: it consumes tokens, may answer "
        "differently on a second run, and fails saying so when no evidence "
        "backend or reasoning provider is configured, rather than returning "
        "a lesser answer built on nothing."
    ),
    spends_money=True,
    args=(
        ArgSpec("--query", "query", required=True, help="the research question"),
        ArgSpec(
            "--depth",
            "depth",
            choices=("low", "medium", "high"),
            help="how hard the run works before it reports; unset uses the configured default",
        ),
        ArgSpec(
            "--max-sources",
            "max_sources",
            help="cap how many sources gather keeps; unset means no cap",
        ),
        ArgSpec(
            "--backend",
            "backend",
            help="which backend acquires evidence: perplexity or agent",
        ),
        ArgSpec("--runs-dir", "runs_dir", help="where runs live for this invocation"),
        ArgSpec(
            "--timeout-ms",
            "timeout_ms",
            help="wall-clock budget for the reasoning stages",
        ),
        ArgSpec(
            "--inline",
            "inline",
            default=None,
            help="return the whole report in the envelope, whatever its size",
        ),
        ArgSpec(
            "--no-inline",
            "inline",
            default=None,
            help="always return a pointer, never the report itself",
        ),
        ArgSpec(
            "--no-scope",
            "scope",
            default=True,
            help=(
                "skip the question-sharpening stage. Measured ~27% cheaper and "
                "~41% faster on a question that is already clear and bounded, "
                "but loses a blind comparison 6 for 6 on a vague one -- leave it "
                "on when you are not sure"
            ),
        ),
        ArgSpec(
            "--max-attempts",
            "max_attempts",
            help=(
                "how many times a stage may be repaired before the run "
                "fails; unset uses the configured default (3)"
            ),
        ),
        ArgSpec("--quiet", "quiet", default=False, help="do not stream progress to stderr"),
        ArgSpec(
            "--detach",
            "detach",
            default=False,
            help=(
                "return part one immediately and continue the work in the "
                "background. MEASURED runs have taken 57 to 784 seconds"
            ),
        ),
    ),
    invocation='{prog} research --query "do state-based CRDTs converge?" --depth low',
    result=(
        "`run_id`, `status`, `brief`, `confidence` (low/medium/high -- when it "
        "says low, believe it), `source_count`, `path` (the run directory), "
        "`report_bytes`, `inline` (whether `report` came back with the "
        "envelope or was left on disk), `usage`, `next` (the exact `read`/"
        "`sources`/`render` commands to go further), `ladder` (brief/report/"
        "sources/raw, each with its REAL size in bytes), `affordances` (named "
        "next moves, each free and credential-free), and -- when a citation "
        "points at a source this run does not have, or the backend omitted a "
        "malformed source entry -- `warnings`. With `--detach`, part one "
        "comes back instead: `accepted`, `detached`, `pid`, `not_yet_true` "
        "(what is not true yet -- read it before treating acceptance as an "
        "answer), and `poll_again_in_seconds`."
    ),
    failures=(
        "NoProviderError (exit 3): no evidence backend, or no reasoning "
        "provider, is configured. Run `check` to see what this host resolves.",
        "NoEvidence (exit 1): the gather stage returned no sources -- nothing "
        "to base an answer on. The run record is kept; `status <id>` shows "
        "where it stopped.",
        "SmartToolError wrapping AttemptsExhausted (exit 1): a stage was "
        "rejected `max_attempts` times in a row; every attempt is kept in "
        "the run's `attempts.json`.",
        "UsageError (exit 2): an unrecognised `--backend` name.",
    ),
)


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


#: How to OBTAIN this tool. Prepended to the installed SKILL.md and
#: deliberately absent from `--help`, whose reader already has the binary.
INSTALL = (
    (
        "as a CLI",
        "uv tool install "
        "'git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/deep-research'",
    ),
    (
        "as a library, from another project",
        "uv add "
        "'deep-research @ git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/deep-research'",
    ),
    (
        "once, without installing",
        "uvx --from "
        "'git+https://github.com/colombod/"
        "amplifier-smart-tools-research#subdirectory=tools/deep-research' "
        "deep-research --help",
    ),
)


def skill() -> str:
    """This tool rendered as an Agent Skill, for a host that consumes skills.

    The same contract `--help` states, arranged for a reader deciding whether
    and how to CALL something rather than whether to install it.

    Deliberately carries NO install instructions, same as `--help`:
    `test_acquisition_lives_in_the_pointer_and_never_in_help` holds this to
    account. A reader of `--help` (or this) already has the binary; the
    pointer SKILL.md that `pointer_skill()` builds is for the reader who may
    not.
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
            'One JSON document per call. Success -- {"result": ...} -- is on '
            "STDOUT. Failure -- "
            '{"error": {"code", "message", "remedy"}} with a non-zero exit -- is on '
            "STDERR, with stdout left empty. Progress and diagnostics are always on "
            "stderr, never stdout, on both success and failure, so you can parse "
            "stdout for a result without ever filtering a failure out of it -- and "
            "if stdout is empty, the call failed; read stderr. A research result is "
            "a BRIEF plus a POINTER: `brief` "
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
            "data -- add `--verify` (and optionally `--verify-timeout`) to HEAD every "
            "source's URL and learn which still resolve; it is the one flag here that "
            "reaches the network, so it is off by default and never required. "
            "`render <id> --format bibliography` reshapes a stored run without "
            "re-running it. FOR A LONG RUN, use `--detach`. It returns in under a "
            "second with part one: the run id, where the rest will appear, and an "
            "explicit `not_yet_true` list -- read that before treating an accepted "
            "request as an answer. Then ask `status <id>` and read `liveness.state`: "
            "`growing` means the work is still happening, `final` means it is done, and "
            "`abandoned` means the process is gone and nothing more is coming. Poll "
            "`liveness.state`, never the stage names. THE WAIT IS YOURS TO SHAPE, and "
            "this is the part callers get wrong: `poll_again_in_seconds` is a HINT "
            "about when new work will exist, NOT an instruction to sleep that long "
            "inside one call. A run can outlast your own per-call limit -- ours have "
            "taken 658 and 784 seconds -- so fitting the wait to your ceiling is your "
            "job, not this tool's, and how you do it is your business. Polling MORE "
            "often than the hint is free and safe: `status` is deterministic, costs "
            "$0.00 and needs no credential, so many short checks are as correct as "
            "few long ones."
            "CONTROLLING WHAT IT COSTS AND WHAT COMES BACK. `--no-scope` skips the "
            "question-sharpening stage. Measured both ways: on a question already clear "
            "and bounded a run costs ~37% MORE with scope than without -- so skipping "
            "it saves ~27% of the cost and ~41% of the wall-clock -- and "
            "changes nothing a blind judge could see; on a vague one it LOSES a blind "
            "comparison 6 for 6. THE TEST IS THE QUESTION, NOT WHO TYPED IT: pass "
            "`--no-scope` when the question already names its subject, its scope and "
            "what would answer it, so there is nothing left to sharpen -- a person can "
            "ask a question that sharp, and a program can emit a woolly one. If you "
            "cannot tell, leave it on; paying the extra 37% is the cheaper mistake. "
            "`estimate --no-scope` prices it for you rather than making you do the "
            "arithmetic; `--max-sources` is deliberately NOT modelled by estimate, "
            "because we have no measured cost-per-source. "
            "`--max-sources N` caps evidence gathering. `--backend` "
            "picks where evidence comes from. `--no-inline` keeps the full report OUT "
            "of the response and returns only the pointer, which is what you want when "
            "your context is tight; `--inline` forces it in. `--runs-dir PATH` is the "
            "shared evidence store -- point several callers at one directory and `fact- "
            "check --from-run <id>` can reuse evidence this tool already paid for, "
            "instead of gathering it again. `read <id> --part brief` returns just the "
            "short answer when that is all you need."
            "GO DEEPER PER VERB. This document covers the tool; every verb has its own. "
            "`<verb> --help` returns that verb's agent-facing document -- what it does, "
            "whether it spends money, every flag and what it is FOR, and how to read "
            "what comes back. `<verb> -h` is the terse flag table for a person. The "
            "split holds at every level: -h is always for a human who already knows the "
            "verb, --help is always the document for an agent deciding whether and how "
            "to call it. When you are about to call something and want more than this "
            "overview gives you, ask the verb directly."
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


#: Where the pointer SKILL.md sends a reader who does not have the tool.
REPOSITORY = "https://github.com/colombod/amplifier-smart-tools-research"
AUTHOR = "colombod"

#: Phrases a host matches on when deciding this skill is relevant.
TRIGGERS = ("deep research", "research this", "find sources", "what is known about")


def pointer_skill() -> str:
    """The installed SKILL.md: install, use `--help`, stay current.

    Deliberately NOT a copy of `--help`. The skill file and the binary reach a
    user from different places -- `npx skills add` tracks a branch, `uv tool
    install ...@tag` is pinned -- so a copy can describe flags the installed
    tool does not have. A pointer cannot.
    """
    from research_core.skill import render_pointer_skill

    return render_pointer_skill(
        manifest(),
        install=INSTALL,
        repository=REPOSITORY,
        author=AUTHOR,
        triggers=TRIGGERS,
    )
