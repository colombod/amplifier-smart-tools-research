"""Public installed Core/Foundation parity, with no external requests."""

import asyncio
import json
from decimal import Decimal

import pytest
from research_core import engine
from research_core import foundation_runtime as runtime


@pytest.fixture(autouse=True)
def private(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_CONFIG", str(tmp_path / "absent.toml"))
    monkeypatch.setenv("RESEARCH_ENGINE_HOME", str(tmp_path / "engine"))
    monkeypatch.setenv("RESEARCH_CREDENTIALS", str(tmp_path / "credentials.toml"))
    for variables in runtime.PROVIDER_ENV.values():
        for variable in variables:
            monkeypatch.delenv(variable, raising=False)
    return tmp_path


def test_retained_credential_layout_and_environment_precedence(private, monkeypatch):
    home = private / "engine"
    home.mkdir()
    path = home / "credentials.json"
    path.write_text(
        json.dumps({"version": 1, "providers": {"openai": {"api_key": "saved-fixture"}}})
    )
    original = path.read_bytes()
    assert runtime.provider_config("openai", home) == {"api_key": "saved-fixture"}
    monkeypatch.setenv("OPENAI_API_KEY", "environment-fixture")
    assert runtime.provider_config("openai", home) == {"api_key": "environment-fixture"}
    assert path.read_bytes() == original


def test_copilot_mapping_and_no_implicit_local_server(private, monkeypatch):
    home = private / "engine"
    assert runtime.provider_config("ollama", home) is None
    monkeypatch.setenv("COPILOT_AGENT_TOKEN", "fixture")
    config = runtime.provider_config("github-copilot", home)
    assert config["github_token"] == "fixture" and "api_key" not in config
    assert config["rate_limit_state_path"] == str(home / "state/rate-limit-state.json")


def test_guard_denies_foreign_tools_and_external_file_writes(private):
    pytest.importorskip("amplifier_core")
    display = engine._Display(None)
    hook = runtime.Events(display, private, {"web_fetch", "web_search"})

    async def scenario():
        for name, args in [
            ("bash", {}),
            ("web_fetch", {"save_to_file": "../outside"}),
            ("web_fetch", {"save_to_file": ["bad"]}),
            ("web_fetch", ["bad"]),
        ]:
            result = await hook.handle("tool:pre", {"tool_name": name, "tool_input": args})
            assert result.action == "deny"
        assert display.tool_calls == 0
        result = await hook.handle(
            "tool:pre", {"tool_name": "web_fetch", "tool_input": {"url": "https://example.test"}}
        )
        assert result.action == "continue" and display.tool_calls == 1
        assert (
            await runtime.DenyApprovals().request_approval("x", ["allow", "deny"], 1, "allow")
            == "deny"
        )

    asyncio.run(scenario())


def test_usage_sums_calls_and_does_not_invent_missing_cost(private):
    pytest.importorskip("amplifier_core")
    events = runtime.Events(engine._Display(None), private, set())

    async def scenario():
        for cost in ("0.01", "0.02", None):
            await events.handle(
                "llm:response", {"usage": {"input_tokens": 3, "output_tokens": 2, "cost_usd": cost}}
            )

    asyncio.run(scenario())
    assert (events.tokens_in, events.tokens_out, events.cost, events.missing_cost) == (
        9,
        6,
        Decimal("0.03"),
        True,
    )


@pytest.mark.parametrize("gather", [False, True])
def test_actual_installed_mount_and_result(gather, private, monkeypatch):
    pytest.importorskip("amplifier_foundation")
    from amplifier_core import ToolResult
    from amplifier_core.message_models import ChatResponse, TextBlock, ToolCall, Usage
    from amplifier_foundation import Bundle
    from amplifier_module_provider_openai import OpenAIProvider
    from amplifier_module_tool_web import WebSearchTool

    monkeypatch.setenv("OPENAI_API_KEY", "offline-fixture")
    calls, mounts, closed = [], [], []
    real_create = Bundle.prepare

    async def prepare(self, **kwargs):
        assert kwargs == {
            "install_deps": False,
            "cache_dir": private / "engine/cache",
            "strict": True,
        }
        assert self.agents == {} and self.hooks == []
        assert not any("source" in row for row in self.providers + self.tools)
        mounts.append(self)
        return await real_create(self, **kwargs)

    monkeypatch.setattr(Bundle, "prepare", prepare)
    monkeypatch.setattr(OpenAIProvider, "stream", None, raising=False)

    async def complete(self, request, **kwargs):
        calls.append(request)
        await self.coordinator.hooks.emit(
            "llm:response", {"usage": {"input_tokens": 11, "output_tokens": 3, "cost_usd": "0.001"}}
        )
        if gather and len(calls) == 1:
            return ChatResponse(
                content=[],
                tool_calls=[ToolCall(id="one", name="web_search", arguments={"query": "fixture"})],
                usage=Usage(input_tokens=11, output_tokens=3, total_tokens=14),
            )
        return ChatResponse(
            content=[TextBlock(text="offline reply")],
            usage=Usage(input_tokens=11, output_tokens=3, total_tokens=14),
        )

    async def search(self, args):
        return ToolResult(success=True, output="fixture evidence")

    monkeypatch.setattr(OpenAIProvider, "complete", complete)
    monkeypatch.setattr(WebSearchTool, "execute", search)
    from amplifier_core import AmplifierSession

    real_exit = AmplifierSession.__aexit__

    async def leave(self, *args):
        result = await real_exit(self, *args)
        closed.append(self.session_id)
        return result

    monkeypatch.setattr(AmplifierSession, "__aexit__", leave)
    result = engine.run_turn(
        "fixture",
        provider="openai",
        model="fixture-model",
        tools=engine.WEB_TOOLS if gather else (),
    )
    assert result.text == "offline reply"
    assert result.tool_calls == int(gather)
    assert result.usage["tokens_in"] == 11 * len(calls)
    assert Decimal(result.usage["cost_usd"]) == Decimal("0.001") * len(calls)
    assert result.model == "fixture-model" and len(closed) == 1
    assert mounts[0].providers[0]["config"]["default_model"] == "fixture-model"
    assert len(mounts[0].tools) == int(gather)
    assert not list((private / "engine/work").iterdir())


def test_timeout_joins_session_cleanup_and_preserves_home(private, monkeypatch):
    async def execute(*args, **kwargs):
        try:
            await asyncio.sleep(100)
        finally:
            (private / "cleaned").touch()

    monkeypatch.setattr(
        engine,
        "_load",
        lambda: {"enumerate_resolvable_providers": lambda: ["openai"], "execute": execute},
    )
    with pytest.raises(engine.EngineUnavailable, match="exceeded"):
        engine.run_turn("fixture", timeout_ms=1)
    assert (private / "cleaned").exists()
    assert not list((private / "engine/work").iterdir())


def test_saved_azure_endpoint_uses_current_public_mount_field(private, monkeypatch):
    home = private / "engine"
    home.mkdir()
    (home / "credentials.json").write_text(
        json.dumps(
            {
                "version": 1,
                "providers": {
                    "azure-openai": {"api_key": "fixture", "endpoint": "https://fixture.invalid"}
                },
            }
        )
    )
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_BASE_URL", raising=False)
    assert runtime.provider_config("azure-openai", home) == {
        "api_key": "fixture",
        "azure_endpoint": "https://fixture.invalid",
    }


def test_actual_cancel_closes_web_session_and_never_downloads(private, monkeypatch):
    pytest.importorskip("amplifier_foundation")
    import amplifier_module_tool_web as web
    from amplifier_foundation.modules.activator import ModuleActivator
    from amplifier_module_provider_openai import OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "offline-fixture")
    monkeypatch.setattr(OpenAIProvider, "stream", None, raising=False)
    clients, cancelled = [], []
    actual_mount = web.mount

    async def mount(coordinator, config):
        cleanup = await actual_mount(coordinator, config)

        async def close():
            await cleanup()
            clients.append("closed")

        return close

    async def forbidden(*args, **kwargs):
        pytest.fail("Installed source-less runtime attempted code activation")

    async def complete(self, request, **kwargs):
        try:
            await asyncio.sleep(100)
        finally:
            cancelled.append(True)

    monkeypatch.setattr(web, "mount", mount)
    monkeypatch.setattr(ModuleActivator, "activate", forbidden)
    monkeypatch.setattr(OpenAIProvider, "complete", complete)
    with pytest.raises(engine.EngineUnavailable, match="exceeded"):
        engine.run_turn("fixture", provider="openai", tools=engine.WEB_TOOLS, timeout_ms=1000)
    assert cancelled == [True] and clients == ["closed"]
    assert not list((private / "engine/work").iterdir())


