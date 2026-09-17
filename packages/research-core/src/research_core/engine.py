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

WHERE THE ENGINE WRITES is this module's problem too. Left alone it puts several
hundred megabytes of module clones and prepared-bundle cache under
``~/.amplifier-agent``, and opens a scratch working directory wherever ``$TMPDIR``
points. Neither location was chosen by the caller, which is harmless on a
workstation and fatal in a sandbox that confines writes to a workspace: the first
model-backed stage dies on a bare ``PermissionError`` naming a path nobody asked
for -- after the evidence has been gathered and paid for. So this module binds
that location from a setting (``engine_home``), puts the turn's working directory
inside it instead of ``$TMPDIR``, removes that directory afterwards, and proves
the whole tree is writable in preflight, before a prompt is built or a token
spent.

The variable that moves it is ``AMPLIFIER_AGENT_HOME``, and that is not the
obvious guess. ``AMPLIFIER_HOME`` is the one the storage resolver underneath
reads, so it is the one anybody reaching for a lever exports first -- and the
engine overwrites it at import, so exporting it does nothing whatsoever, in
silence. Verified by setting it and watching it change, not assumed.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_core.errors import NoProviderError, SmartToolError

#: Where the engine keeps this tool's own session state.
WORKSPACE = "amplifier-research"

#: The one environment variable that moves the engine's on-disk tree. Everything
#: it writes -- prepared-bundle cache, module clones, session state -- is under
#: this, and our turn working directories are put there too.
ENGINE_HOME_ENV = "AMPLIFIER_AGENT_HOME"

#: The variable a caller reaches for instead, and which does nothing: the engine
#: overwrites it at import. Named here so the refusal below can say so, because
#: the alternative is someone exporting it and believing the problem is elsewhere.
OVERWRITTEN_HOME_ENV = "AMPLIFIER_HOME"

#: Turn working directories live here, under the engine home. A subdirectory
#: rather than the root so that deleting scratch can never reach the cache.
WORK_SUBDIR = "work"

#: Whether the CALLER had exported the useless variable, snapshotted before this
#: process could import an engine -- which is guaranteed, because every engine
#: import in this package is inside a function in this module. Reading the live
#: environment instead would report the engine's own value back at the caller
#: and advise them about a variable they never set; the first version of this
#: did exactly that.
_INHERITED_OVERWRITTEN_HOME = os.environ.get(OVERWRITTEN_HOME_ENV)

#: Tried in order when the caller does not name one.
PROVIDER_PREFERENCE = ("anthropic", "openai", "gemini", "azure-openai")

#: A provider needs BOTH a credential and its client library. The engine's own
#: resolution answers only the first question -- it enumerates providers whose
#: credentials are present, whether or not a turn could actually run -- and the
#: engine ships with no provider client library at all, so the gap is the normal
#: case rather than an edge one. Mapping the second question is therefore ours.
PROVIDER_CLIENTS: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "openai-chatgpt": "openai",
    "azure-openai": "openai",
    "github-copilot": "openai",
    "gemini": "google.genai",
}

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
    #: Tool calls the engine reported during this turn. Zero, on a turn that
    #: asked for tools, means the turn ran without them.
    tool_calls: int = 0


