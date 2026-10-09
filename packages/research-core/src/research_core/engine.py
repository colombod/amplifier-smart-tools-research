"""Running one turn on an embedded agent engine.

Both things that need a model go through here: the backend that gathers evidence
with web tools mounted, and the reasoning turns that run with no tools at all.
They differ by exactly one argument, which is worth noticing -- it is the
evidence behind the open question of whether those two seams should be one.

EVERY Agent import lives inside a function body. Deterministic users do not
load the optional runtime or provider stack. The v0.22 public binding does not
rewrite the host's environment on import.

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

``engine_home`` / ``RESEARCH_ENGINE_HOME`` owns state placement. Public
AgentOptions explicitly names working_directory and sessions_directory below
that tree. AMPLIFIER_AGENT_HOME remains our legacy default alias, not an
upstream v0.22 setting; it is stripped around discovery/construction and restored.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import signal
import sys
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_core.config import SOURCE_DEFAULT, SOURCE_FALLBACK
from research_core.errors import NoProviderError, SmartToolError

#: Our setting, not an Agent host environment variable.
ENGINE_HOME_ENV = "RESEARCH_ENGINE_HOME"
LEGACY_ENGINE_HOME_ENV = "AMPLIFIER_AGENT_HOME"

#: AMPLIFIER_HOME does not select the public Agent's sessions directory.
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

#: Snapshot the caller's initial research state placement.
_INHERITED_ENGINE_HOME = os.environ.get(LEGACY_ENGINE_HOME_ENV)

#: Whether this process has already told its caller that a fallback home is in
#: use. Once per process, not once per turn: a four-stage run would otherwise
#: repeat the same sentence four times, and advice repeated is advice skipped.
_FALLBACK_ANNOUNCED = False

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

#: Explicit public built-in names; no filesystem, bash, or delegation.
WEB_TOOLS = ("web_search", "web_fetch")


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
    tool_successes: int = 0


def default_engine_home() -> Path:
    """Where the engine would put its tree if nobody said otherwise.

    Deliberately the engine's OWN default rather than somewhere of ours: the
    tree holds a module cache measured in hundreds of megabytes, and a default
    that moved it per-caller would mean re-cloning it for every invocation while
    quietly orphaning what is already on disk. Our setting's job is to make the
    location nameable, not to relocate anyone who never had a problem.
    """
    if _INHERITED_ENGINE_HOME:
        return Path(_INHERITED_ENGINE_HOME).expanduser()
    return Path.home() / ".amplifier-agent"


def fallback_engine_home(runs_dir: str | Path) -> Path:
    """Inside the runs directory, which the caller has already pointed somewhere.

    A dot-directory so it cannot be mistaken for a run, and inside rather than
    beside: writing to a SIBLING of the path a confined host allowed would be the
    very bug this whole area exists to fix, one directory over.

    ``list_runs`` skips any directory without a ``run.json``, so this is
    invisible to every navigation verb.
    """
    return Path(runs_dir).expanduser() / ".engine"


def resolved_engine_home() -> tuple[Path, str]:
    """The configured engine home and which tier supplied it.

    Settings are resolved here rather than threaded down from the caller, and
    the reason is the detached child: it is a fresh process that re-resolves
    everything for itself, so a value that travelled as a function argument in
    the parent would be lost precisely in the long-running case this exists for.
    The config file and the environment reach both processes; an argument does
    not, so this setting has no argument tier.

    ONE case resolves to a path nobody named: the default is unusable and the
    caller expressed no preference. A host that confines writes hits exactly
    that, and making it type a second setting to proceed is a worse answer than
    putting the tree inside the runs directory it has already pointed somewhere
    writable -- which is a location it chose, even if it did not choose it for
    this. The fallback is reported as its own tier, never dressed up as a
    default, so nobody has to deduce where their disk went.

    A caller who NAMED a path that does not work is refused instead. Overriding
    a stated intention silently is a different act from filling a gap in it.
    """
    from research_core.config import resolve_settings

    settings = resolve_settings()
    setting = settings.resolved["engine_home"]
    home = Path(str(setting.value)).expanduser()
    # `$AMPLIFIER_AGENT_HOME` arrives through the default tier, because our
    # default IS whatever the engine would have used -- but a caller who
    # exported it named a path just as deliberately as one who wrote the
    # setting, and overriding it silently would rebuild the AMPLIFIER_HOME trap
    # with our name on it. Only a host that named nothing at all is filled in.
    named = setting.source != SOURCE_DEFAULT or bool(_INHERITED_ENGINE_HOME)
    if named or _writable(home):
        return home, setting.source

    candidate = fallback_engine_home(settings["runs_dir"])
    if _writable(candidate):
        return candidate, SOURCE_FALLBACK
    # Neither works: hand back the default so the refusal names the path the
    # caller would otherwise go looking for, and let it say the rest.
    return home, setting.source


def bind_engine_home() -> Path:
    """Resolve state placement without mutating the host environment.

    v0.22 uses AgentOptions.sessions_directory, not AMPLIFIER_AGENT_HOME.
    """
    home, _ = resolved_engine_home()
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
            "the Agent's per-turn working and sessions directories go here"
            if writable
            else "cannot be written to; every model-backed verb would fail here"
        ),
    }
    if source == SOURCE_FALLBACK:
        status["because"] = (
            f"{default_engine_home()} is not writable on this host and nothing "
            "named another path, so the tree goes inside the runs directory "
            "instead. Set engine_home to put it somewhere of your choosing -- "
            "and do set it if several machines share one runs directory, since "
            "this cache is not written to be shared."
        )
    if _INHERITED_OVERWRITTEN_HOME:
        # Cheap to report and expensive to discover: this is the variable a
        # caller exports when they want to move the tree, and the engine
        # overwrites it at import, so it has no effect at all.
        status["ignored"] = (
            f"${OVERWRITTEN_HOME_ENV} is set and has no effect here. ${ENGINE_HOME_ENV}, or the "
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
                "state placement is selected by engine_home, not this variable."
            )
        if source == SOURCE_DEFAULT:
            # Reaching here with the default means the fallback was tried and
            # was no better, so the runs directory is unwritable too. Saying
            # only "set engine_home" would send someone to fix the second
            # problem and meet the first one immediately afterwards.
            from research_core.config import resolve_settings

            note += (
                " The runs directory "
                f"({fallback_engine_home(resolve_settings()['runs_dir'])}) was "
                "tried as a fallback and cannot be written to either, so this "
                "host has no usable path yet: runs_dir most likely needs "
                "pointing somewhere allowed as well."
            )
        raise EngineUnavailable(
            f"The engine's own directory at {home} ({source}) cannot be written to: {exc}",
            "Point it somewhere writable: set engine_home in the config file, "
            f"or ${ENGINE_HOME_ENV}. Every deterministic verb keeps working meanwhile." + note,
        ) from exc
    return home


def _announce_fallback_home(on_event: Callable[[dict[str, Any]], None] | None) -> None:
    """Say it once, into the run's own event log, when a fallback is in use.

    `check` reports it, but a caller who never ran `check` would otherwise find
    a cache inside their runs directory with nothing anywhere saying who put it
    there. Choosing a path on someone's behalf is defensible; doing it quietly
    is not, and the run record is where they will look afterwards.
    """
    global _FALLBACK_ANNOUNCED
    if on_event is None or _FALLBACK_ANNOUNCED:
        return
    home, source = resolved_engine_home()
    if source != SOURCE_FALLBACK:
        return
    _FALLBACK_ANNOUNCED = True
    on_event(
        {
            "type": "progress",
            "message": (
                f"{default_engine_home()} is not writable here, so the engine's "
                f"state and working directories are going to {home}. Set "
                "engine_home to choose somewhere else."
            ),
        }
    )


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
        import amplifier_agent
    except ModuleNotFoundError as exc:
        raise NoProviderError(
            f"The agent engine is not installed: {exc}",
            "It ships as a resolved dependency, so its absence means a broken "
            "install rather than a missing option: reinstall the tool. Every "
            "deterministic verb keeps working meanwhile.",
        ) from exc

    return amplifier_agent


_CONSTRUCTION_LOCK = threading.Lock()


@contextlib.asynccontextmanager
async def _agent_environment():
    """Consume our legacy alias without handing an unknown host key upstream.

    The process-global compatibility window contains no turn/provider work;
    always restore the caller's exact value, including on construction failure.
    """
    # A threading lock spans all event loops/threads. Never block an event loop
    # acquiring it and never leave an executor acquisition running on cancel.
    while not _CONSTRUCTION_LOCK.acquire(blocking=False):
        await asyncio.sleep(0.01)
    legacy = os.environ.pop(LEGACY_ENGINE_HOME_ENV, None)
    try:
        yield
    finally:
        if legacy is not None:
            os.environ[LEGACY_ENGINE_HOME_ENV] = legacy
        _CONSTRUCTION_LOCK.release()


async def _providers(api):
    async with _agent_environment():
        return await api.list_providers()


def _web_approvals(api, tools: Sequence[str]):
    async def approve(request):
        allowed = request.name in tools and request.name in WEB_TOOLS
        return api.ApprovalResponse(decision="allow" if allowed else "deny")

    return approve


class _Display:
    """Project public turn-events/1 records onto research progress."""

    def __init__(self, on_event: Callable[[dict[str, Any]], None] | None) -> None:
        self._on_event = on_event
        self.usage: dict[str, Any] = {}
        self.tool_calls = 0
        self.tool_successes = 0
        self.calls: dict[str, str] = {}

    async def emit(self, event) -> None:
        kind, payload = event.type, event.payload
        if kind == "tool_call":
            self.tool_calls += 1
            self.calls[payload.call.call_id] = payload.call.name
        if kind == "usage":
            self.usage = _usage(payload.snapshot)
        if (
            kind == "tool_result"
            and payload.resolution.outcome == "completed"
            and payload.resolution.call_id in self.calls
        ):
            self.tool_successes += 1
        if self._on_event is None:
            return
        if kind == "tool_call":
            self._on_event({"type": "tool", "name": payload.call.name, "status": "started"})
        elif kind == "tool_result":
            resolution = payload.resolution
            self._on_event(
                {
                    "type": "tool",
                    "name": self.calls.get(resolution.call_id),
                    "status": "complete"
                    if resolution.outcome == "completed"
                    else resolution.outcome,
                }
            )
        elif kind == "progress":
            self._on_event({"type": "progress", "message": str(payload.data)})
        elif kind == "terminal" and payload.error:
            self._on_event({"type": "engine_error", "message": payload.error.message})
        elif kind == "usage":
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
        api = _load()
    except NoProviderError:
        return []
    records = asyncio.run(_providers(api))
    return [p.provider for p in records if p.credentials in ("found", "not_required")]


def available_providers() -> list[str]:
    """Providers that could actually run a turn: credential AND client library.

    The distinction is load-bearing and was found the hard way. The engine
    reported five resolvable providers on a machine where not one client library
    was installed; preflight passed on the credential, and the turn then died at
    mount time with "No module named 'anthropic'". A preflight that checks the
    credential answers a different question from the one the caller asked.
    """
    try:
        api = _load()
    except NoProviderError:
        return []
    return [
        p.provider
        for p in asyncio.run(_providers(api))
        if p.installed and p.credentials in ("found", "not_required")
    ]


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


def preflight(*, provider: str | None = None, model: str | None = None) -> str:
    """Confirm a turn could run, before any prompt is built.

    Two questions, and the second was learned from a real failure: a provider
    that can answer, and somewhere the engine can write. A host may have the
    first without the second -- a sandbox confining writes to its workspace is
    exactly that host -- and discovering it at the first model-backed stage means
    discovering it after the evidence has been bought.
    """
    chosen = select_provider(available_providers(), override=provider)
    _validate_model_selection(chosen, model)
    ensure_engine_home_usable()
    return chosen


def _validate_model_selection(provider: str, model: str | None) -> None:
    """Anthropic alone may inherit the upstream documented default."""
    if provider != "anthropic" and model is None:
        raise EngineUnavailable(
            f"Provider {provider!r} requires an explicit model.",
            "Set model alongside provider in the research config file, set "
            "RESEARCH_MODEL, or pass model to the library adapter. Agent v0.22 "
            "has no provider-specific model defaults; its omitted model is "
            "Anthropic's default, not a model for the selected provider.",
        )


async def _run_turn_local(
    prompt: str,
    *,
    tools: Sequence[str] = (),
    provider: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    timeout_ms: int = 600_000,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    workspace: str | None = None,
) -> TurnResult:
    if not set(tools).issubset(WEB_TOOLS):
        raise EngineUnavailable(
            "Research turns may expose only web_search and web_fetch.",
            "Use the web allowlist for gathering, or an empty tool list for reasoning.",
        )
    api = _load()
    records = await _providers(api)
    chosen = select_provider(
        [p.provider for p in records if p.installed and p.credentials in ("found", "not_required")],
        override=provider,
    )
    _validate_model_selection(chosen, model)
    _announce_fallback_home(on_event)
    display = _Display(on_event)
    actual_provider, actual_model = chosen, model
    result: Any = None

    async def consume(turn):
        nonlocal result, actual_provider, actual_model
        async for event in turn.events():
            payload = event.payload
            if event.type == "turn_started":
                actual_provider = payload.primary_actual.provider
                actual_model = payload.primary_actual.model
            elif event.type == "terminal":
                result = payload
            await display.emit(event)

    with contextlib.nullcontext(workspace) if workspace else _turn_workspace() as cwd:
        async with _agent_environment():
            agent = await api.create_agent(
                api.AgentOptions(
                    provider=chosen,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    tools=list(tools),
                    skills=[],
                    mcp_servers=[],
                    approvals=_web_approvals(api, tools),
                    tool_error_policy="stop",
                    working_directory=cwd,
                    sessions_directory=Path(cwd) / "sessions",
                )
            )
        async with (
            agent,
            await agent.create_session(api.SessionOptions(persistence="ephemeral")) as session,
        ):
            turn = await session.start_turn(api.TurnInput(content=[api.TextPart(text=prompt)]))
            consumer = asyncio.create_task(consume(turn))
            try:
                await asyncio.wait_for(asyncio.shield(consumer), timeout=max(timeout_ms, 1) / 1000)
            except (TimeoutError, asyncio.CancelledError) as exc:
                # Never cancel the sole event consumer: terminal is the
                # runtime's proof that in-flight tool pairs have settled.
                await turn.cancel()
                await asyncio.shield(consumer)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise EngineUnavailable(
                    f"The turn exceeded its {timeout_ms} ms budget and was cancelled.",
                    "Raise timeout_ms, or check the provider is reachable.",
                ) from exc
    if result is None or result.state != "success":
        error = result.error if result else None
        raise EngineUnavailable(
            error.message if error else "The agent stream ended without a successful terminal.",
            error.remedy if error else "Run `check` and inspect the provider/runtime installation.",
        )
    return TurnResult(
        text="".join(part.text for part in (result.content or [])),
        usage=_usage(result.usage),
        provider=actual_provider,
        tool_calls=display.tool_calls,
        tool_successes=display.tool_successes,
        model=actual_model,
    )


def _usage(usage) -> dict[str, Any]:
    """Aggregate known totals without treating unknown as zero or non-USD as USD."""
    entries = usage.entries if usage else []

    def tokens(name):
        values = [getattr(entry, name) for entry in entries]
        return sum(values) if values and all(v is not None for v in values) else None

    costs = {}
    for entry in entries:
        for currency, amount in (entry.cost or {}).items():
            costs[currency] = costs.get(currency, 0) + amount
    return {
        "tokens_in": tokens("tokens_in"),
        "tokens_out": tokens("tokens_out"),
        "cost_usd": (
            str(costs["USD"])
            if entries and all(e.cost is not None and "USD" in e.cost for e in entries)
            else None
        ),
        "cost": (
            {currency: str(amount) for currency, amount in costs.items()}
            if costs and all(e.cost is not None for e in entries)
            else None
        ),
    }


SHUTDOWN_SECONDS = 30.0


async def _run_turn_async(
    prompt: str,
    *,
    tools: Sequence[str] = (),
    provider: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    timeout_ms: int = 600_000,
    on_event=None,
    _worker_command=None,
) -> TurnResult:
    """Supervise a disposable Agent process; never replay a submitted turn."""
    home = ensure_engine_home_usable()
    cwd = tempfile.mkdtemp(prefix="turn-", dir=str(home / WORK_SUBDIR))
    environment = dict(os.environ)
    environment.pop(LEGACY_ENGINE_HOME_ENV, None)
    environment[ENGINE_HOME_ENV] = str(home)
    request = dict(
        prompt=prompt,
        tools=list(tools),
        provider=provider,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_ms=timeout_ms,
        workspace=cwd,
    )
    # Serialize before any child exists. No blocking pipe write can precede
    # ownership or deadline admission.
    wire_request = (json.dumps(request) + "\n").encode()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(timeout_ms, 1) / 1000
    grace = None
    primary = None
    presentation = None
    result = None
    runtime_error = None
    settled = False
    buffer = b""
    process = None

    def group_alive():
        if process is None:
            return False
        try:
            os.killpg(process.pid, 0)
            return True
        except ProcessLookupError:
            return False

    def signal_group(value):
        if process is None:
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, value)

    async def supervise():
        nonlocal grace, primary, presentation, result, runtime_error, settled, buffer, process
        try:
            process = await asyncio.create_subprocess_exec(
                *(_worker_command or [sys.executable, "-m", "research_core.agent_worker"]),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                env=environment,
                start_new_session=True,
            )
        except OSError as error:
            raise EngineUnavailable(
                f"Agent worker launch failed: {error}", f"Workspace retained at {cwd}."
            ) from error
        assert process.stdin is not None and process.stdout is not None
        output = process.stdout
        input_stream = process.stdin

        async def deliver():
            input_stream.write(wire_request)
            await input_stream.drain()
            input_stream.close()
            await input_stream.wait_closed()

        delivery = asyncio.create_task(deliver())
        reader = asyncio.create_task(output.read(65536))
        reaper = asyncio.create_task(process.wait())
        escalation = None
        while True:
            now = loop.time()
            if primary is None and now >= deadline:
                primary = EngineUnavailable(
                    f"The turn exceeded its {timeout_ms} ms budget and was cancelled.",
                    "Raise timeout_ms or check provider availability.",
                )
                grace = now + SHUTDOWN_SECONDS
                signal_group(signal.SIGTERM)
            if grace is not None and now >= grace and escalation is None:
                signal_group(signal.SIGKILL)
                escalation = now + 1.0
            if delivery.done():
                try:
                    delivery.result()
                except (BrokenPipeError, ConnectionResetError, OSError) as error:
                    if runtime_error is None:
                        runtime_error = EngineUnavailable(
                            f"Agent request delivery failed: {error}", "No turn is replayed."
                        )
                        if grace is None:
                            grace = now + SHUTDOWN_SECONDS
                            signal_group(signal.SIGTERM)
            data = b""
            if reader.done():
                data = reader.result()
                if data:
                    reader = asyncio.create_task(output.read(65536))
            if data:
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    try:
                        record = json.loads(line)
                        kind = record["type"]
                        if kind == "result":
                            result = TurnResult(**record["result"])
                        elif kind == "settled":
                            settled = True
                        elif kind == "error":
                            runtime_error = EngineUnavailable(record["message"], record["remedy"])
                        elif kind == "event" and on_event and presentation is None:
                            try:
                                on_event(record["event"])
                            except Exception as error:
                                presentation = error
                    except (ValueError, KeyError, TypeError) as error:
                        runtime_error = EngineUnavailable(str(error), "Malformed worker protocol.")
            exited = reaper.done()
            if exited and reader.done() and not data and not group_alive():
                break
            if escalation is not None and now >= escalation:
                break
            await asyncio.sleep(0.01)
        for task in (delivery, reader, reaper):
            if not task.done():
                task.cancel()
        await asyncio.gather(delivery, reader, reaper, return_exceptions=True)
        input_stream.close()
        verified = process.returncode is not None and not group_alive()
        if process.returncode not in (None, 0):
            runtime_error = EngineUnavailable(
                f"Agent worker exited with status {process.returncode}.",
                f"Workspace retained at {cwd}; PID/PGID {process.pid}.",
            )
        if verified and settled and process.returncode == 0 and runtime_error is None:
            shutil.rmtree(cwd)
        else:
            detail = (
                f"Workspace retained at {cwd}; PID/PGID {process.pid}; "
                f"exit={process.returncode}; group_absent={not group_alive()}."
            )
            if primary:
                primary.add_note(detail)
            elif runtime_error:
                runtime_error.add_note(detail)
            else:
                runtime_error = EngineUnavailable("Agent cleanup settlement unresolved.", detail)
        if primary:
            if presentation:
                primary.add_note(f"Presentation error: {presentation!r}")
            raise primary
        if runtime_error:
            if presentation:
                runtime_error.add_note(f"Presentation error: {presentation!r}")
            raise runtime_error
        if result is None:
            raise EngineUnavailable("Agent worker exited without a result.", f"Inspect {cwd}.")
        if presentation:
            raise presentation
        return result

    owned = asyncio.create_task(supervise())
    while True:
        try:
            return await asyncio.shield(owned)
        except asyncio.CancelledError:
            if owned.done():
                raise
            if primary is None:
                primary = asyncio.CancelledError()
                grace = loop.time() + SHUTDOWN_SECONDS
                signal_group(signal.SIGTERM)


def run_turn(
    prompt: str,
    *,
    tools: Sequence[str] = (),
    provider: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    timeout_ms: int = 600_000,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> TurnResult:
    """Run one turn, synchronously, on an embedded engine.

    ``tools`` names the modules to keep mounted; an empty sequence is a turn with
    no tools at all. That single argument is the whole difference between a
    gather and a reasoning turn.
    """
    api = _load()
    try:
        return asyncio.run(
            _run_turn_async(
                prompt,
                tools=tools,
                provider=provider,
                model=model,
                reasoning_effort=reasoning_effort,
                timeout_ms=timeout_ms,
                on_event=on_event,
            )
        )
    except api.AgentError as exc:
        raise EngineUnavailable(exc.message, exc.remedy) from exc


def engine_home() -> str:
    """The tree the engine writes into, whether or not it has been imported yet.

    It used to report ``$AMPLIFIER_HOME``, which answered a different question
    than its name suggested: that variable is set by the engine at import, so
    this returned None until something had already run, and afterwards named a
    subdirectory rather than the tree. What a caller wants to know is where the
    writes will land, and that is answerable before anything is imported.
    """
    return str(resolved_engine_home()[0])
