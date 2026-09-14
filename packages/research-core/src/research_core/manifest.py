"""The SMART_TOOL.md manifest, as structured data.

Read from the copy built into the tool's own package, so a caller reaches the
manifest through the library rather than by locating a file on disk.

The field set is CLOSED. The specification says fields not listed are not part of
the manifest, so an unknown field is an error rather than something to ignore --
a manifest that quietly carries a field nobody reads is a manifest whose author
believes something untrue about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import yaml

from research_core.errors import ManifestError

MANIFEST_FILENAME = "SMART_TOOL.md"

#: Every field the specification defines. Anything else is a defect.
ALLOWED_FIELDS = (
    "smart_tool_format",
    "name",
    "version",
    "description",
    "use_cases",
    "platforms",
    "requires",
)

#: Every field that must be present AND carry content. A field present but empty
#: is not satisfied. ``requires`` is the sole omittable field: a tool with no
#: prerequisites leaves it out.
REQUIRED_FIELDS = (
    "smart_tool_format",
    "name",
    "version",
    "description",
    "use_cases",
    "platforms",
)

_FENCE = "---"


@dataclass(frozen=True)
class Requirement:
    """One entry in ``requires``."""

    name: str
    purpose: str
    install: str
    optional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "install": self.install,
            "optional": self.optional,
        }


@dataclass(frozen=True)
class Manifest:
    """A parsed, validated manifest."""

    smart_tool_format: int
    name: str
    version: str
    description: str
    use_cases: list[str]
    platforms: list[str]
    requires: list[Requirement] = field(default_factory=list)
    body: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "smart_tool_format": self.smart_tool_format,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "use_cases": list(self.use_cases),
            "platforms": list(self.platforms),
            "requires": [r.to_dict() for r in self.requires],
        }


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter, body). Raises when the fence is missing or unclosed."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        raise ManifestError(
            f"{MANIFEST_FILENAME} does not open with a '{_FENCE}' frontmatter fence.",
            "The manifest is YAML frontmatter followed by a Markdown body.",
        )
    for index in range(1, len(lines)):
        if lines[index].strip() == _FENCE:
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :]).strip()
    raise ManifestError(
        f"{MANIFEST_FILENAME} opens a frontmatter fence that is never closed.",
        f"Close the frontmatter with a line containing only '{_FENCE}'.",
    )


def _require_non_empty(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ManifestError(
            f"{MANIFEST_FILENAME} is missing the required field '{key}'.",
            f"Add '{key}' to the manifest frontmatter.",
        )
    value = data[key]
    if value is None or (hasattr(value, "__len__") and len(value) == 0):
        raise ManifestError(
            f"{MANIFEST_FILENAME} declares '{key}' but it carries no content.",
            "A field that is present but empty is not satisfied.",
        )
    return value


def _parse_requires(raw: Any) -> list[Requirement]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ManifestError(
            f"{MANIFEST_FILENAME} field 'requires' must be a list, got {type(raw).__name__}.",
            "Each entry carries name, purpose and install, and may carry optional.",
        )
    entries: list[Requirement] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ManifestError(
                f"requires[{index}] must be a mapping, got {type(item).__name__}.",
                "Each entry carries name, purpose and install, and may carry optional.",
            )
        missing = [k for k in ("name", "purpose", "install") if not item.get(k)]
        if missing:
            raise ManifestError(
                f"requires[{index}] is missing {', '.join(missing)}.",
                "Each entry carries name, purpose and install.",
            )
        entries.append(
            Requirement(
                name=str(item["name"]).strip(),
                purpose=" ".join(str(item["purpose"]).split()),
                install=str(item["install"]).strip(),
                optional=bool(item.get("optional", False)),
            )
        )
    return entries


def parse_manifest(text: str) -> Manifest:
    """Parse and validate manifest text. Every failure names its remedy."""
    frontmatter, body = _split_frontmatter(text)
    try:
        data = yaml.safe_load(frontmatter)
    except yaml.YAMLError as exc:
        raise ManifestError(
            f"{MANIFEST_FILENAME} frontmatter is not valid YAML: {exc}",
            "Fix the YAML syntax in the manifest frontmatter.",
        ) from exc

    if not isinstance(data, dict):
        raise ManifestError(
            f"{MANIFEST_FILENAME} frontmatter must be a mapping, got {type(data).__name__}.",
            "The frontmatter is a YAML mapping of the manifest fields.",
        )

    unknown = sorted(set(data) - set(ALLOWED_FIELDS))
    if unknown:
        raise ManifestError(
            f"{MANIFEST_FILENAME} carries fields the specification does not define: "
            f"{', '.join(unknown)}.",
            "Fields not listed in the specification are not part of the manifest; remove them.",
        )

    for key in REQUIRED_FIELDS:
        _require_non_empty(data, key)

    if not isinstance(data["smart_tool_format"], int):
        raise ManifestError(
            "smart_tool_format must be an integer.",
            "It is the manifest schema version, so a reader can tell whether it "
            "understands the file at all.",
        )
    for key in ("use_cases", "platforms"):
        if not isinstance(data[key], list):
            raise ManifestError(
                f"{key} must be a list, got {type(data[key]).__name__}.",
                f"Write {key} as a YAML list.",
            )

    return Manifest(
        smart_tool_format=int(data["smart_tool_format"]),
        name=str(data["name"]).strip(),
        version=str(data["version"]).strip(),
        description=" ".join(str(data["description"]).split()),
        use_cases=[str(u).strip() for u in data["use_cases"]],
        platforms=[str(p).strip() for p in data["platforms"]],
        requires=_parse_requires(data.get("requires")),
        body=body,
    )


def load_manifest(package: str) -> Manifest:
    """Load the manifest built into ``package``."""
    try:
        text = resources.files(package).joinpath(MANIFEST_FILENAME).read_text("utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise ManifestError(
            f"{MANIFEST_FILENAME} is not present in the installed package {package!r}: {exc}",
            "The manifest ships inside the package; this build is incomplete.",
        ) from exc
    return parse_manifest(text)
