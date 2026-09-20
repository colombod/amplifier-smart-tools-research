"""Detecting whether the things the manifest requires are actually here.

The specification is explicit about the division of labour: *"Every field in the
manifest is inert. Nothing in it is a command, and reading a manifest never runs
anything. Detecting whether a prerequisite is present is the tool's own job."*

So the manifest DECLARES and this module DETECTS -- and the detection is driven
by the declaration rather than by a second hard-coded list. The manifest's
`requires` entries are enumerated, and each is looked up in the detector table.
A requirement with no detector is reported ``unknown``, never ``satisfied``:
silently claiming a prerequisite is fine because nobody taught the tool to look
for it is precisely the drift this arrangement exists to prevent.

What belongs in `requires` is what must exist in the ENVIRONMENT. Package
dependencies do not: the specification says those belong to the packaging system,
which already resolves them. Our Perplexity SDK ships as a resolved dependency
and is therefore absent from `requires`; the API KEY is an environment fact, and
is there.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from research_core.credentials import SURFACES, status
from research_core.manifest import Manifest

SATISFIED = "satisfied"
ABSENT = "absent"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Finding:
    """What was found for one declared requirement."""

    name: str
    state: str
    optional: bool
    detail: str
    purpose: str
    install: str
    lost_without_it: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "optional": self.optional,
            "detail": self.detail,
            "purpose": self.purpose,
            "install": self.install,
            "lost_without_it": self.lost_without_it,
        }


def _credential_detector(surface: str) -> Callable[[], tuple[str, str]]:
    """Detect a credential surface without ever holding its value."""

    def detect() -> tuple[str, str]:
        found = status(surface)
        if found.present:
            return SATISFIED, f"resolved from {found.detail}"
        return ABSENT, found.detail

    return detect


#: Maps a manifest requirement NAME to how this tool looks for it. Keys must
#: match the `requires[].name` values in SMART_TOOL.md; a test asserts that they
#: do, in both manifests, so the declaration and the detection cannot drift
#: apart unnoticed.
def _ai_provider_detector() -> tuple[str, str]:
    """A provider is satisfied only if a turn could actually run.

    Two corrections live here, both found by running the thing rather than
    reasoning about it.

    The first: this reported `satisfied` on a credential alone while every turn
    died at mount time for want of a client library -- the exact false
    all-clear the unknown-never-satisfied rule below exists to prevent, one
    level down.

    The second is subtler and the reverse. It reported `absent` whenever our own
    environment and credentials file were empty -- but the engine we embed is
    the HOST's own library, and it resolves the host's credentials on its own.
    With every *_API_KEY scrubbed, the engine still reported anthropic usable,
    because it reads Amplifier's configuration directly. So the detector said
    "not ready" about a path that works. The authority on whether a turn can run
    is the thing that runs it, and that is the engine -- not us.
    """
    found = status("model_provider")

    from research_core.engine import (
        available_providers,
        client_library_for,
        credentialled_providers,
    )

    usable = available_providers()
    if usable:
        if found.present:
            return SATISFIED, f"{found.detail}, client library present for {usable[0]}"
        # The engine found a credential we cannot see, which is not a bug: the
        # engine is the host's own library and resolves the host's configuration.
        return (
            SATISFIED,
            f"resolved by the embedded engine ({usable[0]}) from the host's own "
            "configuration, not from this tool's environment or credentials file",
        )

    with_credentials = credentialled_providers()
    if with_credentials:
        missing = sorted({client_library_for(p) or p for p in with_credentials})
        return (
            ABSENT,
            f"credentials resolve for {', '.join(with_credentials)}, but no "
            f"client library is installed ({', '.join(missing)}); the engine "
            "ships none of its own",
        )
    return ABSENT, found.detail


DETECTORS: dict[str, Callable[[], tuple[str, str]]] = {
    "perplexity": _credential_detector("perplexity"),
    "ai-provider": _ai_provider_detector,
}


def provider_availability() -> list[dict[str, Any]]:
    """Per-PROVIDER breakdown of the ``ai-provider`` requirement.

    The manifest declares one requirement -- ``ai-provider`` -- satisfied by
    any one of five API-key variables. That is true for whether a run can
    start at all, and false for whether any SPECIFIC one of the five will
    actually work: only ``anthropic`` ships its client library in this
    package's default `agent` extra, so a host with only ``GOOGLE_API_KEY``
    set sees the requirement reported ``satisfied`` while that specific
    provider still cannot run a turn until ``google-genai`` is installed.

    Reporting the requirement as a whole hides exactly that gap, which is
    what a caller actually needs answered before it tries the one credential
    it has. This says, for each candidate provider: usable, credentialled but
    missing its client library (and what to install), or no credential at
    all.
    """
    from research_core.engine import (
        PROVIDER_PREFERENCE,
        available_providers,
        client_library_for,
        credentialled_providers,
    )

    usable = set(available_providers())
    credentialled = set(credentialled_providers())

    breakdown: list[dict[str, Any]] = []
    for name in PROVIDER_PREFERENCE:
        library = client_library_for(name)
        if name in usable:
            state, detail, install = (
                SATISFIED,
                "usable: credential and client library both resolve",
                None,
            )
        elif name in credentialled:
            state = ABSENT
            detail = (
                f"credential resolves, but its client library ({library}) is not installed"
                if library
                else "credential resolves, but this tool has no known client library for it"
            )
            install = f"pip install {library}" if library else None
        else:
            state, detail, install = ABSENT, "no credential configured for this provider", None
        breakdown.append(
            {
                "provider": name,
                "state": state,
                "detail": detail,
                "client_library": library,
                "install": install,
            }
        )
    return breakdown


def check_requirements(manifest: Manifest) -> list[Finding]:
    """Look for everything this tool's own manifest says it needs."""
    findings: list[Finding] = []
    for requirement in manifest.requires:
        detector = DETECTORS.get(requirement.name)
        if detector is None:
            state, detail = (
                UNKNOWN,
                "this tool declares this requirement but has no way to look for "
                "it; that is a defect in the tool, not in your environment",
            )
        else:
            state, detail = detector()
        findings.append(
            Finding(
                name=requirement.name,
                state=state,
                optional=requirement.optional,
                detail=detail,
                purpose=requirement.purpose,
                install=requirement.install,
                lost_without_it=requirement.purpose if state != SATISFIED else None,
            )
        )
    return findings


