"""Actual executable Agent boundary, no inference/network or fake Agent."""

import asyncio
import os
import sys
import time

import pytest
from research_core import engine


@pytest.mark.parametrize(
    "case", ["timeout_callback", "second_cancel", "resistant", "production_grace"]
)
def test_process_cleanup_adverse_states(tmp_path, monkeypatch, case):
    pytest.importorskip("amplifier_agent")
    monkeypatch.setenv("RESEARCH_CONFIG", str(tmp_path / "absent.toml"))
    monkeypatch.setenv("RESEARCH_ENGINE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-not-a-key")
    if case != "production_grace":
        monkeypatch.setattr(engine, "SHUTDOWN_SECONDS", 0.2)
    harness = tmp_path / "worker.py"
    trace = tmp_path / "trace"
    acknowledgement = tmp_path / "callback-ack"
    harness.write_text("""
import asyncio, json, socket, sys
from pathlib import Path
import amplifier_agent as api
from research_core import agent_worker
case = sys.argv[1]
def forbidden(*a, **kw):
    raise AssertionError("network forbidden")
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
original = api.Session.start_turn
async def start(self, value):
    turn = await original(self, value)
    Path(sys.argv[2]).write_text("real Agent session started")
    if case == "timeout_callback":
        # Test-only protocol readiness, after real Agent/session construction.
        # Not a model event or evidence of successful inference.
        sys.__stdout__.write(json.dumps({"type": "event", "event": {
            "type": "progress", "message": "callback-ready"
        }}) + "\\n")
        sys.__stdout__.flush()
        while not Path(sys.argv[3]).exists():
            await asyncio.sleep(0.01)
    return turn
api.Session.start_turn = start
if case == "timeout_callback":
    original_close = api.Session.close
    async def delayed_close(self):
        await asyncio.sleep(3)
        return await original_close(self)
    api.Session.close = delayed_close
if case in ("resistant", "production_grace"):
    original_close = api.Session.close
    async def close(self):
        Path(sys.argv[2]).write_text("real Agent close resistant")
        while True:
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                pass
    api.Session.close = close
agent_worker.main()
""")
    observations = []
    clock_offset = 0.0

    def callback(event):
        nonlocal clock_offset
        paths = list((tmp_path / "home" / "work").glob("turn-*"))
        assert paths and all(p.exists() for p in paths)
        observations.append(event)
        if case == "timeout_callback":
            assert event["message"] == "callback-ready"
            acknowledgement.touch()
            # Advance only the parent's existing monotonic seam after readiness;
            # no production hook and no guessed startup sleep.
            clock_offset = 31.0
            raise ValueError("presentation failed")

    async def scenario():
        if case == "timeout_callback":
            loop = asyncio.get_running_loop()
            original_time = loop.time
            monkeypatch.setattr(loop, "time", lambda: original_time() + clock_offset)
        task = asyncio.create_task(
            engine._run_turn_async(
                "No inference allowed",
                provider="anthropic",
                timeout_ms=30_000 if case == "timeout_callback" else 2000,
                on_event=callback,
                _worker_command=[
                    sys.executable,
                    str(harness),
                    case,
                    str(trace),
                    str(acknowledgement),
                ],
            )
        )
        if case == "second_cancel":
            while not trace.exists():
                await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0.03)
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            assert case == "second_cancel"
        except engine.EngineUnavailable as error:
            assert case != "second_cancel"
            assert "exceeded" in str(error)
            if case == "timeout_callback":
                notes = getattr(error, "__notes__", [])
                assert observations
                assert observations[0]["message"] == "callback-ready"
                assert acknowledgement.exists()
                assert any("Presentation error: ValueError" in note for note in notes)
        else:
            pytest.fail("adverse turn accepted")
        count = len(observations)
        await asyncio.sleep(0.05)
        assert len(observations) == count
        assert not [
            t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()
        ]

    started = time.monotonic()
    asyncio.run(scenario())
    elapsed = time.monotonic() - started
    assert elapsed < (35 if case == "production_grace" else 6)
    if case == "production_grace":
        assert elapsed >= 30
    assert trace.exists(), "real Agent construction/start was not reached"
    if case in ("resistant", "production_grace"):
        assert trace.read_text() == "real Agent close resistant"
    # Retained conservatively: no graceful settlement receipt on interrupted turns.
    assert list((tmp_path / "home" / "work").glob("turn-*"))


@pytest.mark.parametrize("case", ["exit7", "nonreader", "brokenpipe", "launch"])
def test_executable_protocol_and_delivery_failures(tmp_path, monkeypatch, case):
    """Protocol harnesses test transport only; never evidence of Agent success."""
    monkeypatch.setenv("RESEARCH_CONFIG", str(tmp_path / "absent.toml"))
    monkeypatch.setenv("RESEARCH_ENGINE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(engine, "SHUTDOWN_SECONDS", 0.1)
    pid_file = tmp_path / "pid"
    harness = tmp_path / "transport.py"
    harness.write_text("""
import json, os, signal, subprocess, sys, time
open(sys.argv[2], "w").write(str(os.getpid()))
case = sys.argv[1]
if case == "exit7":
    sys.stdin.readline()
    print(json.dumps({"type":"result","result":{"text":"NOT AN AGENT RESULT"}}), flush=True)
    print(json.dumps({"type":"settled"}), flush=True)
    sys.exit(7)
if case == "brokenpipe":
    sys.stdin.close()
    os.close(0)
    time.sleep(0.2)
    sys.exit(3)
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(100)"])
def cancel(signum, frame):
    child.terminate()
    child.wait(timeout=1)
signal.signal(signal.SIGTERM, cancel)
time.sleep(100)
""")
    command = (
        [str(tmp_path / "missing-executable")]
        if case == "launch"
        else [sys.executable, str(harness), case, str(pid_file)]
    )
    start = time.monotonic()
    with pytest.raises(engine.EngineUnavailable) as refused:
        asyncio.run(
            engine._run_turn_async(
                "x" * (2_000_000 if case in ("nonreader", "brokenpipe") else 1),
                timeout_ms=500,
                _worker_command=command,
            )
        )
    assert time.monotonic() - start < 3
    if case == "exit7":
        assert "status 7" in str(refused.value)
    assert list((tmp_path / "home" / "work").glob("turn-*"))
    if pid_file.exists():
        with pytest.raises(ProcessLookupError):
            os.killpg(int(pid_file.read_text()), 0)
