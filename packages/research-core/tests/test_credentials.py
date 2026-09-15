"""Credential resolution: the environment wins, the file is fenced, values never leak."""

from __future__ import annotations

import os

import pytest
from research_core import CredentialsInsecureError, all_status, resolve_credential
from research_core.credentials import CREDENTIALS_PATH_ENV_VAR, SURFACES

ALL_VARS = [var for vars_ in SURFACES.values() for var in vars_]

SECRET = "sk-test-do-not-log-me"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(CREDENTIALS_PATH_ENV_VAR, str(tmp_path / "credentials.toml"))
    for var in ALL_VARS:
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def write_credentials(tmp_path, body: str, mode: int = 0o600):
    path = tmp_path / "credentials.toml"
    path.write_text(body, encoding="utf-8")
    path.chmod(mode)
    return path


def test_absent_is_reported_as_absent_not_as_an_error(isolated):
    value, status = resolve_credential("perplexity")
    assert value is None
    assert status.source == "absent"
    assert not status.present
    assert "PERPLEXITY_API_KEY" in status.detail


def test_the_environment_satisfies_a_surface(isolated, monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", SECRET)
    value, status = resolve_credential("perplexity")
    assert value == SECRET
    assert status.source == "environment"


def test_any_one_provider_variable_satisfies_the_model_surface(isolated, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    assert resolve_credential("model_provider")[1].source == "environment"


def test_the_environment_beats_the_file(isolated, monkeypatch):
    # The inverse of settings, and deliberately so: for secrets the environment
    # is the ecosystem norm and what every host already injects.
    write_credentials(isolated, f'perplexity = "{SECRET}-from-file"\n')
    monkeypatch.setenv("PERPLEXITY_API_KEY", f"{SECRET}-from-env")
    value, status = resolve_credential("perplexity")
    assert value == f"{SECRET}-from-env"
    assert status.source == "environment"


def test_the_file_satisfies_a_surface_when_the_environment_does_not(isolated):
    write_credentials(isolated, f'perplexity = "{SECRET}"\n')
    value, status = resolve_credential("perplexity")
    assert value == SECRET
    assert status.source == "credentials-file"


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o666])
def test_a_credentials_file_readable_by_anyone_else_is_refused(isolated, mode):
    write_credentials(isolated, f'perplexity = "{SECRET}"\n', mode=mode)
    with pytest.raises(CredentialsInsecureError) as excinfo:
        resolve_credential("perplexity")
    assert "chmod 600" in excinfo.value.remedy


def test_a_more_restrictive_mode_is_accepted(isolated):
    write_credentials(isolated, f'perplexity = "{SECRET}"\n', mode=0o400)
    assert resolve_credential("perplexity")[0] == SECRET


def test_no_status_anywhere_carries_the_value_or_its_shape(isolated, monkeypatch):
    # Not the value, not a prefix, not a length. A masked secret is still a
    # secret leak with extra steps: a length says which key it is, a prefix says
    # which account.
    monkeypatch.setenv("PERPLEXITY_API_KEY", SECRET)
    write_credentials(isolated, f'model_provider = "{SECRET}"\n')
    documents = {name: status.to_dict() for name, status in all_status().items()}

    # The VALUE must not appear anywhere at all, paths included -- a config file
    # path containing the secret would be its own disaster.
    assert SECRET not in repr(documents)

    # A PREFIX is a leak wherever it appears, including in provenance.
    assert SECRET[:6] not in repr(documents)

    # The LENGTH check needs one exclusion, and the reason is worth keeping.
    # `detail` carries provenance -- either an env var name or the PATH of the
    # credentials file -- and a filesystem path contains arbitrary digits. This
    # secret is 21 characters, and a run landing in `pytest-2108` failed on the
    # `21` inside pytest's directory counter. The test had been passing by luck,
    # which is worse than failing: a green run meant nothing, and the one time it
    # went red it was reporting on a temp directory rather than on a secret.
    #
    # So: scan every value for the length, but skip values that are paths, which
    # structurally cannot be derived from a secret's shape.
    def _is_path(value: object) -> bool:
        return isinstance(value, str) and os.sep in value

    shape_bearing = repr(
        {
            name: {k: v for k, v in document.items() if not _is_path(v)}
            for name, document in documents.items()
        }
    )
    assert str(len(SECRET)) not in shape_bearing


def test_every_surface_reports_a_status(isolated):
    assert set(all_status()) == set(SURFACES)
    assert all(status.detail for status in all_status().values())


def test_an_unknown_surface_is_a_programming_error(isolated):
    with pytest.raises(KeyError):
        resolve_credential("nonesuch")