def default_engine_home() -> Path:
    """Where the engine would put its tree if nobody said otherwise.

    Deliberately the engine's OWN default rather than somewhere of ours: the
    tree holds a module cache measured in hundreds of megabytes, and a default
    that moved it per-caller would mean re-cloning it for every invocation while
    quietly orphaning what is already on disk. Our setting's job is to make the
    location nameable, not to relocate anyone who never had a problem.
    """
    override = os.environ.get(ENGINE_HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".amplifier-agent"


def resolved_engine_home() -> tuple[Path, str]:
    """The configured engine home and which tier supplied it.

    Settings are resolved here rather than threaded down from the caller, and
    the reason is the detached child: it is a fresh process that re-resolves
    everything for itself, so a value that travelled as a function argument in
    the parent would be lost precisely in the long-running case this exists for.
    The config file and the environment reach both processes; an argument does
    not, so this setting has no argument tier.
    """
    from research_core.config import resolve_settings

    setting = resolve_settings().resolved["engine_home"]
    return Path(str(setting.value)).expanduser(), setting.source


def bind_engine_home() -> Path:
    """Point the engine's tree at the configured home. Idempotent.

    Must run before amplifier_agent_lib is imported: the binding it performs on
    its own storage happens at import time, so a value set afterwards is read by
    nothing. Calling it from _load, immediately above the only import site in
    this package, is what makes "before" structural rather than remembered.
    """
    home, _ = resolved_engine_home()
    os.environ[ENGINE_HOME_ENV] = str(home)
    return home


def _writable(path: Path) -> bool:
    """Whether a path can be written to, or created and then written to."""
    probe = path
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            return False
        probe = parent
    return os.access(probe, os.W_OK)


def engine_home_status() -> dict[str, Any]:
    """Where the engine will write, and whether it can. Reported by `check`.

    Deterministic: reads settings and the filesystem, imports no engine, needs no
    credential. A host that cannot run a model-backed verb can still be told why
    before it tries one.
    """
    home, source = resolved_engine_home()
    writable = _writable(home)
    status: dict[str, Any] = {
        "path": str(home),
        "source": source,
        "writable": writable,
        "detail": (
            "the engine's cache, module clones and per-turn working directories go here"
            if writable
            else "cannot be written to; every model-backed verb would fail here"
        ),
    }
    if _INHERITED_OVERWRITTEN_HOME:
        # Cheap to report and expensive to discover: this is the variable a
        # caller exports when they want to move the tree, and the engine
        # overwrites it at import, so it has no effect at all.
        status["ignored"] = (
            f"${OVERWRITTEN_HOME_ENV} is set and has no effect here: the engine "
            f"overwrites it when it is imported. ${ENGINE_HOME_ENV}, or the "
            "engine_home setting, is what moves the tree."
        )
    return status


def ensure_engine_home_usable() -> Path:
    """Prove the engine can write where it is about to, or refuse saying where.

    Called from preflight and again from the turn itself. The failure this
    replaces was a bare PermissionError raised deep inside a bundle load, on the
    first model-backed stage of a run whose evidence had already been gathered
    and paid for -- a true message naming a path the caller never chose, with no
    statement of which knob moves it.
    """
    home = bind_engine_home()
    try:
        (home / WORK_SUBDIR).mkdir(parents=True, exist_ok=True)
        probe = home / WORK_SUBDIR / f".writable-{uuid.uuid4().hex}"
        probe.touch()
        probe.unlink()
    except OSError as exc:
        _, source = resolved_engine_home()
        note = ""
        if _INHERITED_OVERWRITTEN_HOME:
            note = (
                f" Note that ${OVERWRITTEN_HOME_ENV} is set and does nothing: "
                "the engine overwrites it at import."
            )
        raise EngineUnavailable(
            f"The engine's own directory at {home} ({source}) cannot be written to: {exc}",
            "Point it somewhere writable: set engine_home in the config file, "
            f"or ${ENGINE_HOME_ENV}. It holds a module cache of several hundred "
            "megabytes, so prefer a path that survives between runs over a "
            "temporary one. Every deterministic verb keeps working meanwhile." + note,
        ) from exc
    return home


@contextlib.contextmanager
def _turn_workspace() -> Iterator[str]:
    """A working directory for one turn, inside the engine home, then gone.

    Two corrections in one small scope. It used to be ``tempfile.mkdtemp()`` with
    no directory argument, which put it wherever ``$TMPDIR`` pointed -- a SECOND
    location outside the caller's control, so a host that had made the engine
    home writable could still be tripped by the other one. And nothing ever
    removed it: every turn left a directory behind, for the life of the machine.

    Writability is proved here as well as in preflight. A library caller can
    reach ``run_turn`` directly, and it should refuse the same way.

    A process killed outright leaves its directory behind -- empty, since the
    engine's own state lives elsewhere under the home. That is the honest limit
    of cleanup in a finally block, and it is not worth a reaper with a time
    policy to sweep up empty directories.
    """
    work = ensure_engine_home_usable() / WORK_SUBDIR
    cwd = tempfile.mkdtemp(prefix="turn-", dir=str(work))
    try:
        # Anything the bundle prints goes to stderr. stdout carries the result
        # and nothing else, so a caller can parse it without filtering.
        with contextlib.redirect_stdout(sys.stderr):
            yield cwd
    finally:
        shutil.rmtree(cwd, ignore_errors=True)


def _load():
    """Import the engine. Deferred, and the only place it happens."""
    bind_engine_home()
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
        #: How many tool calls the engine actually reported. This is the ONLY
        #: evidence available that the tools we asked for really mounted and
        #: really ran. There is no post-boot window in which to check: the engine
        #: holds a PreparedBundle, not a session, and the coordinator that owns
        #: the mount registry does not exist until a turn creates one. So the
        #: post-condition can only be observed from the outcome.
        self.tool_calls = 0

    async def emit(self, event: dict[str, Any]) -> None:
        kind = event.get("type", "")
        if kind == "tool/started":
            self.tool_calls += 1
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
        elif kind == "usage":
            # Was tracked into self.usage above but never handed to the
            # caller -- a run with several LLM calls (a gather with tool use
            # is exactly that) never surfaced usage as it happened, only
            # self.usage's last value, which nothing downstream reads either.
            # Forwarding here is what makes a long turn's cost visible live,
            # matching the five event types this class's own contract claims
            # to map (tool/started, tool/completed, progress, error, usage).
            self._on_event({"type": "usage", **self.usage})


def client_library_for(provider: str) -> str | None:
    """The client library a provider needs, if we know of one."""
    return PROVIDER_CLIENTS.get(provider)


def client_library_present(provider: str) -> bool:
    """Whether a provider's client library can actually be imported.

    ``importlib.util.find_spec`` rather than an import: asking whether a module
    exists must not execute it, and importing a provider SDK to find out would
    be a side effect in a function whose whole job is to answer a question.
    """
    import importlib.util

    module = PROVIDER_CLIENTS.get(provider)
    if module is None:
        # Unknown provider: we cannot vouch for it, and saying so beats both
        # guessing yes and refusing outright.
        return True
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def credentialled_providers() -> list[str]:
    """Providers whose credentials resolve, which is not the same as usable."""
    try:
        symbols = _load()
    except NoProviderError:
        return []
    return list(symbols["enumerate_resolvable_providers"]())


def available_providers() -> list[str]:
    """Providers that could actually run a turn: credential AND client library.

    The distinction is load-bearing and was found the hard way. The engine
    reported five resolvable providers on a machine where not one client library
    was installed; preflight passed on the credential, and the turn then died at
    mount time with "No module named 'anthropic'". A preflight that checks the
    credential answers a different question from the one the caller asked.
    """
    return [p for p in credentialled_providers() if client_library_present(p)]


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
        # Say which of the two halves is missing. "No provider configured" when
        # the credential is right there and the library is not sends someone to
        # check the wrong thing.
        with_credentials = credentialled_providers()
        if with_credentials:
            missing = sorted({client_library_for(p) or p for p in with_credentials})
            raise NoProviderError(
                "Credentials resolve for "
                f"{', '.join(with_credentials)}, but none of their client "
                f"libraries is installed ({', '.join(missing)}).",
                f"Install one: pip install {missing[0]}. The agent engine does "
                "not ship a provider client of its own, so a credential alone "
                "is not enough to run a turn. Every deterministic verb keeps "
                "working without either.",
            )
        raise NoProviderError(
            "No AI provider is configured.",
            "Set one of ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, "
            "GEMINI_API_KEY or AZURE_OPENAI_API_KEY, and install its client "
            "library. Every deterministic verb keeps working without one.",
        )
    for preferred in PROVIDER_PREFERENCE:
        if preferred in resolvable:
            return preferred
    return resolvable[0]


def preflight(*, provider: str | None = None) -> str:
    """Confirm a turn could run, before any prompt is built.

    Two questions, and the second was learned from a real failure: a provider
    that can answer, and somewhere the engine can write. A host may have the
    first without the second -- a sandbox confining writes to its workspace is
    exactly that host -- and discovering it at the first model-backed stage means
    discovering it after the evidence has been bought.
    """
    chosen = select_provider(available_providers(), override=provider)
    ensure_engine_home_usable()
    return chosen


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

    display = _Display(on_event)

    with _turn_workspace() as cwd:
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
        tool_calls=display.tool_calls,
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


def engine_home() -> str:
    """The tree the engine writes into, whether or not it has been imported yet.

    It used to report ``$AMPLIFIER_HOME``, which answered a different question
    than its name suggested: that variable is set by the engine at import, so
    this returned None until something had already run, and afterwards named a
    subdirectory rather than the tree. What a caller wants to know is where the
    writes will land, and that is answerable before anything is imported.
    """
    return str(resolved_engine_home()[0])
