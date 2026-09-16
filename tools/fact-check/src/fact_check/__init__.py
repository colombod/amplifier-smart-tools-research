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

from fact_check.checking import check_claims

__version__ = "0.1.0"

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
    depth: str | None = None,
    runs_dir: str | None = None,
) -> dict[str, Any]:
    """What a check will cost and how long it will take, before anything is spent."""
    return api.estimate(claims=claims, depth=depth, runs_dir=runs_dir)


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
            'One JSON document on stdout. Success is {"result": ...}; failure is'
            '{"error": {"code", "message", "remedy"}} with a non-zero exit. The `tally`'
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
