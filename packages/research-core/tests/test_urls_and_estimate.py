"""URL classification and cost estimation: two verbs that never touch the disk."""

from __future__ import annotations

import pytest
from research_core import UsageError, classify_url, classify_urls, estimate_run


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://arxiv.org/abs/1805.06358", "academic"),
        ("https://doi.org/10.1145/3542929", "academic"),
        ("https://cs.stanford.edu/people/", "academic"),
        ("https://inria.hal.science/inria-00555588", "academic"),
        ("https://www.reuters.com/technology/", "news"),
        ("https://www.infoq.com/presentations/crdt/", "news"),
        ("https://www.w3.org/TR/webauthn-3/", "docs"),
        ("https://docs.python.org/3/library/json.html", "docs"),
        ("https://developer.mozilla.org/en-US/docs/Web", "docs"),
        ("https://github.com/microsoft/amplifier", "docs"),
        ("https://example.com/some/page", "other"),
        ("https://martin.kleppmann.com/2020/07/06/crdt-hard-parts.html", "other"),
    ],
)
def test_urls_sort_into_the_expected_category(url, expected):
    assert classify_url(url) == expected


@pytest.mark.parametrize("url", ["", "   ", "not a url", "mailto:someone@example.com"])
def test_a_url_that_cannot_be_parsed_is_other_rather_than_an_error(url):
    # This runs over whatever a backend returned. One malformed entry should not
    # fail a whole reference list.
    assert classify_url(url) == "other"


def test_classifying_several_preserves_order_and_keeps_duplicates():
    urls = ["https://arxiv.org/a", "https://example.com/b", "https://arxiv.org/a"]
    assert [entry["url"] for entry in classify_urls(urls)] == urls
    assert [entry["category"] for entry in classify_urls(urls)] == [
        "academic",
        "other",
        "academic",
    ]


def test_classification_needs_no_network_or_credential(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")  # would break any request
    assert classify_url("https://arxiv.org/abs/1805.06358") == "academic"


@pytest.mark.parametrize("depth", ["low", "medium", "high"])
def test_every_depth_estimates_and_admits_it_is_an_estimate(depth):
    document = estimate_run(depth=depth)
    assert document["is_estimate"] is True
    assert document["caveat"]
    assert document["basis"]


def test_deeper_costs_more_and_takes_longer():
    low, high = estimate_run(depth="low"), estimate_run(depth="high")
    assert float(high["estimated_cost_usd"]) > float(low["estimated_cost_usd"])
    assert high["estimated_seconds"] > low["estimated_seconds"]
    assert high["estimated_sources"] > low["estimated_sources"]


def test_the_cost_is_a_decimal_string_not_a_float():
    # Money as a float is how a rounding error becomes a billing dispute.
    assert isinstance(estimate_run()["estimated_cost_usd"], str)


def test_more_claims_cost_more_but_not_linearly():
    # Claims are verified independently, so cost grows -- but they share the
    # gathered evidence, so three claims do not cost three times one.
    one = float(estimate_run(claims=1)["estimated_cost_usd"])
    three = float(estimate_run(claims=3)["estimated_cost_usd"])
    assert one < three < one * 3


def test_an_unknown_depth_is_refused_and_names_the_ones_that_exist():
    with pytest.raises(UsageError) as excinfo:
        estimate_run(depth="exhaustive")
    assert "low, medium, high" in excinfo.value.remedy
