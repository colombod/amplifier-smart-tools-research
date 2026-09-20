"""fact-check: checks claims against evidence, one verdict per claim.

**The library is the tool.** Everything the CLI can do is reachable from here,
with ordinary Python arguments and ordinary return values -- no capability exists
only in the wrapper. The CLI is one caller of this module; a service, a notebook
or a scheduled job is another, and none of them is privileged.

Nothing here requires a credential to import, and no engine or backend is
imported at module level.

    >>> import fact_check
    >>> fact_check.check()["ready"]
    >>> fact_check.verdicts("fc-...", verdict="refuted")
"""

from __future__ import annotations

from typing import Any

from research_core import Manifest, api, load_manifest
from research_core.skill import ArgSpec, CapabilitySkill

from fact_check.checking import check_claims

__version__ = "0.10.0"

PACKAGE = "fact_check"
PROG = "fact-check"


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


def verdicts(
    run_id: str,
    *,
    verdict: str | None = None,
    claim_index: int | None = None,
    runs_dir: str | None = None,
) -> dict[str, Any]:
    """The per-claim results, filterable by verdict."""
    return api.verdicts(run_id, verdict=verdict, claim_index=claim_index, runs_dir=runs_dir)


def classify(urls: list[str]) -> dict[str, Any]:
    """Sort URLs into academic, news, docs or other."""
    return api.classify(urls)


def estimate(
    *,
    claims: int | None = None,
    query: str | None = None,
    depth: str | None = None,
    runs_dir: str | None = None,
    scope: bool = True,
) -> dict[str, Any]:
    """What a check will cost and how long it will take, before anything is spent.

    ``query`` and ``scope`` price a research-shaped or scope-skipped request;
    they exist here because the CLI's `estimate --query` and `estimate
    --no-scope` do, and the library must reach everything the CLI reaches.
    """
    return api.estimate(claims=claims, query=query, depth=depth, runs_dir=runs_dir, scope=scope)


#: Library-owned `--help` content for this tool's PRIMARY capability, in the
#: same shape `research_core.verbs._CAPABILITIES` gives the shared verbs --
#: built from `check_claims`'s own signature and behaviour, not derived from
#: the argparse subparser in `cli.py`. `check-claims` is this tool's own
#: reason to exist, so it is the one capability an agent most needs the full
#: document for, and `tests/test_capability_skills.py` cross-checks this
#: against both the parser and the public library signature so neither can
#: drift undocumented. LIVES HERE, in the library, rather than in `cli.py`:
#: the CLI only wires it into the parser, it does not define it.
#:
#: `reasoner`, `stream` and `run_id` are excluded from `args` for the same
#: reason as `deep_research.RESEARCH_CAPABILITY`'s: the first two are
#: Python-embedding test seams with no CLI spelling, and `run_id` is wiring
#: the detached child uses to resume the identifier its parent already
#: published.
CHECK_CLAIMS_CAPABILITY = CapabilitySkill(
    verb="check-claims",
    description=(
        "Assess each claim against evidence a research run already gathered, "
        "and return one verdict per claim: supported, refuted, unverifiable, "
        "or opinion. Model-backed: it makes one model call per claim and "
        "fails saying so when no reasoning provider is configured, rather "
        "than guessing. Evidence is not gathered here -- pass --from-run."
    ),
    spends_money=True,
    args=(
        ArgSpec("--claim", "claim", help="a claim to check; repeatable"),
        ArgSpec("--claims-file", "claims_file", help="one claim per line"),
        ArgSpec(
            "--from-run",
            "from_run",
            help="use this run's evidence instead of gathering it again",
        ),
        ArgSpec(
            "--strict",
            "strict",
            default=False,
            help="treat every claim as complex: slower, more expensive, and `estimate` says so",
        ),
        ArgSpec("--runs-dir", "runs_dir", help="where runs live for this invocation"),
        ArgSpec("--timeout-ms", "timeout_ms", help="wall-clock budget for one reasoning turn"),
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
                "background. ONE MODEL CALL PER CLAIM -- estimated 330s for "
                "three claims, 959s for ten, and that estimator is known to "
                "under-predict"
            ),
        ),
    ),
    invocation=(
        "{prog} check-claims --from-run dr-70ce2d29 --claim 'CRDTs converge without coordination.'"
    ),
    result=(
        "`run_id`, `status`, `brief`, `tally` (counts per verdict -- small, "
        "and it IS the answer), `claim_count`, `source_count`, "
        "`inherited_from` (the run this evidence came from), `confidence`, "
        "`path` (the run directory), `report_bytes`, `inline`, `usage`, "
        "`next` (the exact `verdicts`/`sources` commands to go further). "
        "`unverifiable` means CHECKED and no adequate evidence either way -- "
        "never a synonym for `refuted`. With `--detach`, part one comes back "
        "instead: `accepted`, `detached`, `pid`, `claim_count`, "
        "`inherited_from`, `not_yet_true`, and `poll_again_in_seconds`."
    ),
    failures=(
        "NoProviderError (exit 3): no reasoning provider is configured.",
        "UsageError (exit 2): no claims given (neither `--claim` nor "
        "`--claims-file`), or no `--from-run`.",
        "NoEvidence (exit 1): the named run has no sources to check claims against.",
        "SmartToolError wrapping ClaimUncheckable (exit 1): a claim could "
        "not be checked after `max_attempts` rejections -- distinct from "
        "`unverifiable`, which means checked and the evidence was inadequate. "
        "Verdicts already recorded before the stop are kept.",
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
    "verdicts": verdicts,
    "check-claims": check_claims,
    "classify": classify,
    "estimate": estimate,
}

