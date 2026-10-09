"""Replay public events recorded with the real v0.22.0 runtime.

To regenerate (spends provider tokens):
  .venv/bin/python packages/research-core/tests/test_display_events.py --record

The recorder calls create_agent, not a fake Agent. Offline tests reconstruct
public records from its on-disk observations. No provider is needed to replay.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from research_core.engine import _Display, _usage

FIXTURE = Path(__file__).parent / "fixtures" / "agent-v022-events.json"


def encode(value):
    if dataclasses.is_dataclass(value):
        return {
            "$record": type(value).__name__,
            **{f.name: encode(getattr(value, f.name)) for f in dataclasses.fields(value)},
        }
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, list):
        return [encode(v) for v in value]
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, Exception):
        return {
            "$record": "AgentError",
            **{
                k: encode(getattr(value, k))
                for k in (
                    "code",
                    "category",
                    "message",
                    "remedy",
                    "retryable",
                    "correlation_id",
                    "details",
                )
            },
        }
    return value


def decode(value, api) -> Any:
    if isinstance(value, list):
        return [decode(v, api) for v in value]
    if not isinstance(value, dict):
        return value
    if "$decimal" in value:
        return Decimal(value["$decimal"])
    if "$datetime" in value:
        return datetime.fromisoformat(value["$datetime"])
    if "$record" in value:
        return getattr(api, value["$record"])(
            **{k: decode(v, api) for k, v in value.items() if k != "$record"}
        )
    return {k: decode(v, api) for k, v in value.items()}


def test_recorded_runtime_events_reach_progress_and_count_calls():
    api = pytest.importorskip("amplifier_agent")
    recording = json.loads(FIXTURE.read_text())
    assert recording["version"] == "0.22.0"
    assert recording["tag_commit"] == "915edf9372312d4c8244df4b2b16b094cf455cff"
    forwarded = []
    display = _Display(forwarded.append)

    async def replay():
        for raw in recording["events"]:
            await display.emit(decode(raw, api))

    asyncio.run(replay())
    assert display.tool_calls == recording["tool_calls"] == 1
    assert display.tool_successes == 1
    assert [e["status"] for e in forwarded if e["type"] == "tool"] == ["started", "complete"]
    assert {e["name"] for e in forwarded if e["type"] == "tool"} == {"web_fetch"}
    usages = [e for e in forwarded if e["type"] == "usage"]
    assert usages[0]["tokens_in"] is None
    assert usages[-1] == {"type": "usage", **recording["usage"]}
    assert display.usage == recording["usage"]


def test_unknown_usage_is_not_reported_as_zero():
    assert _usage(None) == {"tokens_in": None, "tokens_out": None, "cost_usd": None, "cost": None}


def test_mixed_currencies_and_unknown_tokens_are_preserved():
    api = pytest.importorskip("amplifier_agent")
    usage = api.Usage(
        entries=[
            api.UsageEntry(
                provider="anthropic",
                model="a",
                tokens_in=12,
                tokens_out=None,
                cost={"EUR": Decimal("1.25")},
            ),
            api.UsageEntry(
                provider="openai",
                model="b",
                tokens_in=None,
                tokens_out=4,
                cost={"USD": Decimal("0.5")},
            ),
        ]
    )
    assert _usage(usage) == {
        "tokens_in": None,
        "tokens_out": None,
        "cost_usd": None,
        "cost": {"EUR": "1.25", "USD": "0.5"},
    }


def test_real_public_runtime_refuses_missing_credentials_without_turn(tmp_path):
    pytest.importorskip("amplifier_agent")
    program = """
