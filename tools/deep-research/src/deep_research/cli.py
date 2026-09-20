"""Thin CLI over the library.

Argument parsing, I/O conventions and structured output live here. Domain logic
does not: anything the CLI can do, the library can do, and every handler below is
one library call plus the shaping of its result. Domain logic in this file would
be capability the library cannot reach, which is a defect.

Nothing in this module imports an agent engine, at module level or otherwise.
`--help` must work with every provider variable scrubbed from the environment.
"""

from __future__ import annotations

import argparse
from typing import Any, NoReturn

from research_core import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_REFUSED,
    SmartToolError,
    emit,
    emit_error,
)
from research_core.skill import ArgSpec, CapabilitySkill, add_help_flags, wire_verb_help
from research_core.verbs import register as register_common_verbs

import deep_research

PROG = "deep-research"

#: Library-owned `--help` content for this tool's PRIMARY capability, in the
#: same shape `research_core.verbs._CAPABILITIES` gives the nine shared verbs
#: -- built from `deep_research.research`'s own signature and behaviour, not
#: derived from the argparse subparser below it. `research` and `check-claims`
#: are each tool's own reason to exist, so they are the two capabilities an
#: agent most needs the full document for, and `tests/test_capability_skills.py`
#: cross-checks this against both the parser and the public library signature
#: so neither can drift undocumented.
#:
#: `reasoner`, `stream` and `run_id` are excluded from `args` on purpose: the
#: first two are Python-embedding test seams (a `Reasoner` object and a
#: writable stream have no CLI spelling), and `run_id` is wiring the detached
#: child uses to resume the identifier its parent already published -- never a
#: caller's own choice. `max_attempts` is a real tunable but has no CLI flag
#: yet either; see `RESEARCH_CAPABILITY`'s exclusion note mirrored in
#: `tests/test_capability_skills.py`.
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
        "points at a source this run does not have -- `warnings`. With "
        "`--detach`, part one comes back instead: `accepted`, `detached`, "
        "`pid`, `not_yet_true` (what is not true yet -- read it before "
        "treating acceptance as an answer), and `poll_again_in_seconds`."
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

_DESCRIPTION = """\
deep-research -- answers a research question with evidence.

Multi-source research, synthesised into a short brief, backed by citations you can
act on. The answer is a brief plus a pointer to the full evidence on disk.
"""

_EPILOG = """\
USING THE RESULT

  Every response is a single JSON document on stdout. Success is
  {"result": ...}; failure is {"error": {"code", "message", "remedy"}} with a
  non-zero exit. Diagnostics and progress go to stderr, never stdout, so you can
  parse one without filtering the other.

  A research result is a BRIEF plus a POINTER. `brief` is short and is the
  answer, not a teaser. `path` points at a run directory that outlives the call:
  the full report, the normalised sources, and the raw responses behind them.
  `inline` tells you whether the full report came back with the envelope or was
  left on disk because it was too large.

NAVIGATING A LARGE RESULT

  Do not try to swallow a whole run. Every envelope carries a `next` block
  naming the exact commands to go further, and every one of them is
  deterministic -- they cost nothing, spend no tokens, and need no credentials:

    read <id>     a bounded slice of the report. Always carries a completeness
                  block: when a view is partial it SAYS it is partial and how
                  much was left out. An over-ceiling request is refused rather
                  than silently capped, so a slice can never be mistaken for the
                  whole.
    sources <id>  the citations as structured data, filterable by category --
                  walk the evidence without pulling the report into context.
    render <id>   the same run in another shape: markdown, json, bibliography.

  Exit codes: 0 the verb did its job (including reporting that something is
  broken), 1 the operation failed, 2 the request was impossible or refused,
  3 a model-backed verb was asked for with no provider configured.

OUTPUT FORMAT

  Every capability returns JSON on stdout, always -- there is no text mode and
  no --json flag, because every consumer of this tool is code. The
  specification leaves the format to each capability and asks only that the
  help text say which one it is. This is it.
"""


class _EnvelopeParser(argparse.ArgumentParser):
    """An argparse parser whose usage errors come back as the error envelope.

    argparse writes its own message to stderr and exits 2. A caller parsing
    stdout would see nothing at all and have to infer the failure from an empty
    result, so the message is routed through the envelope instead.
    """

    def error(self, message: str) -> NoReturn:
        emit_error(
            "usage",
            message,
            f"Run `{PROG} --help` for the accepted verbs and arguments.",
        )
        raise SystemExit(EXIT_REFUSED)


