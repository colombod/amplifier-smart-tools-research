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
    """The reply carried no parseable document where one was required.

    ``detail`` -- when set -- is the specific `json.JSONDecodeError` message
    (with its line/column/byte offset) from the candidate that got furthest
    before failing. D6: a repair loop that only ever says "no JSON document
    was found" cannot distinguish "you said nothing" from "you said almost
    the right thing, but this one character broke it" -- and a model fed the
    first message when the second was true fixes the wrong thing, repeatedly,
    at cost. ``detail`` is None only when no candidate looked enough like
    JSON to produce a parse error at all (e.g. the reply was empty or pure
    prose).
    """

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail


def extract_json(text: str) -> Any:
    """Find the JSON document in a reply.

    Tries, in order: a fenced block, the whole reply, then the widest brace- or
    bracket-delimited span. Raises rather than returning a default, because a
    caller that wanted structure and got a default cannot tell the difference
    between "the model said nothing" and "the model said nothing useful".

    Each candidate is tried twice: once strictly, then once permitting literal
    control characters inside string values.

    WHY THE SECOND PASS EXISTS, diagnosed from two captured rejections rather
    than guessed. A `--depth high` run failed synthesis with "no JSON document
    was found" and cost $0.66 in discarded attempts. The replies were, in fact,
    well-formed JSON documents carrying exactly the right keys -- except that the
    model had written markdown into the string values (a table in one, a bullet
    list in the other) using REAL newlines rather than `\n` escapes. Python's
    json rejects raw control characters in strings by default; that is all
    `strict=True` means. Both parse perfectly with `strict=False`.

    This is the failure a long reply invites, because length is when a model
    reaches for markdown structure -- which is why our cheap fixtures never saw
    it and two 800-second runs did.

    The second pass does NOT weaken the guarantee this module exists for. A
    half-parsed result that looks whole is still impossible: the document must
    still be well-formed JSON in every other respect. The only thing forgiven is
    an unescaped newline inside a string, which changes no structure and loses no
    data -- json preserves the character either way.
    """
    if not text or not text.strip():
        raise NoStructureFound("the reply was empty")

    # The candidate that parsed FURTHEST before failing (highest `.pos`) is
    # the one most likely to be "real JSON with one specific defect" rather
    # than unrelated prose -- and its own JSONDecodeError already names the
    # exact byte offset and the token it expected, which is precisely what a
    # repair attempt needs to fix the one thing that is actually wrong rather
    # than guess. `pos == 0` is excluded: that means the parser rejected the
    # very first character, which is what plain prose does too (it never
    # started looking like JSON at all) and surfacing that as "the specific
    # defect" would be no more useful than the generic message -- worse, it
    # would look like a real diagnosis and mislead a repair attempt into
    # fixing something that was never wrong.
    best_error: json.JSONDecodeError | None = None
    for candidate in _candidates(text):
        for strict in (True, False):
            try:
                return json.loads(candidate, strict=strict)
            except json.JSONDecodeError as exc:
                if exc.pos > 0 and (best_error is None or exc.pos > best_error.pos):
                    best_error = exc
                continue
    detail = str(best_error) if best_error is not None else None
    raise NoStructureFound("no JSON document was found in the reply", detail=detail)


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
