"""The one place JSON reaches stdout.

One JSON document on stdout, always. Diagnostics and progress go to stderr and
never to stdout, so a caller can parse the former without filtering the latter.
"""

from __future__ import annotations

import contextlib
import json
import sys
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


def _write(document: Any) -> None:
    """Write one JSON document, and die quietly if the reader has gone away.

    Output is meant to be piped. `... | head` closes the pipe early, and an
    unhandled BrokenPipeError turns that ordinary act into a traceback on
    stderr and a non-zero exit -- which would then look like a tool failure to
    anything reading exit codes.
    """
    try:
        json.dump(document, sys.stdout, sort_keys=True, default=str)
        sys.stdout.write("\n")
        sys.stdout.flush()
    except BrokenPipeError:
        with contextlib.suppress(BrokenPipeError):
            sys.stdout.close()


def emit(result: Any) -> None:
    """Write the success envelope."""
    _write({"result": result})


def emit_error(
    code: str,
    message: str,
    remedy: str,
    affordances: list[Any] | None = None,
) -> None:
    """Write the error envelope.

    ``remedy`` is not optional. A caller should never have to infer what to do
    next from prose or from an empty result.

    ``affordances`` are the typed form of the same obligation: a refusal is a
    response, and a response with no way onward strands its caller. That was
    hypermedia's `204 No Content` mistake, and it was ours until this argument
    existed.
    """
    error: dict[str, Any] = {"code": code, "message": message, "remedy": remedy}
    if affordances:
        error["affordances"] = [a.to_dict() if hasattr(a, "to_dict") else a for a in affordances]
    _write({"error": error})