import asyncio, pathlib
import amplifier_agent as a
async def main():
    try:
        await a.create_agent(a.AgentOptions(
            provider="anthropic", model="claude-sonnet-4-6", tools=[],
            skills=[], mcp_servers=[], approvals="deny", tool_error_policy="stop",
            working_directory=".", sessions_directory=pathlib.Path("sessions"),
        ))
    except a.AgentError as error:
        assert "connection is not configured" in error.message, error
    else:
        raise AssertionError("uncredentialled agent was accepted")
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=tmp_path,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_an_unknown_cost_entry_does_not_become_a_partial_total():
    api = pytest.importorskip("amplifier_agent")
    usage = api.Usage(
        entries=[
            api.UsageEntry(provider="anthropic", model="a", cost={"USD": Decimal("0.5")}),
            api.UsageEntry(provider="anthropic", model="a", cost=None),
        ]
    )
    assert _usage(usage)["cost"] is None
    assert _usage(usage)["cost_usd"] is None


@pytest.mark.parametrize("deny", [False, True])
def test_real_runtime_effect_boundaries_without_provider_execution(tmp_path, deny, monkeypatch):
    """Run shipped effect execution and settlement, not a fake Agent/provider.

    Test-only access to the v0.22 engine turn admits one effect directly, skipping
    model selection of a tool. No start_turn/runtime.execute/provider call occurs.
    This tests the real effect boundary, not a model-backed end-to-end turn.
    """
    api = pytest.importorskip("amplifier_agent")
    from amplifier_agent_engine._engine.effects import PolicyStop
    from amplifier_agent_engine._engine.state import EngineTurn
    from amplifier_agent_engine._records import Tool, ToolFailed, TurnInput, TurnResult
    from research_core.engine import (
        LEGACY_ENGINE_HOME_ENV,
        WEB_TOOLS,
        _agent_environment,
        _web_approvals,
    )

    monkeypatch.setenv(LEGACY_ENGINE_HOME_ENV, str(tmp_path / "legacy"))

    invoked = []

    async def fails(arguments, context):
        invoked.append(context.call_id)
        raise ToolFailed("deliberate local failure; no external effect")

    async def scenario():
        # An inert connection value lets construction validate offline. No
        # provider request is made by this test, and it needs no real credential.
        async with _agent_environment():
            agent = await api.create_agent(
                api.AgentOptions(
                    provider="anthropic",
                    model="claude-sonnet-4-6",
                    tools=[],
                    skills=[],
                    mcp_servers=[],
                    approvals=_web_approvals(api, WEB_TOOLS),
                    tool_error_policy="stop",
                    working_directory=tmp_path,
                    sessions_directory=tmp_path / "sessions",
                    environment={"ANTHROPIC_API_KEY": "offline-boundary-no-provider-request"},
                )
            )
        assert LEGACY_ENGINE_HOME_ENV in __import__("os").environ
        async with (
            agent,
            await agent.create_session(api.SessionOptions(persistence="ephemeral")) as session,
        ):
            target = session._port._target
            # Use the same approval handler bridged by actual Agent construction.
            # It is already converted to engine records on this config.
            assert callable(target.agent.config.approvals)
            turn = EngineTurn(target, TurnInput(content=[]), "claude-sonnet-4-6")
            with pytest.raises(PolicyStop):
                await turn.call_tool(
                    Tool(
                        "local_failure" if deny else "web_fetch",
                        "Fails locally",
                        {"type": "object"},
                        fails,
                    ),
                    "local-call",
                    {},
                )
            await turn._finish(TurnResult("success"))
            events = [event async for event in turn.events()]
            assert [e.type for e in events] == [
                "tool_call",
                "approval_request",
                "approval_decision",
                "tool_result",
                "terminal",
            ]
            assert events[-1].payload.state == ("rejected" if deny else "failure")
            assert events[-1].payload.error.code == ("approval_denied" if deny else "tool_failed")
            assert events[-2].payload.resolution.outcome == ("cancelled" if deny else "failed")
            assert invoked == ([] if deny else ["local-call"])
            display = _Display(None)
            for event in events:
                await display.emit(decode(encode(event), api))
            assert display.tool_calls == 1
            assert display.tool_successes == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("tool", ["deep-research", "fact-check"])
