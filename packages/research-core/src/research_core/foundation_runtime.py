"""Installed public Core/Foundation adapter; no agent implementation imports.

Source-less declarations resolve installed entry points. Nothing downloads a
bundle or installs modules during a research turn. Credentials are read only;
existing agent credential/OAuth locations are retained, never migrated.
"""

from __future__ import annotations

import importlib.util
import json
import os
from decimal import Decimal
from pathlib import Path

from research_core.errors import NoProviderError

PROVIDER_ENV = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "azure-openai": ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_KEY"),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "github-copilot": ("COPILOT_AGENT_TOKEN", "COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"),
    "ollama": ("OLLAMA_HOST", "OLLAMA_BASE_URL"),
    "chat-completions": ("CHAT_COMPLETIONS_BASE_URL",),
    "vllm": ("VLLM_BASE_URL",),
    "openai-chatgpt": (),
}


def _saved(home: Path) -> dict:
    path = home / "credentials.json"
    if not path.exists():
        return {}
    try:
        if path.stat().st_size > 256_000:
            raise ValueError("oversize")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("shape")
        providers = (
            value.get("providers")
            if "providers" in value
            else {
                key: entry if isinstance(entry, dict) else {"api_key": str(entry)}
                for key, entry in value.items()
            }
        )
        if not isinstance(providers, dict):
            raise ValueError("shape")
        return providers
    except (OSError, ValueError, TypeError, AttributeError):
        raise NoProviderError(
            "The retained agent credentials file is unreadable or invalid.",
            "Repair credentials.json under engine_home, or select a provider "
            "with an explicit environment credential.",
        ) from None


def provider_config(provider: str, home: Path) -> dict | None:
    """Environment first, then retained v1/legacy agent credentials; no output secrets."""
    if provider not in PROVIDER_ENV:
        return None
    if provider == "openai-chatgpt":
        try:
            from amplifier_module_provider_openai_chatgpt.oauth import load_tokens
        except ImportError:
            return None
        path = home / "state" / "openai-chatgpt-oauth.json"
        tokens = load_tokens(str(path))
        if not tokens or not (tokens.get("access_token") or tokens.get("refresh_token")):
            return None
        return {"token_file_path": str(path), "login_on_mount": False}
    value = next((os.environ[k] for k in PROVIDER_ENV[provider] if os.environ.get(k)), None)
    field = (
        "host"
        if provider == "ollama"
        else "base_url"
        if provider in {"chat-completions", "vllm"}
        else "api_key"
    )
    saved = {} if value else _saved(home).get(provider, {})
    saved = saved if isinstance(saved, dict) else {}
    value = value or saved.get(field)
    if not isinstance(value, str) or not value:
        return None
    config = {"github_token" if provider == "github-copilot" else field: value}
    if provider == "azure-openai":
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT") or os.environ.get(
            "AZURE_OPENAI_BASE_URL"
        )
        if not endpoint:
            retained = _saved(home).get(provider, {})
            endpoint = retained.get("endpoint") if isinstance(retained, dict) else None
        if endpoint:
            config["azure_endpoint"] = endpoint
    if provider in {"chat-completions", "vllm"}:
        key = os.environ.get(
            "CHAT_COMPLETIONS_API_KEY" if provider == "chat-completions" else "VLLM_API_KEY"
        )
        if key:
            config["api_key"] = key
    # Keep provider-owned auxiliary state inside the configured engine home.
    if provider == "github-copilot":
        config["rate_limit_state_path"] = str(home / "state" / "rate-limit-state.json")
    return config


def configured_providers(home: Path) -> list[str]:
    found, errors = [], []
    for name in PROVIDER_ENV:
        try:
            if provider_config(name, home) is not None:
                found.append(name)
        except NoProviderError as error:
            errors.append(error)
    # A broken unrelated saved file must not hide a usable environment binding.
    # Retain the safe diagnostic when no provider can be selected.
    if not found and errors:
        raise errors[0]
    return found


def runtime_present(provider: str) -> bool:
    modules = [
        "amplifier_core",
        "amplifier_foundation",
        "amplifier_module_loop_streaming",
        "amplifier_module_context_simple",
        "amplifier_module_provider_" + provider.replace("-", "_"),
    ]
    try:
        return all(importlib.util.find_spec(name) is not None for name in modules)
    except (ImportError, ValueError):
        return False


class DenyApprovals:
    async def request_approval(self, prompt, options, timeout, default):
        return "deny"


