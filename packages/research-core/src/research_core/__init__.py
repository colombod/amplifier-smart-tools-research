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
    RunNotFoundError,
    RunsDirUnusableError,
    SmartToolError,
    UsageError,
)
from research_core.estimate import DEPTHS, estimate_run
from research_core.manifest import Manifest, Requirement, load_manifest
from research_core.runs import (
    RENDER_FORMATS,
    Run,
    citation_ids,
    dangling_citations,
    list_runs,
    load_run,
    read_part,
    render,
    sources_of,
    status_of,
    verdicts_of,
)
from research_core.urls import CATEGORIES, classify_url, classify_urls

__version__ = "0.1.0"

__all__ = [
    "CATEGORIES",
    "DEPTHS",
    "EXIT_FAILED",
    "EXIT_NO_PROVIDER",
    "EXIT_OK",
    "EXIT_REFUSED",
    "RENDER_FORMATS",
    "RESOLUTION_ORDER",
    "SETTINGS",
    "SURFACES",
    "__version__",
    "all_status",
    "citation_ids",
    "classify_url",
    "classify_urls",
    "config_path",
    "ConfigInvalidError",
    "credentials_path",
    "CredentialsInsecureError",
    "CredentialStatus",
    "dangling_citations",
    "effective_configuration",
    "emit",
    "emit_error",
    "estimate_run",
    "list_runs",
    "load_manifest",
    "load_run",
    "Manifest",
    "ManifestError",
    "NoProviderError",
    "read_part",
    "render",
    "Requirement",
    "resolve_credential",
    "resolve_settings",
    "Resolved",
    "Run",
    "RunNotFoundError",
    "RunsDirUnusableError",
    "Setting",
    "Settings",
    "SmartToolError",
    "sources_of",
    "status_of",
    "UsageError",
    "verdicts_of",
]
