"""Evidence from Perplexity's research API.

Ported from the Amplifier bundle this tool grew out of, where the same request
shaping, response parsing, citation extraction and mode fallback already existed
and already carried no Amplifier imports.

Two things changed in the port, and both are the point of doing it:

The parsed result is now the PUBLIC return value. The bundle built a clean
structured result internally and then serialised it to markdown prose, so a
caller wanting structured citations had to re-parse text. Here the structure is
what leaves the function, and prose is one rendering of it among several.

The credential is checked at CALL time, not at import or mount time. The bundle
substituted a placeholder when its key was absent and never failed to mount,
which is the opposite of what the conformance kit checks for.

The SDK import is deferred into the method that needs it, so importing this
module -- which the deterministic verbs do, transitively -- costs nothing and
requires nothing.
"""

from __future__ import annotations

from typing import Any

from research_core.backends.base import Budget, Evidence, Source
from research_core.credentials import resolve_credential
from research_core.errors import NoProviderError, SmartToolError

#: The only preset the research API accepts. Named here rather than inline so a
#: change in the service is one edit.
RESEARCH_PRESET = "pro-search"

#: Depth maps to how many steps the service may take. The service's own ceiling
#: is 10; asking for more is an error rather than a silent clamp.
DEPTH_STEPS = {"low": 2, "medium": 5, "high": 9}
DEPTH_EFFORT = {"low": "low", "medium": "medium", "high": "high"}


class BackendError(SmartToolError):
    """The backend was reached and failed."""

    code = "backend_error"
    exit_code = 1


class PerplexityBackend:
    """Acquires evidence from Perplexity's research API."""

    name = "perplexity"

    def __init__(self, *, model: str | None = None) -> None:
        self._model = model

    def preflight(self) -> str:
        """Refuse before a prompt is built, naming the variable and the remedy."""
        value, status = resolve_credential("perplexity")
        if value is None:
            raise NoProviderError(
                "The research verb needs the Perplexity backend and no credential is configured.",
                "Set PERPLEXITY_API_KEY, or put perplexity in "
                "~/.config/amplifier-research/credentials.toml with mode 0600. "
                "Every deterministic verb keeps working without it.",
            )
        return status.source

    def _client(self) -> Any:
        # Deferred: importing this module must not require the SDK, because the
        # deterministic verbs import it transitively and must run with nothing
        # installed beyond the tool itself.
        try:
            from perplexity import Perplexity
        except ModuleNotFoundError as exc:
            raise NoProviderError(
                "The Perplexity SDK is not installed.",
                "It ships as a resolved dependency of this tool, so its absence "
                "means a broken install rather than a missing option: reinstall "
                "the tool. Deterministic verbs keep working meanwhile.",
            ) from exc

        key, _ = resolve_credential("perplexity")
        return Perplexity(api_key=key)

    def gather(
        self,
        query: str,
        budget: Budget,
        *,
        scope: str = "",
        on_event: Any = None,
    ) -> Evidence:
        """One research call, parsed into structure rather than prose.

        ``scope`` and ``on_event`` are honest no-ops here, not stubs. The service
        takes a question and owns its own search loop, so there is nothing to
        pass a scope to; and it is one blocking request, so there is nothing to
        report while it runs.
        """
        self.preflight()
        steps = DEPTH_STEPS.get(budget.depth, DEPTH_STEPS["medium"])
        effort = DEPTH_EFFORT.get(budget.depth, "medium")

        try:
            response = self._client().responses.create(
                input=query,
                preset=RESEARCH_PRESET,
                reasoning={"effort": effort},
                max_steps=steps,
            )
        except NoProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - the backend's errors are not ours
            raise BackendError(
                f"The Perplexity backend failed: {type(exc).__name__}: {exc}",
                "Check the service status and the credential, then run again. A "
                "run that failed keeps whatever it gathered before failing.",
            ) from exc

        return parse_response(response, max_sources=budget.max_sources)


def _text_of(response: Any) -> str:
    """Collect the message text from a response's output items."""
    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", None) in ("output_text", "text"):
                text = getattr(content, "text", "")
                if text:
                    parts.append(text)
    return "\n".join(parts)