@pytest.mark.parametrize("flag", ["-V", "--version"])
def test_cli_version_is_package_metadata_without_credentials(tmp_path, tool, flag):
    from importlib.metadata import version

    result = subprocess.run(
        [sys.executable, "-m", tool.replace("-", "_") + ".cli", flag],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == version(tool)
    assert result.stderr == ""


async def record():
    import amplifier_agent as api
    from research_core.engine import WEB_TOOLS, _run_turn_async, _turn_workspace

    events = []
    approvals = []

    async def approve(request):
        approvals.append(request.name)
        return api.ApprovalResponse(decision="allow" if request.name in WEB_TOOLS else "deny")

    prompt = (
        "Use web_fetch once to read "
        "https://raw.githubusercontent.com/microsoft/amplifier-agent/v0.22.0/docs/python/reference.md "
        "and report the name of the agent factory. Do not search. "
        'Return only JSON: {"findings": "your finding with [1]", '
        '"sources": [{"url": "the URL fetched", "title": "Python reference"}], '
        '"confidence": "high"}.'
    )
    with _turn_workspace() as cwd:
        async with (
            await api.create_agent(
                api.AgentOptions(
                    provider="anthropic",
                    model="claude-sonnet-4-6",
                    tools=list(WEB_TOOLS),
                    approvals=approve,
                    tool_error_policy="stop",
                    working_directory=cwd,
                    sessions_directory=Path(cwd) / "sessions",
                    skills=[],
                    mcp_servers=[],
                )
            ) as agent,
            await agent.create_session(api.SessionOptions(persistence="ephemeral")) as session,
        ):
            turn = await session.start_turn(api.TurnInput(content=[api.TextPart(prompt)]))
            async for event in turn.events():
                events.append(encode(event))
    terminal = decode(events[-1], api)
    assert terminal.type == "terminal" and terminal.payload.state == "success"
    zero = await _run_turn_async(
        'Do not call any tools. Return only JSON: {"findings": "create_agent is the '
        'factory [1]", "sources": [{"url": '
        '"https://raw.githubusercontent.com/microsoft/amplifier-agent/v0.22.0/docs/python/reference.md", '
        '"title": "Python reference"}], "confidence": "high"}.',
        provider="anthropic",
        model="claude-sonnet-4-6",
        tools=WEB_TOOLS,
    )
    assert zero.tool_calls == 0
    FIXTURE.parent.mkdir(exist_ok=True)
    FIXTURE.write_text(
        json.dumps(
            {
                "recorded_at": datetime.now().astimezone().isoformat(),
                "version": api.__version__,
                "tag_commit": "915edf9372312d4c8244df4b2b16b094cf455cff",
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "prompt": prompt,
                "approvals": approvals,
                "tool_calls": sum(e["type"] == "tool_call" for e in events),
                "usage": _usage(terminal.payload.usage),
                "zero_tool_result": dataclasses.asdict(zero),
                "gather_result": {
                    "text": "".join(part.text for part in (terminal.payload.content or [])),
                    "usage": _usage(terminal.payload.usage),
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-6",
                    "tool_calls": sum(e["type"] == "tool_call" for e in events),
                },
                "events": events,
            },
            indent=2,
        )
        + "\n"
    )


@pytest.mark.parametrize("threads", [False, True])
def test_overlapping_real_construction_serializes_legacy_environment(
    tmp_path, monkeypatch, threads
):
    import os
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from research_core.engine import LEGACY_ENGINE_HOME_ENV, _agent_environment

    api = pytest.importorskip("amplifier_agent")
    monkeypatch.setenv(LEGACY_ENGINE_HOME_ENV, str(tmp_path / "legacy"))
    inside = 0
    gate = threading.Lock()

    async def construct(index):
        nonlocal inside
        async with _agent_environment():
            with gate:
                inside += 1
                assert inside == 1
            assert LEGACY_ENGINE_HOME_ENV not in os.environ
            # Deliberately yield while construction compatibility is active.
            await asyncio.sleep(0.03)
            async with await api.create_agent(
                api.AgentOptions(
                    provider="anthropic",
                    model="claude-sonnet-4-6",
                    tools=[],
                    approvals="deny",
                    working_directory=tmp_path,
                    sessions_directory=tmp_path / str(index),
                    environment={"ANTHROPIC_API_KEY": "offline-no-provider-request"},
                )
            ):
                assert LEGACY_ENGINE_HOME_ENV not in os.environ
                await asyncio.sleep(0.03)
            with gate:
                inside -= 1

    if threads:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(asyncio.run, construct(i)) for i in range(2)]
            for future in futures:
                future.result(timeout=30)
    else:

        async def overlap():
            await asyncio.gather(construct(0), construct(1))

        asyncio.run(overlap())
    assert os.environ[LEGACY_ENGINE_HOME_ENV] == str(tmp_path / "legacy")


