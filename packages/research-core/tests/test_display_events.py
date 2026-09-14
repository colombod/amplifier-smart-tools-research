"""_Display, driven with the engine's real event shapes -- no model, no credential.

The engine's ``DisplaySystem`` protocol point is exactly one async method,
``emit(event)`` (see ``amplifier_agent_lib.protocol_points.base.DisplaySystem``,
and the shipped ``CliDisplaySystem`` -- both implement nothing wider). So a
missing-events symptom cannot be an interface mismatch; if it ever recurs, look
at whether the tool that ran was dispatched through the kernel's tool registry
at all (``tool:pre``/``tool:post`` only fire for THAT path -- a provider's own
server-side tool, e.g. Anthropic's ``web_search_20250305`` when
``enable_web_search`` is set, never reaches it) before touching this file again.

Two layers of evidence here:

* ``Test*DirectlyDriven`` -- feeds ``_Display.emit`` the exact dict shapes the
  installed ``bundle/hook_streaming.py`` constructs (read from its source, not
  invented), and asserts what gets forwarded to ``on_event``.
* ``test_full_wiring_*`` -- mounts the REAL shipped streaming hook onto a REAL
  Rust-backed coordinator (``amplifier_core.testing.create_test_coordinator``,
  the same compiled ``HookRegistry`` production uses), wraps our ``_Display``
  in the REAL ``UsageAccumulator`` exactly as ``Engine.__init__`` does, and
  registers it as the ``display.emit`` capability exactly as
  ``amplifier_agent_lib._runtime.make_turn_handler`` does. Then fires
  ``tool:pre`` / ``tool:post`` / ``llm:response`` through ``coordinator.hooks``
  -- the same object identity the real orchestrator is handed
  (``amplifier_core._session_exec.run_orchestrator`` passes
  ``hooks = coordinator.hooks`` straight through). This is the strongest
  offline proof available that engine events reach our display object.
"""

from __future__ import annotations

import asyncio

import pytest
from research_core.engine import _Display

amplifier_agent_lib = pytest.importorskip("amplifier_agent_lib")
amplifier_core = pytest.importorskip("amplifier_core")


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Layer 1: _Display driven directly with real event shapes
# ---------------------------------------------------------------------------


def test_tool_started_and_completed_are_forwarded():
    forwarded = []
    display = _Display(forwarded.append)

    # Shapes exactly as amplifier_agent_lib/bundle/hook_streaming.py's
    # on_tool_pre / on_tool_post construct them.
    run(
        display.emit(
            {
                "type": "tool/started",
                "sessionId": "s1",
                "turnId": "t1",
                "toolCallId": "c1",
                "name": "web_search",
                "args": {"query": "zig 0.1.0"},
            }
        )
    )
    run(
        display.emit(
            {
                "type": "tool/completed",
                "sessionId": "s1",
                "turnId": "t1",
                "toolCallId": "c1",
                "name": "web_search",
                "result": {"ok": True},
                "durationMs": 842,
            }
        )
    )

    assert forwarded == [
        {"type": "tool", "name": "web_search", "status": "started", "duration_ms": None},
        {"type": "tool", "name": "web_search", "status": "complete", "duration_ms": 842},
    ]


def test_progress_and_error_are_forwarded():
    forwarded = []
    display = _Display(forwarded.append)

    run(
        display.emit({"type": "progress", "sessionId": "s1", "turnId": "t1", "message": "thinking"})
    )
    run(
        display.emit(
            {
                "type": "error",
                "sessionId": "s1",
                "turnId": "t1",
                "code": "tool_failed",
                "message": "boom",
                "recoverable": True,
            }
        )
    )

    assert forwarded == [
        {"type": "progress", "message": "thinking"},
        {"type": "engine_error", "message": "boom"},
    ]


def test_usage_is_forwarded_and_tracked():
    # Shape exactly as hook_streaming.py's on_llm_response constructs it.
    forwarded = []
    display = _Display(forwarded.append)

    run(
        display.emit(
            {
                "type": "usage",
                "sessionId": "s1",
                "turnId": "t1",
                "inputTokens": 120,
                "outputTokens": 40,
                "cost": "0.0031",
            }
        )
    )

    # Forwarded to the caller (the defect this test guards: usage used to be
    # tracked into self.usage and NEVER handed to on_event).
    assert forwarded == [
        {"type": "usage", "tokens_in": 120, "tokens_out": 40, "cost_usd": "0.0031"}
    ]
    # And still tracked on the instance, unchanged behaviour.
    assert display.usage == {"tokens_in": 120, "tokens_out": 40, "cost_usd": "0.0031"}


