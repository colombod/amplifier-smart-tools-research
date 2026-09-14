"""Shared core for the research smart tools.

Importing this package must never require a credential, reach a network, or touch
an agent engine. Deterministic verbs are built on it, and they run with nothing
configured.
"""

from research_core.config import (
    RESOLUTION_ORDER,
    SETTINGS,
    Resolved,
    Setting,
    Settings,
    config_path,
    effective_configuration,
    resolve_settings,
)
from research_core.credentials import (
    SURFACES,
    CredentialStatus,
    all_status,
    credentials_path,
    resolve_credential,
)
from research_core.envelope import (
    EXIT_FAILED,
    EXIT_NO_PROVIDER,
    EXIT_OK,
    EXIT_REFUSED,
    emit,
    emit_error,
)
from research_core.errors import (
    ConfigInvalidError,
    CredentialsInsecureError,
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
    "RESOLUTION_ORDER",
    "SETTINGS",
    "SURFACES",
    "ConfigInvalidError",
    "CredentialStatus",
    "CredentialsInsecureError",
    "Manifest",
    "ManifestError",
    "NoProviderError",
    "Requirement",
    "Resolved",
    "Setting",
    "Settings",
    "SmartToolError",
    "UsageError",
    "__version__",
    "all_status",
    "config_path",
    "credentials_path",
    "effective_configuration",
    "emit",
    "emit_error",
    "load_manifest",
    "resolve_credential",
    "resolve_settings",
]
