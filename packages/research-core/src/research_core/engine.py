"""Running one turn on an embedded agent engine.

Both things that need a model go through here: the backend that gathers evidence
with web tools mounted, and the reasoning turns that run with no tools at all.
They differ by exactly one argument, which is worth noticing -- it is the
evidence behind the open question of whether those two seams should be one.

EVERY engine import lives inside a function body. Importing amplifier_agent_lib
rewrites os.environ["AMPLIFIER_HOME"] unconditionally at import time -- verified
on this machine, not taken on faith -- and a module-level import would poison
that variable for unrelated code in the same process, make every deterministic
verb pay for a provider stack it never uses, and break the conformance rule that
runs `--help` with the environment scrubbed. One cause, three symptoms.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import tempfile
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from research_core.errors import NoProviderError, SmartToolError

#: Where the engine keeps this tool's own session state.
WORKSPACE = "amplifier-research"

#: Tried in order when the caller does not name one.
PROVIDER_PREFERENCE = ("anthropic", "openai", "gemini", "azure-openai")

#: The tools a research gather is allowed. The engine's default plan carries far
#: more -- filesystem, bash, delegation - and a research run has no business
#: with any of them. We FILTER rather than clear, which is the one deliberate
#: divergence from both reference smart tools: they run tool-less turns and so
#: zero the plan, and zeroing it would leave a research agent unable to research.
WEB_TOOLS = ("tool-web", "tool-search")


class EngineUnavailable(SmartToolError):
    """The engine is installed but cannot run here."""

    code = "engine_unavailable"
    exit_code = 1


@dataclass
class TurnResult:
    """What one turn produced, and what it cost."""

    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    model: str | None = None


def _load():
    """Import the engine. Deferred, and the only place it happens."""
    try:
        from amplifier_agent_cli.provider_sources import (
            enumerate_resolvable_providers,
            inject_provider,
            inject_routing_matrix,
        )
        from amplifier_agent_lib import __version__
        from amplifier_agent_lib._runtime import make_turn_handler
        from amplifier_agent_lib.bundle.cache import load_and_prepare_cached
        from amplifier_agent_lib.engine import Engine
        from amplifier_agent_lib.protocol import (
            PROTOCOL_VERSION,
            server_default_capabilities,
        )
        from amplifier_agent_lib.protocol_points.defaults_cli import (
            ApprovalOverride,
            CliApprovalSystem,
        )
    except ModuleNotFoundError as exc:
        raise NoProviderError(
            f"The agent engine is not installed: {exc}",
            "It ships as a resolved dependency, so its absence means a broken "
            "install rather than a missing option: reinstall the tool. Every "
            "deterministic verb keeps working meanwhile.",
        ) from exc

    return {
        "enumerate_resolvable_providers": enumerate_resolvable_providers,
        "inject_provider": inject_provider,
        "inject_routing_matrix": inject_routing_matrix,
        "version": __version__,
        "make_turn_handler": make_turn_handler,
        "load_and_prepare_cached": load_and_prepare_cached,
        "Engine": Engine,
        "PROTOCOL_VERSION": PROTOCOL_VERSION,
        "server_default_capabilities": server_default_capabilities,
        "ApprovalOverride": ApprovalOverride,
        "CliApprovalSystem": CliApprovalSystem,
    }


class _Display:
    """Receives the engine's structured events and forwards them to a callback.

    The reference smart tools pin the shipped display to verbosity "quiet" and
    throw these away, because they run one tool-less turn and want silence. A run
    that takes minutes wants the opposite: this is the only seam that reports
    what is happening WHILE it happens.
    """

    def __init__(self, on_event: Callable[[dict[str, Any]], None] | None) -> None:
        self._on_event = on_event
        self.usage: dict[str, Any] = {}

    async def emit(self, event: dict[str, Any]) -> None:
        kind = event.get("type", "")
        if kind == "usage":
            self.usage = {
                "tokens_in": event.get("inputTokens"),
                "tokens_out": event.get("outputTokens"),
                "cost_usd": str(event["cost"]) if event.get("cost") is not None else None,
            }
        if self._on_event is None:
            return
        if kind in ("tool/started", "tool/completed"):
            self._on_event(
                {
                    "type": "tool",
                    "name": event.get("name"),
                    "status": "started" if kind.endswith("started") else "complete",
                    "duration_ms": event.get("durationMs"),
                }
            )
        elif kind == "progress":
            self._on_event({"type": "progress", "message": event.get("message")})
        elif kind == "error":
            self._on_event({"type": "engine_error", "message": event.get("message")})


def available_providers() -> list[str]:
    """Which providers have usable credentials, as the engine itself sees it."""
    try:
        symbols = _load()
    except NoProviderError:
        return []
    return list(symbols["enumerate_resolvable_providers"]())


def select_provider(resolvable: Sequence[str], *, override: str | None) -> str:
    """Choose a provider. Pure: no I/O, so it is testable without an engine."""
    if override:
        if override not in resolvable:
            raise NoProviderError(
                f"Provider {override!r} was asked for, but its credentials are not configured.",
                f"Set the credential for {override}, or unset the provider "
                "setting to use whichever one resolves.",
            )
        return override
    if not resolvable:
        raise NoProviderError(
            "No AI provider is configured.",
            "Set one of ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, "
            "GEMINI_API_KEY or AZURE_OPENAI_API_KEY. Every deterministic verb "
            "keeps working without one.",
        )
    for preferred in PROVIDER_PREFERENCE:
        if preferred in resolvable:
            return preferred
    return resolvable[0]


def preflight(*, provider: str | None = None) -> str:
    """Confirm a turn could run, before any prompt is built."""
    return select_provider(available_providers(), override=provider)


async def _run_turn_async(
    prompt: str,
    *,
    tools: Sequence[str] = (),
    provider: str | None = None,
    model: str | None = None,
    timeout_ms: int = 600_000,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> TurnResult:
    symbols = _load()
    chosen = select_provider(list(symbols["enumerate_resolvable_providers"]()), override=provider)

    cwd = tempfile.mkdtemp(prefix="amplifier-research-")
    display = _Display(on_event)

    # Anything the bundle prints goes to stderr. stdout carries the result and
    # nothing else, so a caller can parse it without filtering.
    with contextlib.redirect_stdout(sys.stderr):
        prepared = await symbols["load_and_prepare_cached"](aaa_version=symbols["version"])

        # Injection is a no-op while any provider is mounted, and the vendored
        # bundle ships stubs -- so clearing first is load-bearing, not tidiness.
        prepared.mount_plan["providers"] = []
        symbols["inject_provider"](prepared, chosen, model_override=model)
        symbols["inject_routing_matrix"](prepared, chosen)

        # Filter, never clear: keeping the plan's own entries is what leaves the
        # web tools mounted for a gather, and an empty tuple is how a reasoning
        # turn asks for none of them.
        prepared.mount_plan["tools"] = [
            entry
            for entry in (prepared.mount_plan.get("tools") or [])
            if entry.get("module") in set(tools)
        ]
        # Sub-agents and hooks are never wanted: a hook observes a session this
        # tool does not have, and each is a third-party module whose failure to
        # load would fail the turn.
        prepared.mount_plan["agents"] = {}
        prepared.mount_plan["hooks"] = []

        handler = symbols["make_turn_handler"](
            prepared, cwd=cwd, is_resumed=False, workspace=WORKSPACE
        )
        engine = symbols["Engine"](
            turn_handler=handler,
            protocol_points={
                # Nothing that could ask for approval is mounted. Declining
                # anything that somehow does keeps the filtering above from
                # being the only defence.
                "approval": symbols["CliApprovalSystem"](override=symbols["ApprovalOverride"].NO),
                "display": display,
            },
        )
        await engine.boot(
            {
                "protocolVersion": symbols["PROTOCOL_VERSION"],
                "clientInfo": {"name": WORKSPACE, "version": "0.1.0"},
                "capabilities": dict(symbols["server_default_capabilities"]()),
                "sessionId": "",
                "resume": False,
                "cwd": cwd,
            },
            bundle_override=prepared,
        )
        try:
            result = await asyncio.wait_for(
                engine.submit_turn(
                    {
                        "sessionId": "",
                        "turnId": f"turn-{uuid.uuid4().hex}",
                        "prompt": prompt,
                    }
                ),
                timeout=max(timeout_ms, 1) / 1000.0,
            )
        except TimeoutError as exc:
            raise EngineUnavailable(
                f"The turn exceeded its {timeout_ms} ms budget and was aborted.",
                "Raise timeout_ms, or check the provider is reachable. A partial "
                "judgment is not returned, because a partial answer that looks "
                "whole is worse than none.",
            ) from exc
        finally:
            with contextlib.suppress(Exception):
                await engine.shutdown()

    tokens_in = int(result.get("tokensIn") or 0)
    tokens_out = int(result.get("tokensOut") or 0)
    reply = result.get("reply") or ""
    if tokens_in == 0 and tokens_out == 0:
        # The engine reports a mount failure as a reply rather than raising.
        # Passing that on would present a tool that never ran as a model that
        # answered badly.
        raise EngineUnavailable(
            f"The engine returned without reaching a model: {reply or 'no reply'}",
            "Check that the provider's credentials and client library are both "
            "present. Run `check` to see which providers this host resolves.",
        )

    cost = result.get("costUsd")
    return TurnResult(
        text=reply,
        usage={
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": str(cost) if cost is not None else None,
        },
        provider=chosen,
        model=model,
    )


def run_turn(
    prompt: str,
    *,
    tools: Sequence[str] = (),
    provider: str | None = None,
    model: str | None = None,
    timeout_ms: int = 600_000,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> TurnResult:
    """Run one turn, synchronously, on an embedded engine.

    ``tools`` names the modules to keep mounted; an empty sequence is a turn with
    no tools at all. That single argument is the whole difference between a
    gather and a reasoning turn.
    """
    return asyncio.run(
        _run_turn_async(
            prompt,
            tools=tools,
            provider=provider,
            model=model,
            timeout_ms=timeout_ms,
            on_event=on_event,
        )
    )


def engine_home() -> str | None:
    """Where the engine put its home, if it has been imported in this process."""
    return os.environ.get("AMPLIFIER_HOME")
