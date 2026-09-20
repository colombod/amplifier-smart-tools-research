"""A malformed source entry is dropped and NAMED, never silently lost.

A partial result is a failure unless the capability documents partial
completion as a valid outcome and says which parts succeeded. Before this,
`parse_agent_reply` filtered non-object entries, entries with no url, and
duplicate urls with nothing recording that it had done so -- a caller reading
`sources <id>` would see fewer sources than the model actually named and have
no way to tell "the model gave less evidence" from "some of it was dropped".
"""

from __future__ import annotations

import json

from research_core.backends.agent import parse_agent_reply


def test_a_well_formed_reply_has_nothing_omitted():
    reply = json.dumps(
        {
            "findings": "x [1]",
            "sources": [{"url": "https://example.com/a", "title": "A"}],
        }
    )
    evidence = parse_agent_reply(reply)
    assert len(evidence.sources) == 1
    assert evidence.omitted == []


def test_a_non_object_source_entry_is_omitted_and_named():
    reply = json.dumps({"findings": "x", "sources": ["not-an-object"]})
    evidence = parse_agent_reply(reply)
    assert evidence.sources == []
    assert evidence.omitted == [{"index": 0, "reason": "not an object"}]


def test_a_source_with_no_url_is_omitted_and_named():
    reply = json.dumps({"findings": "x", "sources": [{"title": "No URL here"}]})
    evidence = parse_agent_reply(reply)
    assert evidence.sources == []
    assert evidence.omitted == [{"index": 0, "reason": "missing or empty url"}]


def test_a_duplicate_url_is_omitted_and_named_not_silently_merged():
    reply = json.dumps(
        {
            "findings": "x [1]",
            "sources": [
                {"url": "https://example.com/a", "title": "First mention"},
                {"url": "https://example.com/a", "title": "Second mention"},
            ],
        }
    )
    evidence = parse_agent_reply(reply)
    assert len(evidence.sources) == 1
    assert evidence.omitted == [
        {"index": 1, "reason": "duplicate url", "url": "https://example.com/a"}
    ]


def test_omissions_travel_through_to_dict_too():
    reply = json.dumps({"findings": "x", "sources": [123]})
    evidence = parse_agent_reply(reply)
    assert evidence.to_dict()["omitted"] == [{"index": 0, "reason": "not an object"}]
