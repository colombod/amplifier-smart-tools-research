"""The one place JSON reaches stdout.

One JSON document on stdout, always. Diagnostics and progress go to stderr and
never to stdout, so a caller can parse the former without filtering the latter.
"""

from __future__ import annotations

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


def emit(result: Any) -> None:
    """Write the success envelope."""
    json.dump({"result": result}, sys.stdout, sort_keys=True, default=str)
    sys.stdout.write("\n")
    sys.stdout.flush()


def emit_error(code: str, message: str, remedy: str) -> None:
    """Write the error envelope.

    ``remedy`` is not optional. A caller should never have to infer what to do
    next from prose or from an empty result.
    """
    json.dump(
        {"error": {"code": code, "message": message, "remedy": remedy}},
        sys.stdout,
        sort_keys=True,
        default=str,
    )
    sys.stdout.write("\n")
    sys.stdout.flush()
