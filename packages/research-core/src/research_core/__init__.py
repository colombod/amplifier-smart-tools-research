"""Shared core for the research smart tools.

Importing this package must never require a credential, reach a network, or touch
an agent engine. Deterministic verbs are built on it, and they run with nothing
configured.
"""

from research_core.envelope import (
    EXIT_FAILED,
    EXIT_NO_PROVIDER,
    EXIT_OK,
    EXIT_REFUSED,
    emit,
    emit_error,
)
from research_core.errors import (
    ManifestError,
    NoProviderError,
    SmartToolError,
    UsageError,
)
from research_core.manifest import Manifest, Requirement, load_manifest

__version__ = "0.1.0"

__all__ = [
    "EXIT_FAILED",
    "EXIT_NO_PROVIDER",
    "EXIT_OK",
    "EXIT_REFUSED",
    "Manifest",
    "ManifestError",
    "NoProviderError",
    "Requirement",
    "SmartToolError",
    "UsageError",
    "__version__",
    "emit",
    "emit_error",
    "load_manifest",
]
