"""Credentials, and only ever the tier they came from.

The inverse of settings: the environment wins, because that is the ecosystem norm
and what every host already injects. A credentials file is supported because
asking for one is reasonable, but it is opt-in, deliberately separate from the
settings file so a config can be shared or committed, and refused outright if its
permissions are wider than 0600.

A credential VALUE never leaves this module. What a resolution reports is the tier
it came from -- never the value, never a prefix, never a length. A masked secret
is still a secret leak with extra steps: a length tells an attacker which key it
is, and a prefix tells them which account.
"""

from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

from research_core.errors import ConfigInvalidError, CredentialsInsecureError

CREDENTIALS_PATH_ENV_VAR = "RESEARCH_CREDENTIALS"
DEFAULT_CREDENTIALS_PATH = "~/.config/amplifier-research/credentials.toml"

SOURCE_ENVIRONMENT = "environment"
SOURCE_FILE = "credentials-file"
SOURCE_ABSENT = "absent"

#: Each credential surface, and the environment variables that satisfy it. The
#: model provider has several because any one of them is enough.
SURFACES: dict[str, tuple[str, ...]] = {
    "perplexity": ("PERPLEXITY_API_KEY",),
    "model_provider": (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "AZURE_OPENAI_API_KEY",
    ),
}


@dataclass(frozen=True)
class CredentialStatus:
    """Whether a surface is satisfied, and by which tier. Never by what value."""

    surface: str
    source: str
    detail: str

    @property
    def present(self) -> bool:
        return self.source != SOURCE_ABSENT

    def to_dict(self) -> dict[str, str | bool]:
        return {"source": self.source, "detail": self.detail, "present": self.present}


def credentials_path() -> Path:
    return Path(os.environ.get(CREDENTIALS_PATH_ENV_VAR, DEFAULT_CREDENTIALS_PATH)).expanduser()


def _read_credentials_file(path: Path) -> dict[str, str]:
    """Read the credentials file, refusing it outright if it is world- or group-readable."""
    if not path.exists():
        return {}

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise CredentialsInsecureError(
            f"The credentials file at {path} is mode {mode:04o}; anything beyond "
            "0600 lets another account on this machine read your keys.",
            f"Run: chmod 600 {path}",
        )

    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigInvalidError(
            f"The credentials file at {path} could not be read: {exc}",
            "Fix the file, or move it aside.",
        ) from exc

    values: dict[str, str] = {}
    for surface in SURFACES:
        value = raw.get(surface)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ConfigInvalidError(
                f"{surface} in {path} must be a non-empty string.",
                f"Set {surface} to the credential, or remove the key.",
            )
        values[surface] = value
    return values


def resolve_credential(surface: str) -> tuple[str | None, CredentialStatus]:
    """Resolve one credential surface.

    Returns the value for the caller that must actually use it, and a status that
    is safe to print. Callers that only need to know whether a surface is
    satisfied should use :func:`status` and never hold the value at all.
    """
    if surface not in SURFACES:
        raise KeyError(f"unknown credential surface: {surface!r}")

    for variable in SURFACES[surface]:
        value = os.environ.get(variable)
        if value and value.strip():
            return value.strip(), CredentialStatus(surface, SOURCE_ENVIRONMENT, f"${variable}")

    path = credentials_path()
    from_file = _read_credentials_file(path)
    if surface in from_file:
        return from_file[surface], CredentialStatus(surface, SOURCE_FILE, str(path))

    variables = " or ".join(SURFACES[surface])
    return None, CredentialStatus(
        surface,
        SOURCE_ABSENT,
        f"not set: no {variables}, and nothing for {surface} in {path}",
    )


def status(surface: str) -> CredentialStatus:
    """Whether a surface is satisfied, without the caller ever holding the value."""
    return resolve_credential(surface)[1]


def all_status() -> dict[str, CredentialStatus]:
    """Every surface's status. Safe to print in full."""
    return {surface: status(surface) for surface in SURFACES}
