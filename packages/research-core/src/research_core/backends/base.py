"""The seam a backend arrives through.

A backend ACQUIRES EVIDENCE. It does not do the reasoning: scoping the question
and synthesising what came back are this tool's own stages, because that is where
the domain judgment lives and the entire point of packaging it here is that it
does not sit in a vendor's service.

The protocol is deliberately small. A backend is handed a question and a budget,
and returns findings and the sources behind them. Everything else -- run
directories, progress, validation, rendering -- happens on our side of the seam,
identically for every backend.

Two implementations exist so the seam is tested rather than asserted: one over a
research service, one over an embedded agent with web tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Source:
    """One piece of evidence, as the backend reported it.

    ``id`` is assigned on our side, after deduplication, so a backend never has
    to invent stable identifiers and two backends cannot disagree about them.
    """

    url: str
    title: str = ""
    snippet: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"url": self.url, "title": self.title, "snippet": self.snippet}


@dataclass(frozen=True)
class Evidence:
    """What a backend returns: findings, the sources behind them, what it cost."""

    text: str
    sources: list[Source] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    raw: Any = None
    backend: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "sources": [s.to_dict() for s in self.sources],
            "usage": dict(self.usage),
            "backend": self.backend,
        }


@dataclass(frozen=True)
class Budget:
    """What a run is allowed to spend. Depth is advice; the rest are limits."""

    depth: str = "medium"
    max_sources: int | None = None
    timeout_ms: int = 600_000
    model: str | None = None


@runtime_checkable
class ResearchBackend(Protocol):
    """Acquires evidence for a question.

    ``preflight`` must refuse BEFORE any prompt is built or any request is made,
    and must never fall back to a degraded answer. A research result that quietly
    was not researched is worse than no result.
    """

    name: str

    def preflight(self) -> str:
        """Confirm this backend can run, or raise. Returns the credential tier."""
        ...

    def gather(self, query: str, budget: Budget) -> Evidence:
        """Acquire evidence for ``query`` within ``budget``."""
        ...
