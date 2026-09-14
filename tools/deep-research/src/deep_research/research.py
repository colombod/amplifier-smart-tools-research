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
from research_core.errors import SmartToolError
from research_core.urls import classify_url
from research_core.writer import RunWriter, new_run_id

STAGES = ("scope", "gather", "synthesise", "report")

#: Above this, the report is left on disk and the envelope carries a pointer.
#: Below it, the caller gets the whole thing inline and is spared a second call.
INLINE_BYTE_THRESHOLD = 8_000


def _backend_for(name: str, *, model: str | None) -> ResearchBackend:
    if name == "perplexity":
        from research_core.backends.perplexity import PerplexityBackend

        return PerplexityBackend(model=model)
    from research_core.errors import UsageError

    raise UsageError(
        f"There is no backend {name!r}.",
        "Backends: perplexity. Set it with --backend, the config file, or RESEARCH_BACKEND.",
    )


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
    """
    count = len(sources)

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if 1 <= number <= count:
            return f"[s{number}]"
        return match.group(0)

    return re.sub(r"\[(\d+)\]", replace, text)


def summarise(text: str, *, max_lines: int = 6) -> str:
    """The brief, taken from the synthesis.

    At this version the brief is the opening of the synthesis rather than a
    written summary, because the stage that would write one has no model behind
    it yet. It is extraction, not summarisation, and the difference matters
    enough to say in a docstring rather than let a reader assume otherwise.
    """
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return "\n".join(lines[:max_lines]).strip()


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
        else _backend_for(settings["backend"], model=settings["model"])
    )

    # Refuse BEFORE anything is created or sent. A refusal must not leave a run
    # directory behind, and must never reach the point of building a prompt.
    engine.preflight()

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
        writer.start_stage("scope")
        # The scope turn arrives with the agent backend. Today the question is
        # passed through unchanged, and the stage records that honestly.
        scoped = query
        writer.finish_stage("scope", scoped=False)

        writer.start_stage("gather")
        evidence = engine.gather(scoped, budget)
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
        if evidence.usage:
            writer.record_usage(evidence.usage)
        writer.finish_stage("gather", sources=len(sources))

        writer.start_stage("synthesise")
        body = rewrite_citations(evidence.text, sources)
        writer.finish_stage("synthesise", synthesised=False)

        writer.start_stage("report")
        report = f"# {query}\n\n{body.strip()}\n"
        brief = summarise(body)
        writer.write_file(_runs.REPORT_FILE, report)
        writer.write_file(_runs.BRIEF_FILE, brief + "\n")
        writer.finish_stage("report")

        record = writer.complete()
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
        "next": {
            "read_report": f"deep-research read {writer.run_id} --sections 1-3",
            "list_sources": f"deep-research sources {writer.run_id}",
            "render": f"deep-research render {writer.run_id} --format bibliography",
        },
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
