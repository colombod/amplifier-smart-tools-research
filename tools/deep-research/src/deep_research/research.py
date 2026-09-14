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
from typing import Any, TextIO

from research_core import runs as _runs
from research_core.backends.base import Budget, Evidence, ResearchBackend
from research_core.config import resolve_settings
from research_core.errors import NoEvidence, SmartToolError
from research_core.reasoning import Reasoner
from research_core.staging import AttemptsExhausted
from research_core.urls import classify_url
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
        run_id=new_run_id("dr"),
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
        scoped = stages.scope(thinker, query, max_attempts=attempts_allowed, on_event=progress)
        writer.write_json("scope.json", scoped.value)
        writer.record_usage(scoped.usage)
        writer.finish_stage("scope", attempts=len(scoped.attempts), scoped=True)
        sharpened = str(scoped.value.get("question") or query)

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