def test_actual_missing_web_mount_refuses_before_provider(private, monkeypatch):
    pytest.importorskip("amplifier_foundation")
    import amplifier_module_tool_web as web
    from amplifier_module_provider_openai import OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "offline-fixture")

    async def absent(*args, **kwargs):
        return None

    async def forbidden(*args, **kwargs):
        pytest.fail("Partial tool mount reached the provider")

    monkeypatch.setattr(web, "mount", absent)
    monkeypatch.setattr(OpenAIProvider, "complete", forbidden)
    monkeypatch.setattr(OpenAIProvider, "stream", forbidden, raising=False)
    with pytest.raises(engine.EngineUnavailable, match="did not mount"):
        engine.run_turn("fixture", provider="openai", tools=engine.WEB_TOOLS)
    assert not list((private / "engine/work").iterdir())


@pytest.mark.parametrize(
    "saved",
    [
        {"openai": "legacy-fixture"},
        {"openai": {"api_key": "legacy-fixture"}},
        {"providers": {"openai": {"api_key": "legacy-fixture"}}},
    ],
)
def test_legacy_credential_shapes_are_read_without_migration(private, saved):
    home = private / "engine"
    home.mkdir()
    path = home / "credentials.json"
    path.write_text(json.dumps(saved))
    before = path.read_bytes()
    assert runtime.provider_config("openai", home) == {"api_key": "legacy-fixture"}
    assert runtime.configured_providers(home) == ["openai"]
    assert path.read_bytes() == before


