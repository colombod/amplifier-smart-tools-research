"""The manifest accessor, and the refusals that make it worth having.

Every test here runs with nothing configured. That is the point: the manifest is
reachable by a caller who has no credentials and never intends to get any.
"""

from __future__ import annotations

import textwrap

import pytest
from research_core import ManifestError, load_manifest
from research_core.manifest import parse_manifest

GOOD = textwrap.dedent("""\
    ---
    smart_tool_format: 1
    name: sample-tool
    version: 0.1.0
    description: >
      Does a thing, and says when to reach for it.
    use_cases:
      - Do the thing
    platforms:
      - linux
    requires:
      - name: some-provider
        purpose: Backs the smart verb. Without it, only the deterministic verbs run.
        optional: true
        install: docs/CONFIGURATION.md
    ---

    # sample-tool

    Body text carries no compatibility guarantee.
    """)


def _without(field: str) -> str:
    return "\n".join(line for line in GOOD.splitlines() if not line.startswith(f"{field}:"))


def test_a_good_manifest_parses_every_field():
    manifest = parse_manifest(GOOD)
    assert manifest.smart_tool_format == 1
    assert manifest.name == "sample-tool"
    assert manifest.version == "0.1.0"
    assert manifest.use_cases == ["Do the thing"]
    assert manifest.platforms == ["linux"]
    assert manifest.body.startswith("# sample-tool")


def test_folded_description_collapses_to_one_line():
    # The manifest is read by tools that will put this in a list. A stray
    # newline from YAML folding is not content.
    assert "\n" not in parse_manifest(GOOD).description


def test_an_undefined_field_is_refused_and_named():
    # The specification says fields not listed are not part of the manifest.
    # Ignoring one would let an author believe something untrue about it.
    text = GOOD.replace("name: sample-tool", "name: sample-tool\nmaintainer: someone")
    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(text)
    assert "maintainer" in str(excinfo.value)


@pytest.mark.parametrize("field", ["smart_tool_format", "name", "version", "description"])
def test_a_missing_required_field_is_refused(field: str):
    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(_without(field))
    assert field in str(excinfo.value)


def test_a_field_present_but_empty_is_not_satisfied():
    text = GOOD.replace("use_cases:\n  - Do the thing", "use_cases: []")
    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(text)
    assert "use_cases" in str(excinfo.value)


def test_requires_is_the_only_omittable_field():
    text = GOOD.split("requires:")[0] + "---\n\n# sample-tool\n"
    assert parse_manifest(text).requires == []


def test_a_requires_entry_missing_install_is_refused():
    text = GOOD.replace("    install: docs/CONFIGURATION.md\n", "")
    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(text)
    assert "install" in str(excinfo.value)


def test_an_unclosed_frontmatter_fence_is_refused():
    text = GOOD.replace("---\n\n# sample-tool", "\n# sample-tool")
    with pytest.raises(ManifestError):
        parse_manifest(text)


def test_a_manifest_with_no_fence_at_all_is_refused():
    with pytest.raises(ManifestError) as excinfo:
        parse_manifest("# just a readme\n")
    assert "frontmatter" in str(excinfo.value)


def test_every_refusal_carries_a_remedy():
    with pytest.raises(ManifestError) as excinfo:
        parse_manifest("# not a manifest\n")
    assert excinfo.value.remedy


@pytest.mark.parametrize(
    ("package", "expected_name"),
    [("deep_research", "deep-research"), ("fact_check", "fact-check")],
)
def test_each_shipped_manifest_loads_from_its_installed_package(package: str, expected_name: str):
    pytest.importorskip(package)
    manifest = load_manifest(package)
    assert manifest.name == expected_name
    assert manifest.requires, "both tools declare their credential surfaces"
    assert all(r.optional for r in manifest.requires), (
        "no credential is mandatory: every deterministic verb runs without one"
    )


@pytest.mark.parametrize(
    ("package", "distribution"),
    [("deep_research", "deep-research"), ("fact_check", "fact-check")],
)
def test_manifest_version_matches_package_version(package: str, distribution: str):
    # The same property the conformance kit checks. A tool publishing two
    # different versions has two answers to a question that has one, and every
    # consumer eventually picks the wrong one.
    from importlib.metadata import version

    pytest.importorskip(package)
    assert load_manifest(package).version == version(distribution)
