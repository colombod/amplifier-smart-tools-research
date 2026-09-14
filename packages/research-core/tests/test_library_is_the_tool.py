"""The rule the specification calls absolute, held by a test.

    "Everything the tool can do is reachable from the library... The rule is
    one-directional and absolute: no capability exists only in a wrapper. If the
    CLI can do it, the library can do it."

This failed quietly for three milestones. The verbs existed, but only as argparse
handlers taking a Namespace, so the tool's own library exposed two functions
where its CLI exposed ten. Nothing was missing -- it was only ASSEMBLED inside
the wrapper, which is exactly what the rule forbids and exactly what no test was
looking for.

Also here: dependency honesty. An undeclared dependency is invisible to the CI
job that installs what is declared, so the first honest test of it is someone
else's install.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

TOOLS = {"deep_research": "deep-research", "fact_check": "fact-check"}


def _verbs_of(package: str) -> set[str]:
    """Every verb the CLI actually exposes, read from the real parser."""
    module = pytest.importorskip(f"{package}.cli")
    parser = module.build_parser()
    for action in parser._actions:
        if getattr(action, "choices", None) and hasattr(action.choices, "keys"):
            return set(action.choices)
    raise AssertionError(f"{package} has no verb table")


@pytest.mark.parametrize("package", sorted(TOOLS))
def test_every_cli_verb_is_reachable_from_the_library(package):
    tool = pytest.importorskip(package)
    missing = _verbs_of(package) - set(tool.CAPABILITIES)
    assert not missing, (
        f"{package} exposes {sorted(missing)} on its CLI with no library "
        "equivalent. A capability that exists only in the wrapper is a "
        "capability no other caller can reach."
    )


@pytest.mark.parametrize("package", sorted(TOOLS))
def test_the_library_advertises_nothing_the_cli_cannot_do(package):
    # The other direction is not a rule, but a library capability with no verb is
    # usually an oversight rather than a decision, and worth seeing.
    tool = pytest.importorskip(package)
    assert set(tool.CAPABILITIES) <= _verbs_of(package) | {"research", "check-claims"}


@pytest.mark.parametrize("package", sorted(TOOLS))
def test_every_capability_is_callable_without_argparse(package):
    tool = pytest.importorskip(package)
    for name, function in tool.CAPABILITIES.items():
        assert callable(function), name
        annotations = getattr(function, "__annotations__", {})
        assert not any("Namespace" in str(value) for value in annotations.values()), (
            f"{package}.{name} takes CLI machinery; it is not a library function"
        )


@pytest.mark.parametrize("package", sorted(TOOLS))
def test_the_deterministic_library_surface_works_with_nothing_configured(
    package, tmp_path, monkeypatch
):
    monkeypatch.setenv("RESEARCH_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("RESEARCH_CREDENTIALS", str(tmp_path / "credentials.toml"))
    for var in ("PERPLEXITY_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    tool = pytest.importorskip(package)
    runs = str(tmp_path / "runs")
    assert tool.check(runs_dir=runs)["ready"] is True
    assert tool.config(runs_dir=runs)["settings"]["runs_dir"]["value"] == runs
    assert tool.list_runs(runs_dir=runs)["count"] == 0
    assert tool.classify(["https://arxiv.org/abs/1"])["by_category"] == {"academic": 1}
    assert tool.manifest().name == TOOLS[package]


# -- dependency honesty ------------------------------------------------------


def _pyproject(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("distribution", sorted(TOOLS.values()))
def test_each_tool_declares_the_shared_core_including_its_extras(distribution):
    project = _pyproject(REPO_ROOT / "tools" / distribution / "pyproject.toml")
    dependencies = project["project"]["dependencies"]
    core = [d for d in dependencies if d.startswith("research-core")]
    assert core, f"{distribution} does not declare research-core"
    assert "[agent,perplexity]" in core[0], (
        f"{distribution} must declare the extras it actually uses; an undeclared "
        "dependency is invisible to the job that installs what is declared"
    )
    assert "#subdirectory=" in core[0], (
        "a path dependency cannot resolve when one distribution root is "
        "installed on its own from git"
    )


def test_every_third_party_import_in_the_core_is_declared():
    # The concrete failure this guards: amplifier-agent was installed by hand
    # into a local venv, imported by research_core.engine, and declared nowhere.
    # CI passed because nothing exercised it yet.
    core = _pyproject(REPO_ROOT / "packages" / "research-core" / "pyproject.toml")
    declared = " ".join(
        core["project"]["dependencies"]
        + [d for group in core["project"]["optional-dependencies"].values() for d in group]
    )
    source = " ".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "packages" / "research-core" / "src").rglob("*.py")
    )
    for module, distribution in (
        ("import yaml", "pyyaml"),
        ("from perplexity import", "perplexityai"),
        ("import amplifier_agent_lib", "amplifier-agent"),
        ("from amplifier_agent_lib", "amplifier-agent"),
        ("from amplifier_agent_cli", "amplifier-agent"),
    ):
        if module in source:
            assert distribution in declared, (
                f"research_core imports {module!r} but nothing declares {distribution}"
            )


def test_the_agent_engine_is_an_extra_so_its_weight_is_a_visible_decision():
    core = _pyproject(REPO_ROOT / "packages" / "research-core" / "pyproject.toml")
    extras = core["project"]["optional-dependencies"]
    assert "agent" in extras
    assert not any("amplifier-agent" in d for d in core["project"]["dependencies"]), (
        "the engine is heavy and git-only; keeping it in an extra is what makes "
        "taking it a decision someone made rather than one that happened"
    )
