"""The two replies that actually cost us $0.66, kept as fixtures.

For two days "no JSON document was found in the reply" was a mystery, because the
replies were discarded at the instant they became the only evidence of why. Once
`raw/` kept rejected replies, three `--depth high` runs produced two failures and
the cause took one command to see.

It was never truncation and never prose-around-JSON. Both replies were well-formed
JSON documents carrying exactly the right keys -- with markdown written INTO the
string values using real newlines instead of `\\n` escapes. A table in one, a
bullet list in the other. `json.loads` rejects raw control characters in strings
by default; that is the whole of what `strict=True` means.

These files are the verbatim replies. They are the regression test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from research_core.parsing import NoStructureFound, extract_json

FIXTURES = Path(__file__).parent / "fixtures" / "rejected-replies"

#: Real replies, and what the model was doing when it broke the parser.
REJECTIONS = {
    "markdown-table-in-a-string.txt": "a markdown table, rows separated by real newlines",
    "bullet-list-in-a-string.txt": "a markdown bullet list, fenced, real newlines",
}


@pytest.mark.parametrize("name,what_broke_it", sorted(REJECTIONS.items()))
def test_a_reply_that_really_failed_now_parses(name, what_broke_it):
    """Run dr-03052120 and dr-94627cb8, verbatim. Both cost real money to lose."""
    document = extract_json((FIXTURES / name).read_text(encoding="utf-8"))

    assert sorted(document) == ["brief", "confidence", "report"], what_broke_it
    assert document["confidence"] in {"low", "medium", "high"}
    assert document["brief"].strip(), "a brief that parses but is empty is not a win"


@pytest.mark.parametrize("name", sorted(REJECTIONS))
def test_the_strict_pass_is_what_rejected_them(name):
    """Proof the fix addresses THIS cause and not some neighbouring one.

    If a fixture ever starts passing strictly, the reply has changed and this
    file is no longer testing what it claims to test.
    """
    text = (FIXTURES / name).read_text(encoding="utf-8")

    with pytest.raises(json.JSONDecodeError) as failure:
        json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
    assert "control character" in failure.value.msg.lower(), (
        "these fixtures exist to cover unescaped control characters in strings"
    )


def test_the_second_pass_forgives_newlines_and_nothing_else():
    """The guarantee this module exists for survives.

    parsing.py's docstring says a half-parsed result that looks whole is the
    failure mode worth spending code to avoid. `strict=False` forgives exactly
    one thing -- a raw control character inside a string -- and still demands a
    well-formed document everywhere else. Truncation, prose, and broken syntax
    must all still be refused.
    """
    for broken in (
        '{"brief": "cut off mid-stri',  # truncated
        "I'd be happy to help! Here is my analysis.",  # prose, no document
        '{"brief": "ok",, "confidence": "low"}',  # malformed
        '{"brief": "ok" "confidence": "low"}',  # missing comma
    ):
        with pytest.raises(NoStructureFound):
            extract_json(broken)


def test_a_newline_inside_a_string_loses_no_data():
    """Forgiving the character is not the same as dropping it.

    If the second pass silently ate newlines, a markdown table in a brief would
    arrive as one unreadable line and we would have traded a loud failure for a
    quiet corruption -- a strictly worse deal.
    """
    document = extract_json('{"report": "row one\nrow two"}')
    assert document["report"] == "row one\nrow two"