class Events:
    def __init__(self, display, cwd, tools):
        self.display, self.cwd, self.tools = display, Path(cwd).resolve(), set(tools)
        self.tokens_in = self.tokens_out = 0
        self.cost = Decimal(0)
        self.known_cost = False
        self.missing_cost = False

    async def handle(self, event, data):
        from amplifier_core import HookResult

        name = data.get("tool_name")
        if event == "tool:pre":
            arguments = data.get("tool_input") or data.get("arguments") or {}
            target = arguments.get("save_to_file") if isinstance(arguments, dict) else None
            unsafe_target = target is not None and (
                not isinstance(target, str)
                or not (self.cwd / target).resolve().is_relative_to(self.cwd)
            )
            if name not in self.tools or not isinstance(arguments, dict) or unsafe_target:
                return HookResult(
                    action="deny",
                    reason="Research only permits selected web tools "
                    "and writes inside its turn directory.",
                )
            await self.display.emit({"type": "tool/started", "name": name})
        elif event == "tool:post":
            await self.display.emit(
                {"type": "tool/completed", "name": name, "durationMs": data.get("duration_ms")}
            )
        elif event == "llm:response":
            usage = data.get("usage") or {}
            inputs = int(data.get("input_tokens") or usage.get("input_tokens") or 0)
            outputs = int(data.get("output_tokens") or usage.get("output_tokens") or 0)
            # Existing TurnResult.tokens_in reports charged input: fresh input
            # plus cache writes; cache reads are not charged again as fresh input.
            inputs += int(data.get("cache_write_tokens") or usage.get("cache_write_tokens") or 0)
            self.tokens_in += inputs
            self.tokens_out += outputs
            cost = usage.get("cost_usd")
            if cost is None:
                self.missing_cost = True
            else:
                amount = Decimal(str(cost))
                if not amount.is_finite() or amount < 0:
                    raise ValueError("Invalid provider cost")
                self.cost += amount
                self.known_cost = True
            await self.display.emit(
                {
                    "type": "usage",
                    "inputTokens": inputs,
                    "outputTokens": outputs,
                    "cost": str(cost) if cost is not None else None,
                }
            )
        return HookResult(action="continue")


async def execute(prompt, *, chosen, model, home, cwd, tools, display):
    from amplifier_foundation import Bundle

    from research_core.engine import EngineUnavailable

    if any(name != "tool-web" for name in tools):
        raise EngineUnavailable(
            "An unsupported research tool module was requested.",
            "Use tool-web for gathering, or no tools for reasoning.",
        )
    config = provider_config(chosen, home)
    if config is None:
        raise NoProviderError(
            "The selected provider is not configured.",
            "Configure the selected provider before starting a new run.",
        )
    if model:
        config["default_model"] = model
    if chosen == "openai-chatgpt":
        from amplifier_module_provider_openai_chatgpt import oauth

        path = config["token_file_path"]
        tokens = oauth.load_tokens(path)
        if not oauth.is_token_valid(tokens) and tokens and tokens.get("refresh_token"):
            tokens = await oauth.refresh_tokens(tokens["refresh_token"], path=path)
        if not oauth.is_token_valid(tokens):
            raise NoProviderError(
                "The retained ChatGPT login has expired.",
                "Renew it explicitly using the provider's login flow; research never starts login.",
            )
    bundle = Bundle(
        name="amplifier-research",
        session={
            "orchestrator": {"module": "loop-streaming"},
            "context": {"module": "context-simple"},
        },
        providers=[{"module": "provider-" + chosen, "config": config}],
        tools=[{"module": "tool-web", "config": {"working_dir": cwd}}] if tools else [],
        hooks=[],
        agents={},
    )
    prepared = await bundle.prepare(install_deps=False, cache_dir=home / "cache", strict=True)
    session = await prepared.create_session(session_cwd=Path(cwd), approval_system=DenyApprovals())
    async with session:
        mounted = session.coordinator.get("tools") or {}
        expected = {"web_search", "web_fetch"} if tools else set()
        if set(mounted) != expected or not session.coordinator.get("providers"):
            raise EngineUnavailable(
                "The requested provider or exact web tool set did not mount.",
                "Reinstall the declared runtime dependencies; no model request was sent.",
            )
        events = Events(display, cwd, expected)
        for event in ("tool:pre", "tool:post", "llm:response"):
            session.coordinator.hooks.register(
                event, events.handle, name="research-events", priority=0
            )
        text = await session.execute(prompt)
    return {
        "reply": text,
        "tokensIn": events.tokens_in,
        "tokensOut": events.tokens_out,
        "costUsd": str(events.cost) if events.known_cost and not events.missing_cost else None,
    }
