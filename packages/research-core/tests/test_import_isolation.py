"""The engine must not be imported until something actually needs it.

This assertion has existed since the first milestone and passed trivially,
because nothing depended on the engine. The optional public Core/Foundation
runtime must remain absent from imports of deterministic library surfaces.

Every check here runs in a FRESH SUBPROCESS rather than in the test process.
Monkeypatching is not enough: another test importing the engine would leave it in
`sys.modules` for the rest of the session, and the assertion would then pass or
fail depending on test ordering. A subprocess is the only way to ask the question
honestly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

PROBE = """
import json, os, sys
before = os.environ.get("AMPLIFIER_HOME")
{body}
print(json.dumps({{
    "engine_modules": sorted(m for m in sys.modules if m.startswith(("amplifier_agent", "amplifier_core", "amplifier_foundation", "amplifier_module_"))),
    "amplifier_home_before": before,
    "amplifier_home_after": os.environ.get("AMPLIFIER_HOME"),
}}))
"""


def probe(body: str) -> dict:
    """Run ``body`` in a clean interpreter and report what it imported.

    AMPLIFIER_HOME is scrubbed from the child's environment. It is often already
    set in a developer's shell -- by this very engine, in an earlier process --
    and inheriting it would make before and after identical whether or not the
    import rewrites anything. The test would then pass for the wrong reason and
    keep passing after the behaviour it guards changed.
    """
    environment = {k: v for k, v in os.environ.items() if k != "AMPLIFIER_HOME"}
    result = subprocess.run(
        [sys.executable, "-c", PROBE.format(body=body)],
        capture_output=True,
        text=True,
        cwd="/tmp",
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    "body",
    [
        "import research_core",
        "import deep_research",
        "import fact_check",
        "import deep_research.cli",
        "import fact_check.cli",
        "import research_core.engine",
        "import research_core.reasoning",
        "import research_core.backends.agent",
        "from research_core.reasoning import AgentReasoner; AgentReasoner()",
    ],
)
def test_importing_does_not_pull_in_the_engine(body):
    # research_core.engine included on purpose: the module that OWNS the engine
    # integration must still not import it until a turn is actually run.
    found = probe(body)
    assert found["engine_modules"] == [], f"{body!r} imported {found['engine_modules']}"


@pytest.mark.parametrize(
    "body",
    ["import research_core", "import deep_research", "import deep_research.cli"],
)
def test_importing_does_not_rewrite_amplifier_home(body):
    # The concrete hazard: importing amplifier_agent_lib sets AMPLIFIER_HOME
    # unconditionally, which would silently re-point unrelated code in the same
    # process at a different application's cache tree.
    found = probe(body)
    assert found["amplifier_home_after"] == found["amplifier_home_before"]


def test_the_probe_detects_the_current_runtime():
    pytest.importorskip("amplifier_core")
    found = probe("import amplifier_core")
    assert found["engine_modules"]
    assert found["amplifier_home_after"] == found["amplifier_home_before"]


def test_the_deterministic_surface_runs_with_the_engine_unimported():
    # The whole claim, end to end: a caller who only reads never pays for the
    # provider stack.
    found = probe(
        "import deep_research, tempfile;"
        "d = tempfile.mkdtemp();"
        "deep_research.list_runs(runs_dir=d);"
        "deep_research.classify(['https://arxiv.org/abs/1']);"
        "deep_research.manifest()"
    )
    assert found["engine_modules"] == []
    assert found["amplifier_home_after"] == found["amplifier_home_before"]
