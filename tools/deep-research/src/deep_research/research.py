"""The research run: the stages, and the artifact they leave behind.

Four stages, and each one is a turn or a backend call bracketed by deterministic
code. At this version `scope` and `synthesise` pass the backend's own findings
through; the reasoning turns that make them do real work arrive with the agent
backend. The stage structure is here now because it is what the progress record,
the run artifact and the failure semantics are built on -- not because the stages
are all doing their final job yet.

Nothing in this module imports an agent engine at module level, and nothing here
runs at import time.
"""

from __future__ import annotations

import re
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from research_core import runs as _runs
from research_core.affordances import free
from research_core.backends.base import Budget, Evidence, ResearchBackend
from research_core.config import resolve_settings
from research_core.errors import NoEvidence, SmartToolError
from research_core.reasoning import Reasoner
from research_core.staging import AttemptsExhausted, StageResult
from research_core.urls import classify_url
from research_core.writer import SCHEMA as RUN_SCHEMA
from research_core.writer import RunWriter, new_run_id

from deep_research import stages

STAGES = ("scope", "gather", "synthesise", "report")

#: Above this, the report is left on disk and the envelope carries a pointer.
#: Below it, the caller gets the whole thing inline and is spared a second call.
INLINE_BYTE_THRESHOLD = 8_000


def _backend_for(name: str, *, provider: str | None, model: str | None) -> ResearchBackend:
    if name == "perplexity":
        from research_core.backends.perplexity import PerplexityBackend

        return PerplexityBackend(model=model)
    if name == "agent":
        from research_core.backends.agent import AgentBackend

        return AgentBackend(provider=provider, model=model)
    from research_core.errors import UsageError

    raise UsageError(
        f"There is no backend {name!r}.",
        "Backends: perplexity, agent. Set one with --backend, the config file, "
        "or RESEARCH_BACKEND.",
    )


def _reasoner_for(
    reasoner: Reasoner | None,
    *,
    provider: str | None,
    model: str | None,
    timeout_ms: int,
) -> Reasoner:
    """The reasoning seam. A supplied reasoner is how a test drives the whole
    pipeline with no provider and no tokens spent."""
    if reasoner is not None:
        return reasoner
    from research_core.reasoning import AgentReasoner

    return AgentReasoner(provider=provider, model=model, timeout_ms=timeout_ms)


def number_sources(evidence: Evidence) -> list[dict[str, Any]]:
    """Give each source a stable id and a category, on our side of the seam.

    Ids are assigned here rather than by a backend so two backends cannot
    disagree about them, and so a citation marker means the same thing in every
    run this tool writes.
    """
    numbered: list[dict[str, Any]] = []
    for index, source in enumerate(evidence.sources, 1):
        numbered.append(
            {
                "id": f"s{index}",
                "url": source.url,
                "title": source.title,
                "category": classify_url(source.url),
                "found_in_stage": "gather",
            }
        )
    return numbered


def rewrite_citations(text: str, sources: list[dict[str, Any]]) -> str:
    """Rewrite a backend's `[1]` markers into this tool's `[sN]` ids.

    Deterministic, and it only rewrites markers that actually have a source
    behind them. A marker numbered past the end of the source list is LEFT AS IT
    IS rather than invented into an id -- the dangling-citation check is what
    should notice it, and silently renaming it would hide exactly the failure
    that check exists to catch.

    Both `[1]` and `[web:1]` are recognised. The second form is what the research
    service actually emits, which a recorded fixture did not reveal and one live
    call did.
    """
    count = len(sources)

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if 1 <= number <= count:
            return f"[s{number}]"
        return match.group(0)

    return re.sub(r"\[(?:web:)?(\d+)\]", replace, text)


def summarise(text: str, *, max_lines: int = 6) -> str:
    """The brief, taken from the synthesis.

    At this version the brief is the opening of the synthesis rather than a
    written summary, because the stage that would write one has no model behind
    it yet. It is extraction, not summarisation, and the difference matters
    enough to say in a docstring rather than let a reader assume otherwise.
    """
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return "\n".join(lines[:max_lines]).strip()