__all__ = [
    "CAPABILITIES",
    "PACKAGE",
    "PROG",
    "Manifest",
    "__version__",
    "check",
    "check_claims",
    "classify",
    "config",
    "estimate",
    "list_runs",
    "manifest",
    "read",
    "render",
    "run_status",
    "sources",
    "verdicts",
]


#: How to OBTAIN this tool. Prepended to the installed SKILL.md and
#: deliberately absent from `--help`, whose reader already has the binary.
INSTALL = (
    (
        "as a CLI",
        "uv tool install "
        "'git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/fact-check'",
    ),
    (
        "as a library, from another project",
        "uv add "
        "'fact-check @ git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/fact-check'",
    ),
    (
        "once, without installing",
        "uvx --from "
        "'git+https://github.com/colombod/"
        "amplifier-smart-tools-research#subdirectory=tools/fact-check' "
        "fact-check --help",
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
            "check-claims": "assess claims against evidence, one verdict per claim",
            "verdicts": "a run's verdicts, filterable by verdict",
            "estimate": "what a check will cost and how long, BEFORE spending",
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
        model_backed=("check-claims",),
        result_shape=(
            'One JSON document per call. Success -- {"result": ...} -- is on '
            "STDOUT. Failure -- "
            '{"error": {"code", "message", "remedy"}} with a non-zero exit -- is on '
            "STDERR, with stdout left empty; if stdout is empty, the call failed. "
            "The `tally` "
            "travels inline because it is small and it IS the answer; the per-claim "
            "detail stays on disk. VERDICT MEANINGS MATTER HERE: `supported` and "
            "`refuted` mean the evidence says so; `unverifiable` means the claim was "
            "CHECKED and no adequate evidence was found either way -- it is never "
            "reported as `refuted`, and you must not read it as one. `opinion` means "
            "the claim is not checkable against evidence at all. A claim the tool could "
            "not check for a mechanical reason FAILS the run rather than being filed "
            "under `unverifiable`."
        ),
        navigation=(
            "Never swallow a whole run. Every response -- INCLUDING A REFUSAL -- "
            "carries `affordances`: named next moves, each with a CLI form, a library "
            "form, what it returns, what it costs, and whether it needs a credential. "
            "They are all $0.00 and all credential-free. `verdicts <id>` returns every "
            "verdict as data and `--verdict refuted` filters to the ones a caller "
            "usually acts on; each carries the claim, the reasoning and the source ids "
            "it rests on, so you can audit one without reading the rest. `read <id> "
            "--lines N` always carries a completeness block -- when a view is partial "
            "it says so and by how much, so never present a slice as the whole. "
            "Evidence is not gathered here: pass `--from-run <id>` to reuse a deep- "
            "research run that already has sources, which is the point of a shared runs "
            "directory."
            "GO DEEPER PER VERB. This document covers the tool; every verb has its own. "
            "`<verb> --help` returns that verb's agent-facing document -- what it does, "
            "whether it spends money, every flag and what it is FOR, and how to read "
            "what comes back. `<verb> -h` is the terse flag table for a person. The "
            "split holds at every level: -h is always for a human who already knows the "
            "verb, --help is always the document for an agent deciding whether and how "
            "to call it. When you are about to call something and want more than this "
            "overview gives you, ask the verb directly."
            "WHEN THE RUN IS LONG. This verb makes ONE MODEL CALL PER CLAIM, so its "
            "wall-clock scales with the claim count rather than being fixed. Measured: "
            "two claims took 42 seconds and $0.15. Our own estimator predicts 330 "
            "seconds for three claims and 959 for ten -- it is PESSIMISTIC here, where "
            "the same estimator is optimistic for research, so treat both as rough. If "
            "your per-call limit is tight or the claim list is long, pass `--detach`: "
            "it returns part one in about a second with the run id and an explicit "
            "`not_yet_true` list, and you rejoin with `status <id>`. `liveness.state` "
            "is `growing` while work continues, `final` when it is done, and "
            "`abandoned` when the process is gone and nothing more is coming -- that "
            "last one is TERMINAL, so stop polling. Whatever reached disk before a "
            "death stays readable, so a dead run is usually salvageable rather than a "
            "total loss. THE WAIT IS YOURS TO SHAPE: `poll_again_in_seconds` is a hint "
            "about when new work will exist, not an instruction to sleep that long "
            "inside one call, and polling more often is free because `status` is "
            "deterministic and needs no credential."
        ),
        examples=(
            (
                "Check claims against evidence another run already gathered:",
                (
                    "fact-check check-claims --from-run dr-70ce2d29 \\\n --claim 'CRDTs "
                    "converge without coordination.' \\\n --claim 'CRDTs are the best data "
                    "structure.'"
                ),
            ),
            (
                "Look at only the claims the evidence contradicted:",
                "fact-check verdicts fc-7c26fe85 --verdict refuted",
            ),
        ),
    )


CAPABILITIES["skill"] = skill


#: Where the pointer SKILL.md sends a reader who does not have the tool.
REPOSITORY = "https://github.com/colombod/amplifier-smart-tools-research"
AUTHOR = "colombod"

#: Phrases a host matches on when deciding this skill is relevant.
TRIGGERS = ("fact check", "verify this claim", "is this true", "check claims")


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
