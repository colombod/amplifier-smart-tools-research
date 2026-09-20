"""D5: nothing ever checked whether a cited source URL actually resolves.

A run's own confidence claim can rest on a citation that is a 404, returned
verbatim by a backend and never opened by anything downstream. These tests
drive the real check (`research_core.url_reachability.verify_source_urls`) and
the real opt-in wiring (`research_core.api.sources(verify=...)`), with
`urllib.request.urlopen` replaced by a script -- no real network reached, and
none of these tests can pass by accident of what happens to be online today.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from research_core import api
from research_core.url_reachability import verify_source_urls

FIXTURES = Path(__file__).parent / "fixtures" / "runs"


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


def _scripted_urlopen(script: dict[str, Any]):
    """Map a URL to either a status code or an exception to raise.

    ``script[url]`` is either an int (a real HTTP response, success or not) or
    an exception instance to raise (a genuine network failure).
    """
    calls: list[tuple[str, str]] = []

    def fake(request: urllib.request.Request, timeout: float | None = None):
        calls.append((request.get_method(), request.full_url))
        outcome = script[request.full_url]
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, dict):
            # method-specific outcome, e.g. HEAD refused, GET fine
            result = outcome[request.get_method()]
            if isinstance(result, Exception):
                raise result
            return _FakeResponse(result)
        return _FakeResponse(outcome)

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


def test_a_url_that_resolves_is_reachable(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _scripted_urlopen({"https://ok.example/": 200}))
    result = verify_source_urls([{"id": "s1", "url": "https://ok.example/"}])
    assert result[0]["reachable"] is True
    assert result[0]["status_code"] == 200
    assert result[0]["error"] is None


def test_a_404_is_a_definite_answer_not_a_network_failure(monkeypatch):
    """The exact D5 shape: rfc-editor's pdfrfc URL returns a real 404."""
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        _scripted_urlopen(
            {
                "https://dead.example/": urllib.error.HTTPError(
                    "https://dead.example/", 404, "Not Found", None, None
                )
            }
        ),
    )
    result = verify_source_urls([{"id": "s1", "url": "https://dead.example/"}])
    assert result[0]["reachable"] is False
    assert result[0]["status_code"] == 404
    assert result[0]["error"] is None, "a real HTTP response is not a network failure"


def test_head_refused_falls_back_to_get(monkeypatch):
    """Some hosts 405 on HEAD but answer GET fine -- not proof of death."""
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        _scripted_urlopen(
            {
                "https://head-refuses.example/": {
                    "HEAD": urllib.error.HTTPError(
                        "https://head-refuses.example/", 405, "Method Not Allowed", None, None
                    ),
                    "GET": 200,
                }
            }
        ),
    )
    result = verify_source_urls([{"id": "s1", "url": "https://head-refuses.example/"}])
    assert result[0]["reachable"] is True
    assert result[0]["status_code"] == 200


def test_a_network_failure_is_reported_not_raised(monkeypatch):
    """Could-not-check and does-not-exist must never be the same finding."""
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        _scripted_urlopen({"https://unreachable.example/": urllib.error.URLError("no route")}),
    )
    result = verify_source_urls([{"id": "s1", "url": "https://unreachable.example/"}])
    assert result[0]["reachable"] is None
    assert result[0]["status_code"] is None
    assert result[0]["error"]


def test_a_source_with_no_url_is_reported_not_crashed_on():
    result = verify_source_urls([{"id": "s1", "url": None}])
    assert result[0]["reachable"] is None
    assert "no url" in result[0]["error"]


def test_verify_is_off_by_default_and_touches_no_network(monkeypatch):
    """`sources` without `--verify` must never import urlopen at all."""

    def _boom(*a, **k):
        raise AssertionError("sources() reached the network without --verify")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    document = api.sources("dr-1a2b3c4d", runs_dir=str(FIXTURES))
    assert "verified" not in document
    assert "reachable" not in document["sources"][0]


def test_verify_true_enriches_every_source_and_summarises(monkeypatch, tmp_path):
    """The real seam: api.sources(verify=True) against a real fixture run."""
    fixture = FIXTURES / "dr-1a2b3c4d"
    run = tmp_path / "runs" / "dr-1a2b3c4d"
    run.parent.mkdir(parents=True)
    import shutil

    shutil.copytree(fixture, run)
    sources_doc = json.loads((run / "sources.json").read_text())
    urls = [s["url"] for s in sources_doc["sources"]]
    assert len(urls) >= 2, "fixture must carry at least two sources for this test to mean anything"

    script: dict[str, Any] = {urls[0]: 200}
    for extra in urls[1:]:
        script[extra] = urllib.error.HTTPError(extra, 404, "Not Found", None, None)
    monkeypatch.setattr(urllib.request, "urlopen", _scripted_urlopen(script))

    document = api.sources("dr-1a2b3c4d", runs_dir=str(tmp_path / "runs"), verify=True)

    assert document["verified"] is True
    assert document["reachable_count"] == 1
    assert document["unreachable_count"] == len(urls) - 1
    assert document["unknown_count"] == 0
    first = next(s for s in document["sources"] if s["url"] == urls[0])
    assert first["reachable"] is True
    assert first["status_code"] == 200
    dead = next(s for s in document["sources"] if s["url"] == urls[1])
    assert dead["reachable"] is False
    assert dead["status_code"] == 404


def test_the_scripted_fake_itself_fails_loudly_on_an_unscripted_url(monkeypatch):
    """Guards the test helper: an unscripted URL must fail loudly in the test,
    not silently report success -- or these tests could pass for the wrong
    reason."""
    monkeypatch.setattr(urllib.request, "urlopen", _scripted_urlopen({}))
    with pytest.raises(KeyError):
        verify_source_urls([{"id": "s1", "url": "https://not-scripted.example/"}])