def _size_of(path: Path) -> int | None:
    """Bytes on disk, or None if it is not there. Never a guess.

    A fabricated size is worse than an honest absence: the whole point of a
    ladder is that a caller can refuse to fetch something enormous, and it can
    only do that if the numbers are real.
    """
    try:
        if path.is_dir():
            return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return path.stat().st_size
    except OSError:
        return None


def _ladder_and_affordances(
    run_id: str, run_path: Path, report: str, source_count: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The rungs above the proxy, with their real sizes, and the verbs to climb.

    The brief is the proxy: written by the agent to stand alone, and small
    enough to hand to a caller that will read nothing else. Everything above it
    is opt-in, and a caller decides what to pull knowing what it costs in bytes
    BEFORE pulling it -- which is the difference between navigation and a guess.
    """
    rungs = [
        ("brief", "the answer, standalone -- you already have it", run_path / "brief.md"),
        ("report", "the full synthesis with numbered sections", run_path / "report.md"),
        (
            "sources",
            f"all {source_count} citations as filterable data",
            run_path / "sources.json",
        ),
        ("raw", "the backend's own replies, verbatim, for audit", run_path / "raw"),
    ]
    ladder = [
        {
            "rung": name,
            "does": does,
            "bytes": _size_of(path),
            "cost_usd": "0.00",
            "ready": path.exists(),
        }
        for name, does, path in rungs
    ]

    has_sections = any(
        line.startswith("## ") and line[3:].split(".")[0].strip().isdigit()
        for line in report.splitlines()
    )
    affordances = [
        free(
            "read",
            "a bounded slice of the report; always says whether the view is "
            "partial and by how much",
            command=(
                f"deep-research read {run_id} --sections 1-3"
                if has_sections
                else f"deep-research read {run_id} --lines 40"
            ),
            call=f"deep_research.read({run_id!r}, lines=40)",
            returns="text",
            bytes=_size_of(run_path / "report.md"),
        ),
        free(
            "sources",
            f"the {source_count} citations as data, filterable by category",
            command=f"deep-research sources {run_id} --category academic",
            call=f"deep_research.sources({run_id!r}, category='academic')",
            bytes=_size_of(run_path / "sources.json"),
        ),
        free(
            "render",
            "reshape this run without re-running it: markdown, json, bibliography",
            command=f"deep-research render {run_id} --format bibliography",
            call=f"deep_research.render({run_id!r}, format='bibliography')",
            returns="text",
        ),
        free(
            "status",
            "this run's stages, usage and liveness",
            command=f"deep-research status {run_id}",
            call=f"deep_research.status({run_id!r})",
        ),
    ]
    return ladder, [a.to_dict() for a in affordances]


def _next_commands(run_id: str, report: str) -> dict[str, str]:
    """The navigation block, built from what this run actually contains.

    A hint that does not work is worse than no hint: it teaches a caller a
    command, the command fails, and the caller stops trusting the block. So the
    section form is only offered when the report really has numbered sections --
    a short report does not, and the plain read is what works there.
    """
    has_sections = any(
        line.startswith("## ") and line[3:].split(".")[0].strip().isdigit()
        for line in report.splitlines()
    )
    read = (
        f"deep-research read {run_id} --sections 1-3"
        if has_sections
        else f"deep-research read {run_id}"
    )
    return {
        "read_report": read,
        "list_sources": f"deep-research sources {run_id}",
        "render": f"deep-research render {run_id} --format bibliography",
    }


def research(
    query: str,
    *,
    depth: str | None = None,
    backend: str | ResearchBackend | None = None,
    max_sources: int | None = None,
    runs_dir: str | None = None,
    timeout_ms: int | None = None,
    inline: bool | None = None,
    quiet: bool = False,
    stream: TextIO | None = None,
    reasoner: Reasoner | None = None,
    max_attempts: int | None = None,
    scope: bool = True,
    run_id: str | None = None,
    detach: bool = False,
) -> dict[str, Any]:
    """Run the research workflow and return a brief plus a pointer to the evidence.

    ``backend`` may be a name or an already-constructed backend; passing one is
    how a test drives the whole pipeline without a credential or a network.
    """
    settings = resolve_settings(
        runs_dir=runs_dir,
        depth=depth,
        timeout_ms=timeout_ms,
        backend=backend if isinstance(backend, str) else None,
    )

    if detach:
        # Hand back part one and get out of the way. The work continues in a
        # child process writing to the same run directory, which was always the
        # durable state -- detaching names what was already there rather than
        # building something new.
        return _detach(
            query,
            run_id=run_id or new_run_id("dr"),
            settings=settings,
            depth=depth,
            backend=backend if isinstance(backend, str) else None,
            max_sources=max_sources,
            inline=inline,
            max_attempts=max_attempts,
            scope=scope,
        )

    engine: ResearchBackend = (
        backend
        if not isinstance(backend, str) and backend is not None
        else _backend_for(
            settings["backend"], provider=settings["provider"], model=settings["model"]
        )
    )
    thinker = _reasoner_for(
        reasoner,
        provider=settings["provider"],
        model=settings["model"],
        timeout_ms=settings["timeout_ms"],
    )
    attempts_allowed = max_attempts or settings["max_attempts"]

    # Refuse BEFORE anything is created or sent. BOTH seams are checked here:
    # discovering halfway through that the reasoning stages cannot run would mean
    # having already paid for the evidence.
    engine.preflight()
    thinker.preflight()

    budget = Budget(
        depth=settings["depth"],
        max_sources=max_sources,
        timeout_ms=settings["timeout_ms"],
        model=settings["model"],
    )

    writer = RunWriter(
        runs_dir=settings["runs_dir"],
        run_id=run_id or new_run_id("dr"),
        tool="deep-research",
        query=query,
        depth=budget.depth,
        backend=getattr(engine, "name", "unknown"),
        stages=STAGES,
        quiet=quiet,
        stream=stream,
    )

    try:

        def progress(event: dict[str, Any]) -> None:
            writer.event(event.pop("type", "progress"), **event)

        writer.start_stage("scope")
        if scope:
            scoped = stages.scope(thinker, query, max_attempts=attempts_allowed, on_event=progress)
            writer.write_json("scope.json", scoped.value)
            writer.record_usage(scoped.usage)
            writer.finish_stage("scope", attempts=len(scoped.attempts), scoped=True)
            sharpened = str(scoped.value.get("question") or query)
        else:
            # The caller's question, asked as they asked it. A turn is not free,
            # and sharpening can narrow a search that would have found more on
            # the original wording -- so whether it helps is an empirical
            # question, and this is the other arm of it.
            scoped = StageResult(value={"question": query}, attempts=[])
            writer.write_json("scope.json", {"question": query, "scoped": False})
            writer.finish_stage("scope", attempts=0, scoped=False)
            sharpened = query

        writer.start_stage("gather")
        evidence = engine.gather(
            sharpened,
            budget,
            scope=str(scoped.value.get("question") or ""),
            on_event=progress,
        )
        writer.write_raw("gather-01.json", getattr(evidence, "raw", None) or evidence.to_dict())
        sources = number_sources(evidence)
        writer.write_json(
            _runs.SOURCES_FILE,
            {
                "schema": "research-sources/v1",
                "run_id": writer.run_id,
                "sources": sources,
            },
        )
        writer.count(sources=len(sources))
        if not sources:
            # Refuse rather than degrade. A run with no evidence dressed up as a
            # complete research result is the most expensive thing this tool
            # could return: it looks exactly like a good one.
            raise NoEvidence(
                "The gather stage returned no sources, so there is nothing to base an answer on.",
                "Check `check` -- a backend whose tools failed to load will "
                "answer from memory and cite nothing. Try --backend perplexity, "
                "or a question with a published answer.",
                # A refusal is a response, and a response owes the caller a next
                # move. This one already knows a great deal: which host it ran
                # on, which run directory it wrote to, and that a run record
                # exists even though the answer does not.
                affordances=[
                    free(
                        "check",
                        "what this host resolves, and what each missing piece "
                        "would unlock -- the usual cause of an empty gather",
                        command="deep-research check",
                        call="deep_research.check()",
                    ),
                    free(
                        "status",
                        "this run's stages and where it stopped; the run record "
                        "survives the refusal",
                        command=f"deep-research status {writer.run_id}",
                        call=f"deep_research.status({writer.run_id!r})",
                    ),
                    free(
                        "list",
                        "earlier runs in this runs directory, which may already "
                        "hold evidence for this question",
                        command="deep-research list",
                        call="deep_research.list_runs()",
                    ),
                ],
            )
        if evidence.usage:
            writer.record_usage(evidence.usage)

        # What the backend actually DID, reported the same way for both.
        # The agent backend streams a tool event per call; a research service
        # runs its own loop and tells us afterwards. Either way a caller paying
        # for searches and fetches should be able to see them, so the service's
        # own accounting is replayed as the same kind of event.
        calls = evidence.usage.get("calls") or {}
        for name, detail in calls.items():
            progress(
                {
                    "type": "tool",
                    "name": name,
                    "status": "complete",
                    "invocations": detail.get("invocations"),
                    "cost_usd": detail.get("cost_usd"),
                    "reported_by": "backend",
                }
            )
        if calls:
            writer.count(sources=len(sources), backend_calls=evidence.usage.get("call_count"))
        writer.finish_stage("gather", sources=len(sources), calls=calls or None)

        writer.start_stage("synthesise")
        body = rewrite_citations(evidence.text, sources)
        written = stages.synthesise(
            thinker,
            sharpened,
            sources,
            body,
            max_attempts=attempts_allowed,
            on_event=progress,
        )
        writer.write_json(
            "attempts.json",
            {
                "scope": [a.to_dict() for a in scoped.attempts],
                "synthesise": [a.to_dict() for a in written.attempts],
            },
        )
        writer.record_usage(written.usage)
        writer.finish_stage("synthesise", attempts=len(written.attempts), synthesised=True)

        writer.start_stage("report")
        report = str(written.value["report"]).strip() + "\n"
        # An h1 title, not merely any heading. A synthesis that opens straight at
        # "## 1." has sections but no title, and a reader opening the file has
        # nothing telling them what question it answers.
        if not report.lstrip().startswith("# "):
            report = f"# {sharpened}\n\n{report}"
        brief = str(written.value["brief"]).strip()
        writer.write_file(_runs.REPORT_FILE, report)
        writer.write_file(_runs.BRIEF_FILE, brief + "\n")
        writer.set(confidence=written.value.get("confidence"))
        writer.finish_stage("report")

        record = writer.complete()
    except AttemptsExhausted as exc:
        # Loudly, carrying every attempt. Returning the least-bad draft would
        # hand back a partial answer nobody could tell apart from a good one.
        writer.write_json("attempts.json", {exc.stage: [a.to_dict() for a in exc.attempts]})
        writer.fail(
            stage=exc.stage,
            code="attempts_exhausted",
            message=str(exc),
            remedy=(
                "Every attempt is kept in attempts.json with the reason it was "
                "rejected. Raise max_attempts if the model was close, or look at "
                "the rejections -- repeated identical ones usually mean the "
                "evidence cannot support the question as asked."
            ),
        )
        raise SmartToolError(str(exc), "See attempts.json in the run directory.") from exc
    except SmartToolError as exc:
        # The run keeps everything gathered before the failure. A failed run that
        # threw its evidence away would make a retry cost twice.
        current = next(
            (s["name"] for s in writer.record["stages"] if s.get("status") == "running"),
            "gather",
        )
        writer.fail(stage=current, code=exc.code, message=exc.message, remedy=exc.remedy)
        raise

    run = _runs.load_run(settings["runs_dir"], writer.run_id)
    dangling = _runs.dangling_citations(run)
    report_bytes = len(report.encode("utf-8"))
    show_inline = inline if inline is not None else report_bytes <= INLINE_BYTE_THRESHOLD

    envelope: dict[str, Any] = {
        "run_id": writer.run_id,
        "status": record["status"],
        "brief": brief,
        "confidence": record.get("confidence"),
        "source_count": len(sources),
        "path": str(writer.path),
        "report_bytes": report_bytes,
        "inline": bool(show_inline),
        "usage": record.get("usage"),
        "next": _next_commands(writer.run_id, report),
    }
    # The rungs above the proxy, and the verbs to climb them. `next` stays: it is
    # a documented contract term and a caller may be parsing it, so removing it
    # would be a breaking change for a cosmetic gain.
    ladder, affordances = _ladder_and_affordances(writer.run_id, writer.path, report, len(sources))
    envelope["ladder"] = ladder
    envelope["affordances"] = affordances
    if show_inline:
        envelope["report"] = report
    if dangling:
        # Surfaced, never swallowed: the synthesis cited something this run does
        # not have. It is reported on the result rather than only in a log,
        # because a caller acting on the brief needs to know.
        envelope["warnings"] = [
            {
                "code": "dangling_citations",
                "message": (
                    f"The report cites {', '.join(dangling)}, which no source in this run defines."
                ),
                "markers": dangling,
            }
        ]
    return envelope


def _detach(
    query: str,
    *,
    run_id: str,
    settings: dict[str, Any],
    depth: str | None,
    backend: str | None,
    max_sources: int | None,
    inline: bool | None,
    max_attempts: int | None,
    scope: bool,
) -> dict[str, Any]:
    """Start the work elsewhere and return what is true right now.

    Part one of a sequence. It carries the identifier, where the rest will
    appear, and -- the part that matters -- an explicit statement of what is NOT
    yet true, so a caller cannot mistake an accepted request for an answer.

    The child is spawned detached, with its own session, so it outlives the
    caller. Its output goes to files in the run directory rather than to the
    caller's terminal, because a background process writing to a shared stderr
    is how a caller's own output gets corrupted by something it stopped watching.
    """
    import json as _json
    import subprocess
    import sys

    runs_dir = Path(settings["runs_dir"]).expanduser()
    run_path = runs_dir / run_id
    run_path.mkdir(parents=True, exist_ok=True)

    arguments = {
        "query": query,
        "run_id": run_id,
        "runs_dir": str(runs_dir),
        "depth": depth,
        "backend": backend,
        "max_sources": max_sources,
        "inline": inline,
        "max_attempts": max_attempts,
        "scope": scope,
        "quiet": True,
    }
    bootstrap = (
        "import json,sys;import deep_research;deep_research.research(**json.loads(sys.argv[1]))"
    )
    with (run_path / "detached.log").open("wb") as log:
        child = subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", bootstrap, _json.dumps(arguments)],
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(runs_dir),
        )

    # Claim the run before the child gets there, so a caller that asks for status
    # immediately finds a record rather than a gap. The child's RunWriter
    # overwrites this with the same pid, because that pid IS the child.
    now = datetime.now(UTC).isoformat()
    (run_path / _runs.RUN_FILE).write_text(
        _json.dumps(
            {
                "schema": RUN_SCHEMA,
                "run_id": run_id,
                "tool": "deep-research",
                "status": "running",
                "pid": child.pid,
                "host": socket.gethostname(),
                "query": query,
                "depth": settings["depth"],
                "backend": settings["backend"],
                "created_at": now,
                "updated_at": now,
                "detached": True,
                "stages": [{"name": n, "status": "not_started"} for n in STAGES],
                "counts": {},
                "usage": {},
                "confidence": None,
                "failure": None,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return {
        "run_id": run_id,
        "accepted": True,
        "detached": True,
        "path": str(run_path),
        "pid": child.pid,
        # Said plainly, because an accepted request looks a great deal like an
        # answer if nobody says otherwise.
        "not_yet_true": [
            "no evidence has been gathered",
            "no report exists",
            "no confidence has been assessed",
            "the run may still fail",
        ],
        "poll_again_in_seconds": 10,
        "affordances": [
            a.to_dict()
            for a in (
                free(
                    "status",
                    "whether this run is growing, final, or abandoned -- ask "
                    "this before anything else",
                    command=f"deep-research status {run_id}",
                    call=f"deep_research.status({run_id!r})",
                ),
                free(
                    "read",
                    "a bounded slice of the report, once one exists",
                    command=f"deep-research read {run_id} --lines 40",
                    call=f"deep_research.read({run_id!r}, lines=40)",
                ),
                free(
                    "sources",
                    "the citations, once gathering has finished",
                    command=f"deep-research sources {run_id}",
                    call=f"deep_research.sources({run_id!r})",
                ),
            )
        ],
    }
