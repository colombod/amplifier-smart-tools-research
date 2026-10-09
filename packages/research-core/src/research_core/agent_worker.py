"""One owned executable Agent turn. stdout is private NDJSON, stderr diagnostic."""

from __future__ import annotations

import asyncio
import contextlib
import json
import signal
import sys
from dataclasses import asdict

from research_core.engine import _run_turn_local


def main():
    request = json.loads(sys.stdin.readline())
    protocol = sys.stdout

    def send(kind, **fields):
        protocol.write(json.dumps({"type": kind, **fields}) + "\n")
        protocol.flush()

    async def execute():
        task = asyncio.create_task(
            _run_turn_local(**request, on_event=lambda event: send("event", event=event))
        )
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
        try:
            result = await task
        except BaseException as error:
            send(
                "error",
                message=str(error),
                remedy=getattr(error, "remedy", "Inspect Agent runtime."),
            )
        else:
            send("result", result=asdict(result))
            send("settled")
        # Local turn returns only after its context-managed session and agent
        # closes. Runner finalization still must exit before parent can delete.

    with contextlib.redirect_stdout(sys.stderr):
        asyncio.run(execute())


if __name__ == "__main__":
    main()
