"""Thin CLI over the library.

Argument parsing, I/O conventions and structured output live here. Domain logic
does not: anything the CLI can do, the library can do, and every handler below is
one library call plus the shaping of its result.

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
from research_core.verbs import register as register_common_verbs

import fact_check

PROG = "fact-check"

_DESCRIPTION = """\
fact-check -- checks claims against evidence, one verdict per claim.

Claims are checked independently, so one false claim does not condemn the rest.
Each verdict carries the sources it rests on.
"""

_EPILOG = """\
USING THE RESULT

  Every response is a single JSON document on stdout. Success is
  {"result": ...}; failure is {"error": {"code", "message", "remedy"}} with a
  non-zero exit. Diagnostics and progress go to stderr, never stdout, so you can
  parse one without filtering the other.

  A check result is a TALLY plus a POINTER. The tally -- how many claims were
  supported, refuted, unverifiable or opinion -- comes back inline, because it
  is small and it is the answer. The per-claim detail lives at `path`, in a run
  directory that outlives the call.

  `unverifiable` is a real verdict: the claim was checked and no adequate
  evidence was found either way. It is never reported as `refuted`.

NAVIGATING A LARGE RESULT

  Do not try to swallow a whole run. Every envelope carries a `next` block
  naming the exact commands to go further, and every one of them is
  deterministic -- they cost nothing, spend no tokens, and need no credentials:

    verdicts <id>  the per-claim results as structured data, filterable by
                   verdict. Audit one verdict without reading the others.
    sources <id>   the evidence as structured data -- walk the citations without
                   pulling the report into context.
    read <id>      a bounded slice of the narrative. Always carries a
                   completeness block: a partial view SAYS it is partial and how
                   much was left out, and an over-ceiling request is refused
                   rather than silently capped.

  Runs are shared with deep-research: `--from-run <id>` checks claims against
  evidence a research run already gathered, instead of gathering it again.

  Exit codes: 0 the verb did its job (including reporting that something is
  broken), 1 the operation failed, 2 the request was impossible or refused,
  3 a model-backed verb was asked for with no provider configured.

This version ships `manifest` only. The verbs above are specified in
contracts/cli.v1.md and arrive next.
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
    )
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

    config = verbs.add_parser(
        "config",
        help="the effective settings, and which tier each came from (deterministic)",
        description=(
            "Print the effective settings and, for each, where it came from: an "
            "explicit argument, the config file, an environment variable, or the "
            "built-in default -- in that order of precedence. Anything seen and "
            "deliberately not honoured is reported as such rather than vanishing. "
            "Credential surfaces report only the tier that satisfied them, never a "
            "value. Settings are shared with deep-research: one config file "
            "configures the pair. Deterministic: runs with no provider configured."
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

    register_common_verbs(verbs, prog=PROG, package="fact_check", include_verdicts=True)

    return parser


def _cmd_manifest(_args: argparse.Namespace) -> dict[str, Any]:
    return fact_check.manifest().to_dict()


def _cmd_config(args: argparse.Namespace) -> dict[str, Any]:
    return fact_check.config(runs_dir=args.runs_dir, backend=args.backend, depth=args.depth)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = args.handler(args)
    except SmartToolError as exc:
        emit_error(exc.code, exc.message, exc.remedy)
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
