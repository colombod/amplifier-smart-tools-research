"""Settings resolution, and the refusals that make four tiers safe to have.

Every test runs with a private config path and a scrubbed environment, so none of
them can be influenced by the machine they run on.
"""

from __future__ import annotations

import pytest
from research_core import (
    SETTINGS,
    ConfigInvalidError,
    effective_configuration,
    resolve_settings,
)
from research_core.config import CONFIG_PATH_ENV_VAR

ENV_VARS = [s.env_var for s in SETTINGS]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """A private config path, and not one ambient setting left standing."""
    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, str(tmp_path / "config.toml"))
    monkeypatch.setenv("RESEARCH_CREDENTIALS", str(tmp_path / "credentials.toml"))
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path


def write_config(tmp_path, body: str) -> None:
    (tmp_path / "config.toml").write_text(body, encoding="utf-8")


def test_nothing_configured_falls_all_the_way_to_defaults(isolated):
    settings = resolve_settings()
    assert settings.source_of("depth") == "default"
    assert settings["depth"] == "medium"
    assert not settings.config_path_exists


def test_the_default_runs_dir_honours_xdg_state_home(isolated):
    assert str(isolated / "state") in resolve_settings()["runs_dir"]


def test_the_environment_beats_the_default(isolated, monkeypatch):
    monkeypatch.setenv("RESEARCH_DEPTH", "high")
    settings = resolve_settings()
    assert settings["depth"] == "high"
    assert settings.source_of("depth") == "environment"


def test_the_config_file_beats_the_environment(isolated, monkeypatch):
    # The reasoning, which is the whole point of this ordering: a deployment
    # that wrote a config file meant it; an environment variable can arrive by
    # accident from a parent process.
    write_config(isolated, 'depth = "low"\n')
    monkeypatch.setenv("RESEARCH_DEPTH", "high")
    settings = resolve_settings()
    assert settings["depth"] == "low"
    assert settings.source_of("depth") == "config-file"


def test_an_argument_beats_everything(isolated, monkeypatch):
    write_config(isolated, 'depth = "low"\n')
    monkeypatch.setenv("RESEARCH_DEPTH", "high")
    settings = resolve_settings(depth="medium")
    assert settings["depth"] == "medium"
    assert settings.source_of("depth") == "argument"


def test_what_was_overridden_is_reported_rather_than_vanishing(isolated, monkeypatch):
    write_config(isolated, 'depth = "low"\n')
    monkeypatch.setenv("RESEARCH_DEPTH", "high")
    settings = resolve_settings(depth="medium")
    assert any("RESEARCH_DEPTH" in note for note in settings.ignored)
    assert any("config.toml" in note for note in settings.ignored)


def test_an_unset_argument_is_not_an_argument(isolated):
    # An unset CLI flag arrives as None. Treating that as an explicit choice
    # would make every flag override the config file merely by existing.
    assert resolve_settings(depth=None).source_of("depth") == "default"


def test_a_wrong_type_in_the_config_file_is_fatal(isolated):
    # Not a fall-through to the default. Silently substituting one is how runs
    # end up written somewhere nobody expects.
    write_config(isolated, "max_read_lines = true\n")
    with pytest.raises(ConfigInvalidError) as excinfo:
        resolve_settings()
    assert "max_read_lines" in str(excinfo.value)
    assert excinfo.value.remedy


def test_a_string_where_an_integer_belongs_is_fatal(isolated):
    write_config(isolated, 'max_read_lines = "lots"\n')
    with pytest.raises(ConfigInvalidError):
        resolve_settings()


def test_a_value_outside_the_allowed_choices_is_fatal(isolated):
    write_config(isolated, 'depth = "exhaustive"\n')
    with pytest.raises(ConfigInvalidError) as excinfo:
        resolve_settings()
    assert "low, medium, high" in str(excinfo.value)


def test_an_unreadable_config_file_is_fatal(isolated):
    write_config(isolated, "this is not = = toml\n")
    with pytest.raises(ConfigInvalidError) as excinfo:
        resolve_settings()
    assert "could not be read" in str(excinfo.value)


def test_a_setting_that_does_not_exist_is_refused_and_named(isolated):
    # A key nobody reads is a key whose author believes something untrue.
    write_config(isolated, 'colour = "blue"\n')
    with pytest.raises(ConfigInvalidError) as excinfo:
        resolve_settings()
    assert "colour" in str(excinfo.value)


def test_an_empty_environment_variable_is_absent_not_empty(isolated, monkeypatch):
    monkeypatch.setenv("RESEARCH_DEPTH", "")
    assert resolve_settings().source_of("depth") == "default"


def test_a_bad_integer_in_the_environment_is_fatal(isolated, monkeypatch):
    monkeypatch.setenv("RESEARCH_MAX_READ_LINES", "lots")
    with pytest.raises(ConfigInvalidError):
        resolve_settings()


def test_every_setting_resolves_and_reports_a_known_tier(isolated):
    settings = resolve_settings()
    assert set(settings.resolved) == {s.name for s in SETTINGS}
    for resolved in settings.resolved.values():
        assert resolved.source in {
            "argument",
            "config-file",
            "environment",
            "default",
        }
        assert resolved.detail


def test_the_report_is_printable_and_names_the_order(isolated):
    document = effective_configuration()
    assert document["resolution_order"] == [
        "argument",
        "config-file",
        "environment",
        "default",
    ]
    assert set(document["credentials"]) == {"perplexity", "model_provider"}