def test_final_writer_and_stage_retries_preserve_unknown_currency_usage(tmp_path):
    from research_core.staging import Attempt, StageResult
    from research_core.writer import RunWriter

    usd = {"tokens_in": 10, "tokens_out": 5, "cost_usd": "1.25", "cost": {"USD": "1.25"}}
    eur = {"tokens_in": None, "tokens_out": 7, "cost_usd": None, "cost": {"EUR": "2.50"}}
    stage = StageResult(None, [Attempt(1, False, usage=usd), Attempt(2, True, usage=eur)])
    writer = RunWriter(
        runs_dir=tmp_path,
        run_id="dr-usage",
        tool="deep-research",
        query="test",
        depth="low",
        backend="agent",
        stages=(),
        quiet=True,
    )
    writer.record_usage(usd)
    writer.record_usage(stage.usage)
    writer.complete()
    usage = json.loads((writer.path / "run.json").read_text())["usage"]
    assert usage["tokens_in"] is None
    assert usage["cost_usd"] is None
    assert usage["cost"] == {"USD": "2.50", "EUR": "2.50"}
    assert usage["complete"]["tokens_in"] is False
    assert usage["known_subtotals"]["tokens_in"] == 20


@pytest.mark.parametrize("provider", ["openai", "azure-openai", "gemini"])
def test_nondefault_provider_without_model_refuses_actionably(provider):
    from research_core.engine import EngineUnavailable, _validate_model_selection

    with pytest.raises(EngineUnavailable) as refused:
        _validate_model_selection(provider, None)
    assert provider in refused.value.message
    assert "RESEARCH_MODEL" in refused.value.remedy
    assert "alongside provider" in refused.value.remedy


@pytest.mark.parametrize(
    "provider,model,effort",
    [("anthropic", None, None), ("openai", "gpt-4.1", "none")],
)
def test_scoped_model_policy_with_real_construction(tmp_path, provider, model, effort):
    api = pytest.importorskip("amplifier_agent")
    from research_core.engine import _agent_environment, _validate_model_selection

    _validate_model_selection(provider, model)

    async def scenario():
        async with _agent_environment():
            agent = await api.create_agent(
                api.AgentOptions(
                    provider=provider,
                    model=model,
                    reasoning_effort=effort,
                    tools=[],
                    skills=[],
                    mcp_servers=[],
                    approvals="deny",
                    working_directory=tmp_path,
                    sessions_directory=tmp_path / "sessions",
                    environment={
                        "ANTHROPIC_API_KEY": "offline-no-provider-request",
                        "OPENAI_API_KEY": "offline-no-provider-request",
                    },
                )
            )
        async with (
            agent,
            await agent.create_session(api.SessionOptions(persistence="ephemeral")) as session,
        ):
            assert session.info.provider == provider
            if model is not None:
                assert session.info.model == model
                assert session.info.reasoning_effort == effort
            else:
                assert session.info.model  # resolved upstream, not invented here

    asyncio.run(scenario())


if __name__ == "__main__" and "--record" in sys.argv:
    asyncio.run(record())
