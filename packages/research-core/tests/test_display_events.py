"""Stable research event DTOs and their public Core hook-registry wiring.

Direct tests need no engine extra. The two registry tests use the installed
Core implementation, without credentials or requests.
"""

from __future__ import annotations

import asyncio

import pytest
from research_core.engine import _Display


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Layer 1: _Display driven directly with real event shapes
# ---------------------------------------------------------------------------


def test_tool_started_and_completed_are_forwarded():
    forwarded = []
    display = _Display(forwarded.append)

    # Stable internal DTOs retained by the new public hook adapter.
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
# Layer 2: installed Core hook registry + research-owned public hook adapter.
# ---------------------------------------------------------------------------


def test_full_wiring_delivers_tool_events_through_the_real_hook_registry(tmp_path):
    pytest.importorskip("amplifier_core")
    from amplifier_core.testing import create_test_coordinator
    from research_core.foundation_runtime import Events

    forwarded = []
    display = _Display(forwarded.append)
    events = Events(display, tmp_path, {"web_search", "web_fetch"})

    coordinator = create_test_coordinator()
    for event in ("tool:pre", "tool:post"):
        coordinator.hooks.register(event, events.handle, name="research-events", priority=0)

    async def scenario():
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


def test_full_wiring_delivers_usage_through_the_real_hook_registry(tmp_path):
    pytest.importorskip("amplifier_core")
    from amplifier_core.testing import create_test_coordinator
    from research_core.foundation_runtime import Events

    forwarded = []
    display = _Display(forwarded.append)
    events = Events(display, tmp_path, set())

    coordinator = create_test_coordinator()
    coordinator.hooks.register("llm:response", events.handle, name="research-events", priority=0)

    async def scenario():
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
    assert events.tokens_in == 200
    assert events.tokens_out == 50
