"""The seam the reasoning turns arrive through.

A Reasoner takes a prompt and returns text. That is the whole contract, and it is
deliberately narrower than the backend seam beside it: a reasoning turn has no
tools, no search, and no opinion about where evidence comes from. It reasons over
what it is handed.

Two implementations, and the second is why the first can be trusted: the agent
one runs a real turn, and the scripted one lets every model-backed path in this
package be exercised end to end with no provider configured and no tokens spent.
An UnconfiguredReasoner raises from ``think`` rather than returning, so a
preflight that failed to refuse first cannot pass quietly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Thought:
    """What one reasoning turn produced, and what it cost."""

    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    provider: str = ""


@runtime_checkable
class Reasoner(Protocol):
    """Reasons over what it is given. No tools, no search, no evidence of its own."""

    name: str

    def preflight(self) -> str:
        """Confirm a turn could run, before any prompt is built."""
        ...

    def think(
        self, prompt: str, *, on_event: Callable[[dict[str, Any]], None] | None = None
    ) -> Thought:
        """Run one turn."""
        ...


class AgentReasoner:
    """Reasons on an embedded agent engine, with no tools mounted.

    Tool-less on purpose. These turns scope a question and weigh evidence that has
    already been gathered; giving them search would let a synthesis quietly
    introduce a source the run never recorded, which is the one thing the citation
    check downstream exists to catch.
    """

    name = "agent"

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        timeout_ms: int = 600_000,
    ) -> None:
        self._provider = provider
        self._model = model
        self._timeout_ms = timeout_ms

    def preflight(self) -> str:
        from research_core.engine import preflight

        return preflight(provider=self._provider)

    def think(
        self, prompt: str, *, on_event: Callable[[dict[str, Any]], None] | None = None
    ) -> Thought:
        from research_core.engine import run_turn

        result = run_turn(
            prompt,
            tools=(),
            provider=self._provider,
            model=self._model,
            timeout_ms=self._timeout_ms,
            on_event=on_event,
        )
        return Thought(text=result.text, usage=result.usage, provider=result.provider)


class ScriptedReasoner:
    """Replies from a script, and records what it was asked.

    The prompts it captures are the point as often as the replies are: a test can
    assert that a repair attempt actually carried the specific markers that were
    rejected, rather than merely that a second attempt happened.
    """

    name = "scripted"

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []

    def preflight(self) -> str:
        return "scripted"

    def think(
        self, prompt: str, *, on_event: Callable[[dict[str, Any]], None] | None = None
    ) -> Thought:
        self.prompts.append(prompt)
        reply = self._replies.pop(0) if self._replies else ""
        return Thought(
            text=reply,
            usage={"tokens_in": 100, "tokens_out": 50, "cost_usd": "0.0010"},
            provider="scripted",
        )


class UnconfiguredReasoner:
    """Nothing configured, which is a refusal and not a fallback."""

    name = "unconfigured"

    def preflight(self) -> str:
        from research_core.errors import NoProviderError

        raise NoProviderError(
            "No AI provider is configured for the reasoning stages.",
            "Set one of ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, "
            "GEMINI_API_KEY or AZURE_OPENAI_API_KEY. Every deterministic verb "
            "keeps working without one.",
        )

    def think(
        self, prompt: str, *, on_event: Callable[[dict[str, Any]], None] | None = None
    ) -> Thought:
        raise AssertionError("preflight must refuse before a prompt is ever built or a turn run")