def test_usage_with_no_cost_forwards_none():
    forwarded = []
    display = _Display(forwarded.append)

    run(
        display.emit(
            {
                "type": "usage",
                "sessionId": "s1",
                "turnId": "t1",
                "inputTokens": 5,
                "outputTokens": 1,
            }
        )
    )

    assert forwarded == [{"type": "usage", "tokens_in": 5, "tokens_out": 1, "cost_usd": None}]


@pytest.mark.parametrize(
    "kind",
    ["result/delta", "result/final", "thinking/delta", "thinking/final", "session:start", ""],
)
def test_unclaimed_event_types_are_dropped_without_raising(kind):
    forwarded = []
    display = _Display(forwarded.append)

    run(display.emit({"type": kind, "sessionId": "s1", "turnId": "t1", "text": "irrelevant"}))

    assert forwarded == []


def test_no_on_event_callback_does_not_raise():
    display = _Display(None)
    run(display.emit({"type": "tool/started", "name": "x"}))
    run(display.emit({"type": "usage", "inputTokens": 1, "outputTokens": 1}))
    # Usage is still tracked even with no consumer.
    assert display.usage == {"tokens_in": 1, "tokens_out": 1, "cost_usd": None}


# ---------------------------------------------------------------------------
# Layer 2: the real Rust hook registry + the real shipped streaming hook +
# the real UsageAccumulator, wired exactly as production code wires them.
# ---------------------------------------------------------------------------


def test_full_wiring_delivers_tool_events_through_the_real_hook_registry():
    from amplifier_agent_lib.bundle.hook_streaming import mount as mount_streaming_hook
    from amplifier_agent_lib.protocol_points.usage_accumulator import UsageAccumulator
    from amplifier_core.testing import create_test_coordinator

    forwarded = []
    display = _Display(forwarded.append)
    # Exactly what Engine.__init__ does to the display protocol point.
    usage = UsageAccumulator(display)

    coordinator = create_test_coordinator()
    # Exactly what _runtime.py's make_turn_handler does per turn.
    coordinator.register_capability("display.emit", usage.emit)

    async def scenario():
        await mount_streaming_hook(coordinator, {})
        # Exactly the payload shape amplifier_module_loop_streaming's
        # _execute_tool_with_result / _execute_tool_only send to hooks.emit
        # (session_id/turn_id are NOT among its keys -- confirmed by reading
        # that module's source; hook_streaming.py defaults them to "").
        await coordinator.hooks.emit(
            "tool:pre",
            {
                "tool_name": "web_search",
                "tool_call_id": "c1",
                "tool_input": {"query": "zig 0.1.0"},
            },
        )
        await coordinator.hooks.emit(
            "tool:post",
            {
                "tool_name": "web_search",
                "tool_call_id": "c1",
                "tool_input": {"query": "zig 0.1.0"},
                "result": {"success": True},
                "duration_ms": 750,
            },
        )

    run(scenario())

    assert forwarded == [
        {"type": "tool", "name": "web_search", "status": "started", "duration_ms": None},
        {"type": "tool", "name": "web_search", "status": "complete", "duration_ms": 750},
    ]


def test_full_wiring_delivers_usage_through_the_real_hook_registry():
    from amplifier_agent_lib.bundle.hook_streaming import mount as mount_streaming_hook
    from amplifier_agent_lib.protocol_points.usage_accumulator import UsageAccumulator
    from amplifier_core.testing import create_test_coordinator

    forwarded = []
    display = _Display(forwarded.append)
    usage = UsageAccumulator(display)

    coordinator = create_test_coordinator()
    coordinator.register_capability("display.emit", usage.emit)

    async def scenario():
        await mount_streaming_hook(coordinator, {})
        await coordinator.hooks.emit(
            "llm:response",
            {
                "session_id": "s1",
                "turn_id": "t1",
                "usage": {"input_tokens": 200, "output_tokens": 50, "cost_usd": "0.0042"},
            },
        )

    run(scenario())

    usage_events = [e for e in forwarded if e["type"] == "usage"]
    assert usage_events == [
        {"type": "usage", "tokens_in": 200, "tokens_out": 50, "cost_usd": "0.0042"}
    ]
    # UsageAccumulator itself also summed it, independent of our display.
    assert usage.gross_input == 200
    assert usage.output_tokens == 50
