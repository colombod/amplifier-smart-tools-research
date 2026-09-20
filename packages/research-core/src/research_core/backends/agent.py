"""Evidence from an embedded agent with web tools.

The second implementation behind the ResearchBackend seam, and the reason the
seam is tested rather than asserted. It differs from the Perplexity one in a way
worth stating plainly, because a single abstraction must not pretend the
difference away:

- Perplexity owns its own search-and-synthesise loop. We hand it a question and
  get findings back; we do not see the steps, and it reports no cost.
- This one runs the loop inside a turn we control, with tools we chose, and
  reports real token accounting. We see each tool call as it happens.

Same seam, genuinely different shape. That asymmetry is the evidence the open
question about unifying the two seams asked for.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from research_core.backends.base import Budget, Evidence, Source
from research_core.parsing import NoStructureFound, extract_json

#: How hard the agent is asked to look, by depth. Advice in the prompt rather
#: than a hard limit: the engine bounds the turn, and a number in a sentence is
#: not a guarantee.
DEPTH_GUIDANCE = {
    "low": "Search once or twice. Stop early; this is a quick check.",
    "medium": "Search several times, following what looks load-bearing.",
    "high": "Search widely, read the primary sources, and keep going until "
    "further searching stops changing the answer.",
}


class AgentBackend:
    """Acquires evidence by running an agent with search and fetch mounted."""

    name = "agent"

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        prompt_template: str | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._template = prompt_template

    def preflight(self) -> str:
        from research_core.engine import preflight

        return preflight(provider=self._provider)

    def gather(
        self,
        query: str,
        budget: Budget,
        *,
        scope: str = "",
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> Evidence:
        from research_core.engine import WEB_TOOLS, run_turn

        self.preflight()
        prompt = self._build_prompt(query, budget, scope)

        result = run_turn(
            prompt,
            # Filter, never clear. Both reference smart tools zero the mount plan
            # because they run tool-less turns; zeroing it here would leave a
            # research agent unable to research.
            tools=WEB_TOOLS,
            provider=self._provider,
            model=self._model,
            timeout_ms=budget.timeout_ms,
            on_event=on_event,
        )
        # THE POST-CONDITION, and the only one available. Asking for tools is not
        # getting them: the engine logs a module that fails to load and carries
        # on without it, and there is no window in which to check -- the engine
        # holds a PreparedBundle, and the coordinator that owns the mount
        # registry does not exist until a turn creates one. So the only honest
        # evidence that search happened is that search happened.
        #
        # This matters far more than the telemetry it was found through. A
        # research agent with no tools does not fail. It answers from memory and
        # returns URLs it never opened, which reached sources.json and passed
        # every downstream check because a source was PRESENT. One live run
        # said, in its own words, "No live access to the two listed sources"
        # while two sat in the record.
        if result.tool_calls == 0:
            from research_core.errors import NoEvidence

            raise NoEvidence(
                "The agent completed without calling a single tool, so nothing "
                "was searched or fetched.",
                "Any sources it named would be recalled, not gathered. This is "
                "usually a tool that failed to load -- the engine's stderr names "
                "the missing dependency. Run `check`, or use --backend perplexity.",
            )

        return parse_agent_reply(result.text, usage=result.usage, max_sources=budget.max_sources)

    def _build_prompt(self, query: str, budget: Budget, scope: str) -> str:
        if self._template:
            return self._template.format(
                query=query,
                scope=scope or "(not scoped)",
                guidance=DEPTH_GUIDANCE.get(budget.depth, DEPTH_GUIDANCE["medium"]),
            )
        return (
            "Research the question below using the web tools available to you.\n\n"
            f"{DEPTH_GUIDANCE.get(budget.depth, DEPTH_GUIDANCE['medium'])}\n\n"
            "Return ONLY a JSON document:\n"
            '{"findings": "prose citing sources as [1], [2] by their position in '
            'the list below", "sources": [{"url": "...", "title": "...", '
            '"snippet": "..."}], "confidence": "high|medium|low"}\n\n'
            f"THE QUESTION:\n{query}\n" + (f"\nWHAT WOULD ANSWER IT:\n{scope}\n" if scope else "")
        )


def parse_agent_reply(
    text: str, *, usage: dict[str, Any] | None = None, max_sources: int | None = None
) -> Evidence:
    """Turn an agent's reply into structured evidence.

    Exported because it is the part worth testing, and testing it needs a recorded
    reply rather than a credential.

    A reply carrying no parseable document is a FAILURE, not an empty result. A
    caller that asked for evidence and received nothing cannot tell the difference
    between "the agent found nothing" and "the agent said something we could not
    read", and those want different responses.
    """
    from research_core.backends.perplexity import BackendError

    try:
        document = extract_json(text)
    except NoStructureFound as exc:
        raise BackendError(
            f"The agent's reply carried no readable result: {exc}",
            "This is usually a model that ignored the output format. Run again, "
            "or use --backend perplexity.",
        ) from exc

    if not isinstance(document, dict):
        raise BackendError(
            f"The agent returned a {type(document).__name__} where an object was required.",
            "Run again, or use --backend perplexity.",
        )

    sources: list[Source] = []
    omitted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, entry in enumerate(document.get("sources") or []):
        if not isinstance(entry, dict):
            omitted.append({"index": index, "reason": "not an object"})
            continue
        url = str(entry.get("url") or "").strip()
        if not url:
            omitted.append({"index": index, "reason": "missing or empty url"})
            continue
        if url in seen:
            omitted.append({"index": index, "reason": "duplicate url", "url": url})
            continue
        seen.add(url)
        sources.append(
            Source(
                url=url,
                title=str(entry.get("title") or "").strip(),
                snippet=str(entry.get("snippet") or "").strip(),
            )
        )
    if max_sources is not None:
        sources = sources[:max_sources]

    return Evidence(
        text=str(document.get("findings") or "").strip(),
        sources=sources,
        usage=dict(usage or {}),
        raw=document,
        backend="agent",
        omitted=omitted,
    )
