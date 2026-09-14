"""The manifest declares; this tool detects. These tests hold that line.

The specification is explicit: "Every field in the manifest is inert. Nothing in
it is a command, and reading a manifest never runs anything. Detecting whether a
prerequisite is present is the tool's own job."

So the interesting failures here are not "is the detector right" but "can the
declaration and the detection drift apart" -- and the answer has to be no.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from research_core import load_manifest
from research_core.credentials import CREDENTIALS_PATH_ENV_VAR
from research_core.prerequisites import DETECTORS, check, check_requirements

TOOLS = {
    "deep_research": "deep-research",
    "fact_check": "fact-check",
}

REPO_ROOT = Path(__file__).resolve().parents[3]

ALL_CREDENTIAL_VARS = (
    "PERPLEXITY_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "AZURE_OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(CREDENTIALS_PATH_ENV_VAR, str(tmp_path / "credentials.toml"))
    for var in ALL_CREDENTIAL_VARS:
        monkeypatch.delenv(var, raising=False)
    return tmp_path


@pytest.mark.parametrize("package", sorted(TOOLS))
def test_every_declared_requirement_has_a_detector(package):
    # THE drift guard. A requirement nobody taught the tool to look for would be
    # reported `unknown` at runtime, which is honest but useless -- so it must
    # not be possible to add one to the manifest and forget the detector.
    pytest.importorskip(package)
    manifest = load_manifest(package)
    missing = [r.name for r in manifest.requires if r.name not in DETECTORS]
    assert not missing, (
        f"{manifest.name} declares {missing} in requires with no detector in "
        "research_core.prerequisites.DETECTORS"
    )


@pytest.mark.parametrize("package", sorted(TOOLS))
def test_an_undetectable_requirement_is_unknown_and_never_satisfied(package):
    # If the guard above ever fails, this is what the user sees: honest doubt,
    # not a false all-clear.
    pytest.importorskip(package)
    manifest = load_manifest(package)
    from dataclasses import replace

    from research_core.manifest import Requirement

    invented = Requirement(
        name="something-nobody-taught-us-about",
        purpose="Exists only in this test.",
        install="docs/CONFIGURATION.md",
        optional=True,
    )
    findings = check_requirements(replace(manifest, requires=[*manifest.requires, invented]))
    odd = next(f for f in findings if f.name == invented.name)
    assert odd.state == "unknown"
    assert "defect in the tool" in odd.detail


@pytest.mark.parametrize(("package", "distribution"), sorted(TOOLS.items()))
def test_every_install_reference_points_at_a_document_that_exists(package, distribution):
    # `install` is "a reference to documentation, a relative path or a URL,
    # never a command". The conformance kit checks it is not a command; nothing
    # checks the document is actually there, and a dangling pointer is a broken
    # promise made to someone who is already stuck.
    pytest.importorskip(package)
    manifest = load_manifest(package)
    root = REPO_ROOT / "tools" / distribution
    for requirement in manifest.requires:
        if requirement.install.startswith(("http://", "https://")):
            continue
        assert (root / requirement.install).exists(), (
            f"{manifest.name} points {requirement.name} at {requirement.install}, "
            "which does not exist"
        )


@pytest.mark.parametrize("package", sorted(TOOLS))
def test_the_perplexity_api_key_is_declared_as_an_environment_requirement(package):
    # The SDK is a package dependency and the specification says those belong to
    # the packaging system, not to requires. The KEY is an environment fact, and
    # so it belongs here.
    pytest.importorskip(package)
    names = {r.name for r in load_manifest(package).requires}
    assert "perplexity" in names


@pytest.mark.parametrize("package", sorted(TOOLS))
def test_no_requirement_is_mandatory(package):
    # Every deterministic verb runs with nothing configured. A non-optional
    # entry would contradict the tool's central claim about itself.
    pytest.importorskip(package)
    assert all(r.optional for r in load_manifest(package).requires)


@pytest.mark.parametrize("package", sorted(TOOLS))
def test_each_optional_requirement_names_its_cost_where_a_reader_will_see_it(package):
    # "optional: true means the tool runs without the dependency in a reduced
    # form, and that entry's purpose states what is lost."
    #
    # Whether a sentence STATES what is lost is not machine-checkable, and an
    # earlier version of this test pretended otherwise by grepping for the
    # phrase "without it" -- which tests phrasing, not meaning, and would pass
    # for a purpose that used the words and said nothing. What IS checkable:
    # the purpose is substantial, and `check` actually surfaces it to the person
    # who is missing the dependency rather than leaving it buried in a file
    # nobody opens.
    pytest.importorskip(package)
    manifest = load_manifest(package)
    for requirement in manifest.requires:
        assert len(requirement.purpose) > 80, requirement.name

    document = check(manifest)
    surfaced = " ".join(document["reduced_form"])
    for requirement in manifest.requires:
        if requirement.optional:
            assert requirement.name in surfaced, requirement.name


@pytest.mark.parametrize("package", sorted(TOOLS))
def test_check_reports_absent_when_nothing_is_configured(package, tmp_path):
    pytest.importorskip(package)
    document = check(load_manifest(package), runs_dir=str(tmp_path / "runs"))
    assert {r["state"] for r in document["requirements"]} == {"absent"}
    # Nothing required is missing, because nothing is required.
    assert document["ready"] is True
    assert document["deterministic_capabilities_available"] is True
    assert document["reduced_form"], "an unsatisfied optional must name its cost"


@pytest.mark.parametrize("package", sorted(TOOLS))
def test_check_sees_the_key_when_it_is_set(package, monkeypatch):
    pytest.importorskip(package)
    monkeypatch.setenv("PERPLEXITY_API_KEY", "sk-not-a-real-key")
    found = {r["name"]: r for r in check(load_manifest(package))["requirements"]}
    assert found["perplexity"]["state"] == "satisfied"
    assert found["perplexity"]["detail"] == "resolved from $PERPLEXITY_API_KEY"
    assert found["ai-provider"]["state"] == "absent"


@pytest.mark.parametrize("package", sorted(TOOLS))
def test_check_never_reports_a_credential_value(package, monkeypatch):
    secret = "sk-do-not-print-me-anywhere"
    pytest.importorskip(package)
    monkeypatch.setenv("PERPLEXITY_API_KEY", secret)
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    rendered = repr(check(load_manifest(package)))
    assert secret not in rendered
    assert secret[:8] not in rendered


def test_check_reports_an_unwritable_runs_directory(tmp_path):
    pytest.importorskip("deep_research")
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    try:
        document = check(load_manifest("deep_research"), runs_dir=str(blocked / "runs"))
        assert document["runs_dir"]["writable"] is False
        assert "would fail" in document["runs_dir"]["detail"]
    finally:
        blocked.chmod(0o700)
