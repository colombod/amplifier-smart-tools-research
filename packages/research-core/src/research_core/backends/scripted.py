"""Backends that spend nothing, so every model-backed path can be tested for free.

The seam is a protocol, so a test supplies its own implementation and the whole
pipeline -- preflight, run directory, stages, validation, rendering -- runs end to
end with no provider configured and no tokens spent. That is the same seam a
different provider would arrive through, which is why testing through it tests
something real rather than a mock of something real.
"""

from __future__ import annotations

from research_core.backends.base import Budget, Evidence, Source
from research_core.errors import NoProviderError


class ScriptedBackend:
    """Returns prepared evidence and records what it was asked."""

    name = "scripted"

    def __init__(self, *evidence: Evidence) -> None:
        self._evidence = list(evidence)
        self.questions: list[str] = []
        self.budgets: list[Budget] = []

    def preflight(self) -> str:
        return "scripted"

    def gather(self, query: str, budget: Budget) -> Evidence:
        self.questions.append(query)
        self.budgets.append(budget)
        if not self._evidence:
            return Evidence(text="", sources=[], backend=self.name)
        return self._evidence.pop(0)


class UnconfiguredBackend:
    """A backend with nothing configured, which is a refusal and not a fallback.

    ``gather`` asserts rather than returning anything: if it is ever reached,
    preflight failed to refuse first, and a prompt was built for a run that could
    never have happened.
    """

    name = "unconfigured"

    def preflight(self) -> str:
        raise NoProviderError(
            "No evidence backend is configured.",
            "Set PERPLEXITY_API_KEY and run again.",
        )

    def gather(self, query: str, budget: Budget) -> Evidence:
        raise AssertionError(
            "preflight must refuse before a prompt is ever built or a request made"
        )


def sample_evidence() -> Evidence:
    """Evidence shaped like a real gather, for tests that need something plausible."""
    return Evidence(
        text=(
            "Two independent sources agree that the property holds under the stated "
            "conditions [1][2]. A third dissents on the grounds that the conditions "
            "are rarely met in practice [3]."
        ),
        sources=[
            Source(url="https://arxiv.org/abs/1805.06358", title="A study"),
            Source(url="https://www.w3.org/TR/webauthn-3/", title="A specification"),
            Source(url="https://example.com/dissent", title="A dissenting view"),
        ],
        usage={"tokens_in": 1200, "tokens_out": 340, "cost_usd": "0.0087"},
        backend="scripted",
    )