def build_parser() -> argparse.ArgumentParser:
    parser = _EnvelopeParser(
        prog=PROG,
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        # Built without argparse's help so `-h` and `--help` can differ: argparse
        # binds both spellings to one action, and they answer different readers.
        add_help=False,
    )
    add_help_flags(parser, skill=deep_research.skill)
    verbs = parser.add_subparsers(dest="verb", metavar="<verb>", required=True)

    manifest = verbs.add_parser(
        "manifest",
        help="this tool's own manifest as structured data (deterministic)",
        description=(
            "Print this tool's manifest -- what it is, what it needs, and which of "
            "its prerequisites are optional. Deterministic: runs with no provider "
            "configured and no credentials of any kind."
        ),
    )
    manifest.set_defaults(handler=_cmd_manifest)

    skill = verbs.add_parser(
        "skill",
        help="this tool as an Agent Skill, for a host that consumes skills (deterministic)",
        description=(
            "Render this tool as an Agent Skill -- YAML frontmatter plus markdown -- "
            "which a host can write straight into a skills directory and an agent can "
            "read as it reads any other skill. `--help` is written for a person and "
            "leaves an agent to infer the contract from English; this states the same "
            "contract in the shape hosts already have machinery for. Deterministic."
        ),
    )
    skill.set_defaults(handler=_cmd_skill)

    config = verbs.add_parser(
        "config",
        help="the effective settings, and which tier each came from (deterministic)",
        description=(
            "Print the effective settings and, for each, where it came from: an "
            "explicit argument, the config file, an environment variable, or the "
            "built-in default -- in that order of precedence. Anything seen and "
            "deliberately not honoured is reported as such rather than vanishing. "
            "Credential surfaces report only the tier that satisfied them, never a "
            "value. Deterministic: runs with no provider configured."
        ),
    )
    config.add_argument(
        "--runs-dir",
        metavar="PATH",
        help="override the runs directory for this invocation",
    )
    config.add_argument("--backend", metavar="NAME", help="override the evidence backend")
    config.add_argument(
        "--depth",
        choices=("low", "medium", "high"),
        help="override how hard a run works before it reports",
    )
    config.set_defaults(handler=_cmd_config)

    research = verbs.add_parser(
        "research",
        help="run the research workflow -- MODEL-BACKED, spends tokens",
        description=(
            "Research a question and leave the evidence on disk. Model-backed: it "
            "consumes tokens, may answer differently on a second run, and fails "
            "saying so when no backend is configured rather than returning a "
            "lesser answer. Progress is written to stderr as it runs AND kept in "
            "the run's own event log, so a caller who was not watching can still "
            "reconstruct what happened."
        ),
    )
    research.add_argument("--query", required=True, metavar="TEXT")
    research.add_argument("--depth", choices=("low", "medium", "high"))
    research.add_argument("--max-sources", type=int, metavar="N")
    research.add_argument("--backend", metavar="NAME")
    research.add_argument("--runs-dir", metavar="PATH")
    research.add_argument("--timeout-ms", type=int, metavar="MS")
    research.add_argument(
        "--inline",
        dest="inline",
        action="store_true",
        default=None,
        help="return the whole report in the envelope, whatever its size",
    )
    research.add_argument(
        "--no-inline",
        dest="inline",
        action="store_false",
        help="always return a pointer, never the report itself",
    )
    research.add_argument(
        "--no-scope",
        dest="scope",
        action="store_false",
        help=(
            "skip the question-sharpening stage. Measured: on a question that is "
            "already clear and bounded the run costs ~37%% more WITH scope, so skipping "
            "it saves ~27%% of the cost and ~41%% of the "
            "wall-clock and changes nothing a blind judge could see -- but on a "
            "vague one it loses a blind comparison 6 for 6. Use it when you know "
            "what you are asking; leave it on when you are not sure."
        ),
    )
    research.add_argument("--quiet", action="store_true", help="do not stream progress to stderr")
    research.add_argument(
        "--detach",
        action="store_true",
        help=(
            "return part one immediately and continue the work in the background. "
            "The response says what is NOT yet true and names `status` as the way "
            "to find out when it is. MEASURED runs have taken 57 to 784 seconds -- "
            "the upper figure is real, not a guess -- so blocking for "
            "that is a choice, not an obligation."
        ),
    )
    research.set_defaults(handler=_cmd_research, _capability_skill=RESEARCH_CAPABILITY)

    register_common_verbs(verbs, prog=PROG, package="deep_research", include_verdicts=False)

    # EVERY verb gets the same -h / --help split the root has, wired as a
    # post-pass so a verb added later inherits it without anyone remembering.
    wire_verb_help(verbs, prog=PROG, model_backed=("research",))

    return parser


def _cmd_manifest(_args: argparse.Namespace) -> dict[str, Any]:
    return deep_research.manifest().to_dict()


def _cmd_skill(_args: argparse.Namespace) -> dict[str, Any]:
    return {"skill": deep_research.skill()}


def _cmd_research(args: argparse.Namespace) -> dict[str, Any]:
    return deep_research.research(
        args.query,
        depth=args.depth,
        backend=args.backend,
        max_sources=args.max_sources,
        runs_dir=args.runs_dir,
        timeout_ms=args.timeout_ms,
        inline=args.inline,
        quiet=args.quiet,
        detach=args.detach,
        scope=args.scope,
    )


def _cmd_config(args: argparse.Namespace) -> dict[str, Any]:
    return deep_research.config(runs_dir=args.runs_dir, backend=args.backend, depth=args.depth)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = args.handler(args)
    except SmartToolError as exc:
        emit_error(
            exc.code, exc.message, exc.remedy, exc.affordances, artifact_path=exc.artifact_path
        )
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 - the envelope is the contract
        emit_error(
            "error",
            f"{type(exc).__name__}: {exc}",
            "This is a defect in the tool. Report it with the traceback on stderr.",
        )
        return EXIT_FAILED
    emit(payload)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