def test_environment_binding_survives_broken_unrelated_saved_file(private, monkeypatch):
    home = private / "engine"
    home.mkdir()
    path = home / "credentials.json"
    path.write_text("malformed-fixture")
    monkeypatch.setenv("OPENAI_API_KEY", "explicit-fixture")
    assert "openai" in runtime.configured_providers(home)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-fixture")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://fixture.invalid")
    assert "azure-openai" in runtime.configured_providers(home)
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY")
    with pytest.raises(runtime.NoProviderError, match="unreadable or invalid"):
        runtime.configured_providers(home)
    assert path.read_text() == "malformed-fixture"


def test_cached_usage_preserves_existing_charged_input_semantics(private):
    pytest.importorskip("amplifier_core")
    forwarded = []
    events = runtime.Events(engine._Display(forwarded.append), private, set())

    async def scenario():
        await events.handle(
            "llm:response",
            {
                "usage": {
                    "input_tokens": 3,
                    "cache_write_tokens": 45320,
                    "cache_read_tokens": 500,
                    "output_tokens": 2,
                    "cost_usd": "0.2",
                }
            },
        )
        await events.handle(
            "llm:response",
            {
                "usage": {
                    "input_tokens": 4,
                    "cache_read_tokens": 1000,
                    "output_tokens": 1,
                    "cost_usd": "0.1",
                }
            },
        )

    asyncio.run(scenario())
    assert events.tokens_in == 45327 and events.tokens_out == 3
    assert forwarded[0]["tokens_in"] == 45323
    assert events.cost == Decimal("0.3")