def _field(obj: Any, name: str) -> Any:
    """Read a field from an SDK object or a plain dict, indifferently."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _tool_calls_of(usage: Any, cost_block: Any) -> dict[str, dict[str, Any]]:
    """What the service searched and fetched, and what each cost.

    Two sources agree here and either may be absent, so take what is present:
    `tool_calls_details` carries invocation counts, `tool_calls_cost_details`
    carries per-kind cost.
    """
    details = _field(usage, "tool_calls_details") or {}
    costs = _field(cost_block, "tool_calls_cost_details") or {}
    names = set()
    for holder in (details, costs):
        if isinstance(holder, dict):
            names |= set(holder.keys())
    calls: dict[str, dict[str, Any]] = {}
    for name in sorted(names):
        entry = _field(details, name) or {}
        cost = _field(costs, name)
        calls[name] = {
            "invocations": int(_field(entry, "invocation") or 0),
            "cost_usd": str(cost) if cost is not None else None,
        }
    return calls


def _sources_of(response: Any) -> list[Source]:
    """Citations, from all three places the service reports them, deduplicated.

    Annotations on the message, the search results, and the fetched pages each
    carry URLs, and the same URL routinely appears in more than one. Order is
    preserved so the first mention wins its position.
    """
    seen: set[str] = set()
    found: list[Source] = []

    def add(url: Any, title: Any, snippet: Any = "") -> None:
        if not url or not isinstance(url, str):
            return
        cleaned = url.strip()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        found.append(
            Source(
                url=cleaned,
                title=(title or "").strip() if isinstance(title, str) else "",
                snippet=(snippet or "").strip() if isinstance(snippet, str) else "",
            )
        )

    for item in getattr(response, "output", []) or []:
        kind = getattr(item, "type", None)
        if kind == "message":
            for content in getattr(item, "content", []) or []:
                for annotation in getattr(content, "annotations", None) or []:
                    add(
                        getattr(annotation, "url", None),
                        getattr(annotation, "title", None),
                    )
        elif kind in ("search_results", "fetch_url_results"):
            for result in getattr(item, "results", []) or []:
                add(
                    getattr(result, "url", None),
                    getattr(result, "title", None) or getattr(result, "name", None),
                    getattr(result, "snippet", None),
                )
    return found


def parse_response(response: Any, *, max_sources: int | None = None) -> Evidence:
    """Turn a service response into structured evidence.

    Exported because it is the part worth testing, and testing it needs a
    recorded response rather than a live call or a credential.
    """
    usage = getattr(response, "usage", None)
    accounting: dict[str, Any] = {}
    if usage is not None:
        tokens_in = int(_field(usage, "input_tokens") or 0)
        tokens_out = int(_field(usage, "output_tokens") or 0)
        accounting = {"tokens_in": tokens_in, "tokens_out": tokens_out}

        # The service reports cost in detail, under usage.cost. We previously
        # looked for a flat `cost_usd` that does not exist on this shape, found
        # nothing, and recorded None -- so every Perplexity call was invisible
        # in our accounting while the caller was genuinely being billed. Tokens
        # and credits are spend whether or not a number is attached.
        cost_block = _field(usage, "cost") or {}
        total = _field(cost_block, "total_cost")
        accounting["cost_usd"] = str(total) if total is not None else None
        accounting["currency"] = _field(cost_block, "currency") or "USD"

        # What the service DID on our behalf, and what each kind of call cost.
        # This is the Perplexity equivalent of the agent backend's tool events:
        # the searches and fetches are the work, and a caller comparing the two
        # backends should be able to see both.
        calls = _tool_calls_of(usage, cost_block)
        if calls:
            accounting["calls"] = calls
            accounting["call_count"] = sum(c["invocations"] for c in calls.values())

    error = getattr(response, "error", None)
    if error is not None:
        raise BackendError(
            f"The backend reported an error: "
            f"{getattr(error, 'code', 'unknown')}: {getattr(error, 'message', '')}",
            "Check the service status, then run again.",
        )

    sources = _sources_of(response)
    if max_sources is not None:
        sources = sources[:max_sources]

    return Evidence(
        text=_text_of(response),
        sources=sources,
        usage=accounting,
        raw=response,
        backend="perplexity",
    )
