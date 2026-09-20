"""The one place JSON reaches stdout -- for a SUCCESS. Failures go to stderr.

Stdout carries the requested result, whether text or structured data, and
nothing else: ``emit`` is the only function here that writes to it. Stderr
carries diagnostics -- progress, warnings, and the failure envelope itself --
so a caller piping stdout to a parser never has to filter a failure out of a
result stream that is only ever supposed to hold results.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Any

#: The verb did its job. Note that reporting a problem can itself be the job --
#: ``check`` exits 0 whether the host is healthy or broken, because the report is
#: the deliverable.
EXIT_OK = 0

#: The operation failed.
EXIT_FAILED = 1

#: The caller asked for something impossible: bad usage, unknown verb, refused
#: action, broken configuration.
EXIT_REFUSED = 2

#: A model-backed verb was asked for with no backend configured.
EXIT_NO_PROVIDER = 3


def _write(document: Any, *, stream: Any = None) -> None:
    """Write one JSON document, and die quietly if the reader has gone away.

    Output is meant to be piped. `... | head` closes the pipe early, and an
    unhandled BrokenPipeError turns that ordinary act into a traceback on
    stderr and a non-zero exit -- which would then look like a tool failure to
    anything reading exit codes.

    ``stream`` defaults to stdout, which carries the requested RESULT and
    nothing else. ``emit_error`` points this at stderr instead, so a caller
    piping stdout to a parser never has to filter a failure envelope out of
    it first.
    """
    target = stream if stream is not None else sys.stdout
    try:
        json.dump(document, target, sort_keys=True, default=str)
        target.write("\n")
        target.flush()
    except BrokenPipeError:
        with contextlib.suppress(BrokenPipeError):
            target.close()


def emit(result: Any) -> None:
    """Write the success envelope. The only thing this tool ever puts on stdout."""
    _write({"result": result})


def emit_error(
    code: str,
    message: str,
    remedy: str,
    affordances: list[Any] | None = None,
    *,
    artifact_path: str | Path | None = None,
) -> None:
    """Write the error envelope to STDERR.

    ``remedy`` is not optional. A caller should never have to infer what to do
    next from prose or from an empty result.

    ``affordances`` are the typed form of the same obligation: a refusal is a
    response, and a response with no way onward strands its caller. That was
    hypermedia's `204 No Content` mistake, and it was ours until this argument
    existed.

    ``artifact_path``, when given, is the run directory (or other artifact)
    that was created and partly populated before the failure -- so a caller
    reading the error still knows exactly where whatever survived is, rather
    than having to reconstruct the runs directory from the request it just
    made. Always resolved to an absolute path: a caller may run from any
    working directory, and a relative path is only meaningful in the one it
    happened to run from.

    Stderr, never stdout: a caller piping stdout to a parser must never see a
    failure envelope land where only results are expected.
    """
    error: dict[str, Any] = {"code": code, "message": message, "remedy": remedy}
    if affordances:
        error["affordances"] = [a.to_dict() if hasattr(a, "to_dict") else a for a in affordances]
    if artifact_path is not None:
        error["artifact"] = {"path": str(Path(artifact_path).expanduser().resolve())}
    _write({"error": error}, stream=sys.stderr)
