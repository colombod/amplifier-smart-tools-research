"""Where the engine writes, who decides it, and what happens when it cannot.

A real run died here. A host that confined writes to its workspace ran a research
run, paid for the gather, and then lost the synthesis stage to a bare
``PermissionError`` naming ``~/.amplifier-agent`` -- a directory nobody had
chosen and no setting mentioned. The evidence survived; the run did not.

Two claims are under test, and the second is the one that makes the first
matter:

1. Everything the engine writes is under ONE configured path, refused up front
   when it is unusable rather than discovered mid-run.
2. ``AMPLIFIER_HOME`` -- the variable anyone reaching for a lever exports first
   -- is NOT that path, because the engine overwrites it at import. Our refusal
   says so in as many words, so a test has to hold the engine to it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from research_core import SETTINGS, ConfigInvalidError, engine, resolve_settings
from research_core.config import CONFIG_PATH_ENV_VAR
from research_core.engine import (
    ENGINE_HOME_ENV,
    OVERWRITTEN_HOME_ENV,
    WORK_SUBDIR,
    EngineUnavailable,
    _turn_workspace,
    bind_engine_home,
    default_engine_home,
    engine_home,
    engine_home_status,
    ensure_engine_home_usable,
)

ENV_VARS = [s.env_var for s in SETTINGS]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """A private config path and no ambient setting left standing."""
    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, str(tmp_path / "config.toml"))
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv(ENGINE_HOME_ENV, raising=False)
    monkeypatch.delenv(OVERWRITTEN_HOME_ENV, raising=False)
    return tmp_path


def write_config(tmp_path, body: str) -> None:
    (tmp_path / "config.toml").write_text(body, encoding="utf-8")


def test_the_default_is_what_the_engine_would_have_done_anyway(monkeypatch):
    # Deliberately not a path of ours. The tree holds a module cache measured in
    # hundreds of megabytes; a default that moved it would orphan what is on
    # disk and re-clone it, for every caller who never had a problem.
    monkeypatch.setenv("HOME", "/home/probe")
    assert str(default_engine_home()) == "/home/probe/.amplifier-agent"
    assert resolve_settings().source_of("engine_home") == "default"


def test_the_engines_own_variable_still_works_when_we_have_no_opinion(monkeypatch):
    # A caller who already knew the engine's lever keeps it: our setting adds a
    # name for the location, it does not take one away.
    monkeypatch.setenv(ENGINE_HOME_ENV, "/somewhere/chosen")
    assert str(default_engine_home()) == "/somewhere/chosen"
    assert engine_home() == "/somewhere/chosen"


def test_the_setting_moves_it_and_says_which_tier_said_so(isolated, monkeypatch):
    monkeypatch.setenv("RESEARCH_ENGINE_HOME", str(isolated / "from-environment"))
    assert engine_home_status()["source"] == "environment"

    write_config(isolated, f'engine_home = "{isolated / "from-file"}"\n')
    status = engine_home_status()
    assert status["source"] == "config-file"
    assert status["path"] == str(isolated / "from-file")


def test_binding_points_the_engines_own_variable_at_the_configured_home(isolated, monkeypatch):
    # The binding, not the setting, is what the engine reads. It has to reach the
    # environment before the engine is imported, and this is the proof it does.
    monkeypatch.setenv("RESEARCH_ENGINE_HOME", str(isolated / "bound"))
    assert bind_engine_home() == isolated / "bound"
    assert os.environ[ENGINE_HOME_ENV] == str(isolated / "bound")


def test_an_unwritable_home_is_refused_before_anything_is_spent(isolated, monkeypatch):
    blocked = isolated / "read-only"
    blocked.mkdir()
    blocked.chmod(0o500)
    monkeypatch.setenv("RESEARCH_ENGINE_HOME", str(blocked / "engine"))

    with pytest.raises(EngineUnavailable) as excinfo:
        ensure_engine_home_usable()

    # The refusal has to carry both halves: where it tried, and which knob moves
    # it. The failure it replaces carried only the first.
    assert str(blocked / "engine") in excinfo.value.message
    assert "engine_home" in excinfo.value.remedy
    assert ENGINE_HOME_ENV in excinfo.value.remedy
    blocked.chmod(0o700)


def test_the_variable_that_does_nothing_is_named_as_doing_nothing(isolated, monkeypatch):
    # Exporting AMPLIFIER_HOME is the natural first guess and has no effect at
    # all. Saying so costs one line here and saves an afternoon there.
    monkeypatch.setattr(engine, "_INHERITED_OVERWRITTEN_HOME", str(isolated / "guessed"))
    monkeypatch.setenv("RESEARCH_ENGINE_HOME", str(isolated / "real"))

    status = engine_home_status()
    assert OVERWRITTEN_HOME_ENV in status["ignored"]
    assert ENGINE_HOME_ENV in status["ignored"]

    blocked = isolated / "read-only"
    blocked.mkdir()
    blocked.chmod(0o500)
    monkeypatch.setenv("RESEARCH_ENGINE_HOME", str(blocked / "engine"))
    with pytest.raises(EngineUnavailable) as excinfo:
        ensure_engine_home_usable()
    assert OVERWRITTEN_HOME_ENV in excinfo.value.remedy
    blocked.chmod(0o700)


def test_the_engines_own_rewrite_is_not_reported_back_as_the_callers_mistake(isolated, monkeypatch):
    """The advice fires for a caller who set it, never for the engine that did.

    The first version read the live environment, so any process that had run a
    turn -- which sets AMPLIFIER_HOME as a side effect of importing the engine --
    told its caller they had set a variable they had never touched. Advice that
    fires when nothing is wrong is how advice stops being read.
    """
    monkeypatch.setenv(OVERWRITTEN_HOME_ENV, str(isolated / "set-by-the-engine"))
    monkeypatch.setattr(engine, "_INHERITED_OVERWRITTEN_HOME", None)
    monkeypatch.setenv("RESEARCH_ENGINE_HOME", str(isolated / "home"))
    assert "ignored" not in engine_home_status()


def test_a_broken_config_file_is_fatal_here_too(isolated, monkeypatch):
    write_config(isolated, "engine_home = 3\n")
    with pytest.raises(ConfigInvalidError):
        engine_home_status()


def test_the_turn_workspace_lives_under_the_home_and_does_not_outlive_the_turn(
    isolated, monkeypatch
):
    # It used to be tempfile.mkdtemp() with no directory: a SECOND location
    # outside the caller's control, and one that nothing ever deleted.
    monkeypatch.setenv("RESEARCH_ENGINE_HOME", str(isolated / "home"))
    with _turn_workspace() as cwd:
        assert cwd.startswith(str(isolated / "home" / WORK_SUBDIR))
        assert os.path.isdir(cwd)
    assert not os.path.exists(cwd)


def test_the_turn_workspace_is_removed_when_the_turn_fails(isolated, monkeypatch):
    # The failing path is the one that matters: a run that dies is exactly when
    # nobody is left to tidy up.
    monkeypatch.setenv("RESEARCH_ENGINE_HOME", str(isolated / "home"))
    with pytest.raises(RuntimeError), _turn_workspace() as cwd:
        raise RuntimeError("the turn failed")
    assert not os.path.exists(cwd)


def test_check_reports_where_the_engine_will_write(isolated, monkeypatch):
    from research_core import api

    monkeypatch.setenv("RESEARCH_ENGINE_HOME", str(isolated / "home"))
    reported = api.check("deep_research")["engine_home"]
    assert reported["path"] == str(isolated / "home")
    assert reported["writable"] is True


PROBE = """
import json, os, sys
import amplifier_agent_lib
from amplifier_agent_lib.persistence import amplifier_agent_home, cache_root
print(json.dumps({
    "agent_home": str(amplifier_agent_home()),
    "cache": str(cache_root()),
    "amplifier_home_after": os.environ.get("AMPLIFIER_HOME"),
}))
"""


def test_the_two_claims_our_message_makes_about_the_engine_are_true(tmp_path):
    """Hold the engine to what the refusal above tells people.

    The message asserts two things about someone else's code: that
    ``AMPLIFIER_AGENT_HOME`` moves the tree, and that ``AMPLIFIER_HOME`` does
    not. Both are true of the version we embed, neither is ours to guarantee,
    and a message that quietly stopped being true would send the next person to
    check the wrong thing -- which is the failure this whole file exists to
    prevent, one level up.
    """
    pytest.importorskip("amplifier_agent_lib")
    environment = dict(os.environ)
    environment[ENGINE_HOME_ENV] = str(tmp_path / "agent")
    environment[OVERWRITTEN_HOME_ENV] = str(tmp_path / "ignored")

    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        capture_output=True,
        text=True,
        cwd="/tmp",
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout.strip().splitlines()[-1])

    assert found["agent_home"] == str(tmp_path / "agent"), (
        f"${ENGINE_HOME_ENV} no longer moves the engine's tree; the setting and "
        "the refusal message both need revisiting"
    )
    assert found["cache"].startswith(str(tmp_path / "agent"))
    assert found["amplifier_home_after"] != str(tmp_path / "ignored"), (
        f"the engine no longer overwrites ${OVERWRITTEN_HOME_ENV}; the refusal "
        "message saying it has no effect has become false"
    )