def check(manifest: Manifest, *, runs_dir: str | None = None) -> dict[str, Any]:
    """The `check` verb's payload.

    Reporting a problem IS this verb's success: it exits 0 whether the host is
    ready or not, because the report is the deliverable. A caller that wants a
    non-zero exit for "not ready" can branch on `ready`.
    """
    findings = check_requirements(manifest)
    missing_required = [f for f in findings if f.state != SATISFIED and not f.optional]
    unsatisfied_optional = [f for f in findings if f.state != SATISFIED and f.optional]

    document: dict[str, Any] = {
        "tool": manifest.name,
        "version": manifest.version,
        "ready": not missing_required,
        "requirements": [f.to_dict() for f in findings],
        "deterministic_capabilities_available": True,
        "note": (
            "Every deterministic capability runs with none of these configured. "
            "What an unsatisfied optional requirement costs you is named in its "
            "purpose."
        ),
    }
    if unsatisfied_optional:
        document["reduced_form"] = [f"{f.name}: {f.purpose}" for f in unsatisfied_optional]

    if runs_dir is not None:
        from research_core.writer import default_runs_dir_is_writable

        writable = default_runs_dir_is_writable(runs_dir)
        document["runs_dir"] = {
            "path": runs_dir,
            "writable": writable,
            "detail": (
                "runs can be written here"
                if writable
                else "runs cannot be written here; a model-backed verb would fail"
            ),
        }

    # The second place this tool causes writes, and the one nobody chose. It is
    # reported unconditionally and beside runs_dir on purpose: a host that
    # confines writes needs both paths in front of it at once, before it spends
    # anything, rather than discovering the second at the first model-backed
    # stage of a run it has already paid for.
    from research_core.engine import engine_home_status

    document["engine_home"] = engine_home_status()

    known_surfaces = sorted(SURFACES)
    document["credential_surfaces"] = known_surfaces

    # `ai-provider` is one requirement covering five possible credentials, and
    # "satisfied" means only that ONE of them works -- which specific one, and
    # what the other four would need, is exactly what a caller with a
    # not-yet-working key needs answered next.
    if any(r.name == "ai-provider" for r in manifest.requires):
        document["provider_availability"] = provider_availability()

    return document
