"""Failures are loud and they name the remedy.

Every deliberate failure carries a stable ``code`` a caller can branch on and a
``remedy`` a caller can act on, so nothing has to be inferred from prose or from an
empty result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class SmartToolError(RuntimeError):
    """Base for every deliberate failure."""

    code = "failed"
    exit_code = 1

    def __init__(
        self,
        message: str,
        remedy: str,
        affordances: list[Any] | None = None,
        *,
        artifact_path: str | Path | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.remedy = remedy
        # A refusal is a response, and a response owes the caller a next move.
        # Hypermedia learned this the expensive way with `204 No Content`: a
        # response carrying no representation carries no way onward, and strands
        # the client at exactly the moment it most needs direction. Ours did the
        # same -- an error envelope and nothing else.
        #
        # A library caller reads these off the exception; a CLI caller reads them
        # off the envelope. Same list, both paths.
        self.affordances: list[Any] = list(affordances or [])
        # Where a partial artifact -- most often a run directory -- was left on
        # disk when this failure happened. A run that was created and then
        # failed has evidence a caller should not have to reconstruct the runs
        # directory to find; a library caller reads this off the exception, a
        # CLI caller off the error envelope's ``artifact.path``. Always
        # resolved to absolute: whoever reads it may not share this process's
        # working directory.
        self.artifact_path: str | None = (
            str(Path(artifact_path).expanduser().resolve()) if artifact_path is not None else None
        )

    def with_artifact(self, path: str | Path) -> SmartToolError:
        """Attach a partial artifact's location after construction.

        Some raise sites only learn where a run directory is -- a
        ``RunWriter`` already created for this attempt -- after the error
        that ends the attempt was already built (or after catching one raised
        lower down). Mutating in place beats forcing every such site to
        thread the path through the constructor: ``raise exc.with_artifact(
        writer.path) from exc``. Resolved to absolute, same as the
        constructor argument, and returns ``self`` so it composes with
        ``raise``.
        """
        self.artifact_path = str(Path(path).expanduser().resolve())
        return self


class UsageError(SmartToolError):
    """The caller asked for something that does not exist or cannot be parsed."""

    code = "usage"
    exit_code = 2


class ConfigInvalidError(SmartToolError):
    """A config file is present but unreadable, or a setting is the wrong type.

    Never downgraded to a default. A caller with a config file present is entitled
    to have it honoured or to be told plainly that it is broken.
    """

    code = "config_invalid"
    exit_code = 2


class CredentialsInsecureError(SmartToolError):
    """A credentials file exists but its permissions are wider than 0600."""

    code = "credentials_insecure"
    exit_code = 2


class RunNotFoundError(SmartToolError):
    """No such run in the runs directory this invocation is pointed at.

    Named rather than empty. Several callers may be pointed at different runs
    directories, so "not found" and "you are looking in the wrong place" are the
    same message and it has to say which directory it looked in.
    """

    code = "run_not_found"
    exit_code = 1


class RunsDirUnusableError(SmartToolError):
    """The runs directory is not a directory, or cannot be written."""

    code = "runs_dir_unusable"
    exit_code = 1


class NoEvidence(SmartToolError):
    """A run that was supposed to gather evidence gathered none."""

    code = "no_evidence"
    exit_code = 1


class RunFailedError(SmartToolError):
    """A run exists but failed, and there is nothing complete to navigate to.

    A failed run keeps whatever it gathered before the failure -- that is the
    point of writing artifacts as a run proceeds rather than only at the end --
    but a partial brief or report rendered as though it were the finished
    document IS the "partial result silently returned as complete" failure
    mode this project refuses on principle. `status` is where a caller learns
    what happened and what survives; navigation verbs that assemble a
    finished-shaped document (`render`) refuse instead of guessing which
    partial assembly is honest.
    """

    code = "run_failed"
    exit_code = 1


class NoProviderError(SmartToolError):
    """A model-backed capability was asked for with no backend configured.

    Raised by preflight, before any prompt is built. It never degrades to a lesser
    deterministic answer.
    """

    code = "no_provider"
    exit_code = 3


class ManifestError(SmartToolError):
    """The tool's own manifest is malformed or missing -- a defect in the tool."""

    code = "manifest"
    exit_code = 1
