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
DETECTORS: dict[str, Callable[[], tuple[str, str]]] = {
    "perplexity": _credential_detector("perplexity"),
    "ai-provider": _credential_detector("model_provider"),
}


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

    known_surfaces = sorted(SURFACES)
    document["credential_surfaces"] = known_surfaces
    return document
