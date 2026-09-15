"""What a caller may do next, said in the response itself.

A smart tool's output is routinely larger than its response and larger than the
caller's context window. The response is what a caller can ACT ON; the output is
what the tool PRODUCED, and they were never the same size. So a response owes the
caller two things: a proxy it can use immediately, and a way to reach the rest.

We shipped a weak version of the second: a ``next`` block of shell command
strings. Useful to an agent driving the CLI, meaningless to one calling the
library, and silent about what anything costs. This is the typed form.

The one idea borrowed from hypermedia -- and it is one idea, not a format. Siren
is the only surveyed format that separates plain links from parameterised
ACTIONS, and our follow-ups were always actions. What we deliberately did not
take: registered relation vocabularies and RDF. The coupling those remove is one
an agent re-reading a fresh skill on every call does not have, bought at a
payload and tooling cost practitioners were right about (see the survey in
``dr-56f6e5ec``).

The lesson that shaped this module most: ``204 No Content`` broke hypermedia's
interaction loop, because a response with no representation carries no way
onward. **Our refusals had exactly that defect** -- an error envelope and nothing
else, leaving the caller stranded at the moment it most needs direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

#: What comes back when an affordance is taken. Deliberately coarse: a caller
#: needs to know whether to expect prose, a structure, or bytes it should not
#: put in a context window.
Returns = Literal["text", "json", "bytes"]


@dataclass(frozen=True)
class Affordance:
    """One thing the caller may do next, and everything needed to decide.

    Both invocation forms are carried because the library is the tool. A response
    that only makes sense in a shell is a CLI-shaped leak, and a library caller
    reading ``command`` would have to shell out to follow its own tool's advice.
    """

    #: Stable identifier a caller can branch on. Free-form by design -- see the
    #: module docstring on why a registered vocabulary is not worth its cost here.
    name: str

    #: What it does, in one sentence, for an agent deciding whether to take it.
    does: str

    #: The CLI form, ready to run.
    command: str

    #: The library form, e.g. ``deep_research.read("dr-1", lines=40)``.
    call: str

    #: What comes back.
    returns: Returns = "json"

    #: What taking it costs. ``"0.00"`` is a claim we can make for every
    #: deterministic verb and do not make lightly.
    cost_usd: str = "0.00"

    #: Whether it needs a credential. A caller on an unconfigured host can then
    #: filter to what it can actually do rather than discovering by failure.
    needs_credentials: bool = False

    #: Rough size of what comes back, when known. None means unknown, never zero:
    #: the whole point is that a caller can refuse to fetch something enormous,
    #: and a fabricated size is worse than an honest absence.
    bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "name": self.name,
            "does": self.does,
            "command": self.command,
            "call": self.call,
            "returns": self.returns,
            "cost_usd": self.cost_usd,
            "needs_credentials": self.needs_credentials,
        }
        if self.bytes is not None:
            document["bytes"] = self.bytes
        return document


@dataclass
class Rung:
    """One step on a fidelity ladder: the same content, at a different size.

    For us the ladder is brief -> report -> raw sources. For a tool emitting an
    image it is thumbnail -> web -> original; for audio, transcript -> clip ->
    master. The shape is the same, which is the test of whether this generalises
    beyond the tool that invented it.
    """

    rung: str
    does: str
    bytes: int | None = None
    cost_usd: str = "0.00"
    ready: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "rung": self.rung,
            "does": self.does,
            "bytes": self.bytes,
            "cost_usd": self.cost_usd,
            "ready": self.ready,
        }


@dataclass
class Completeness:
    """Whether this representation is the whole thing, and how much is beyond.

    A property of the response, not one verb's courtesy. A caller that cannot
    tell a slice from the whole will present a slice as the whole.
    """

    complete: bool
    returned: int | None = None
    total: int | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "returned": self.returned,
            "total": self.total,
            "note": self.note,
        }


@dataclass
class Navigation:
    """The affordances and ladder attached to one response."""

    affordances: list[Affordance] = field(default_factory=list)
    ladder: list[Rung] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {"affordances": [a.to_dict() for a in self.affordances]}
        if self.ladder:
            document["ladder"] = [r.to_dict() for r in self.ladder]
        return document


def free(name: str, does: str, command: str, call: str, **kwargs: Any) -> Affordance:
    """A deterministic affordance: costs nothing, needs no credential.

    Most of what a caller should do next is free, and saying so is what stops a
    cautious agent refusing to explore a result it has already paid for.
    """
    return Affordance(
        name=name,
        does=does,
        command=command,
        call=call,
        cost_usd="0.00",
        needs_credentials=False,
        **kwargs,
    )
