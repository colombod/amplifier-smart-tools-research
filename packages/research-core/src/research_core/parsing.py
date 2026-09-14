"""Getting structure out of a model's reply.

A model asked for JSON returns JSON surrounded by whatever it felt like saying.
This finds the document and refuses when there is not one, rather than guessing:
a half-parsed result that looks whole is the failure mode worth spending code to
avoid.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCED = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class NoStructureFound(ValueError):
    """The reply carried no parseable document where one was required."""


def extract_json(text: str) -> Any:
    """Find the JSON document in a reply.

    Tries, in order: a fenced block, the whole reply, then the widest brace- or
    bracket-delimited span. Raises rather than returning a default, because a
    caller that wanted structure and got a default cannot tell the difference
    between "the model said nothing" and "the model said nothing useful".
    """
    if not text or not text.strip():
        raise NoStructureFound("the reply was empty")

    for candidate in _candidates(text):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise NoStructureFound("no JSON document was found in the reply")


def _candidates(text: str) -> list[str]:
    found = [block.strip() for block in _FENCED.findall(text)]
    found.append(text.strip())
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            found.append(text[start : end + 1])
    return [candidate for candidate in found if candidate]


def strip_fences(text: str) -> str:
    """Return prose with any fenced blocks removed."""
    return _FENCED.sub("", text).strip()
