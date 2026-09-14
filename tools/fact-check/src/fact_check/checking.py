"""The checking run: triage, verify each claim, compile.

Where this differs from the research workflow, and why it is a separate tool
rather than a verb: the middle stage fans out over N claims where N is a runtime
value, each claim is assessed independently, and **each verdict is written as it
lands**. A run interrupted after three of six claims leaves three real verdicts
on disk rather than nothing.

`--from-run` is the payoff of one shared, accumulating runs directory: evidence
another run already gathered is read rather than bought again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TextIO

from research_core import runs as _runs
from research_core.config import resolve_settings
from research_core.errors import NoEvidence, SmartToolError, UsageError
from research_core.reasoning import Reasoner
from research_core.staging import AttemptsExhausted
from research_core.writer import RunWriter, new_run_id

from fact_check import stages

STAGES = ("triage", "verify", "compile")
INLINE_BYTE_THRESHOLD = 8_000


def read_claims(*, claim: list[str] | None = None, claims_file: str | None = None) -> list[str]:
    """Collect claims from arguments or a file, one per non-empty line."""
    collected = [c.strip() for c in (claim or []) if c and c.strip()]
    if claims_file:
        path = Path(claims_file).expanduser()
        if not path.is_file():
            raise UsageError(
                f"No claims file at {path}.",
                "Point --claims-file at a file with one claim per line.",
            )
        collected += [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    return collected


def evidence_from_run(runs_dir: str, run_id: str) -> tuple[list[dict[str, Any]], str, str]:
    """Read another run's evidence instead of gathering it again."""
    run = _runs.load_run(runs_dir, run_id)
    sources = _runs.sources_of(run)["sources"]
    if not sources:
        raise NoEvidence(
            f"Run {run_id} has no sources to check claims against.",
            "Pick a run that completed with sources -- `fact-check list` shows "
            "the source count for each.",
        )
    report_path = run.path / _runs.REPORT_FILE
    findings = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
    return sources, findings, run_id


def check_claims(
    *,
    claim: list[str] | None = None,
    claims_file: str | None = None,
    from_run: str | None = None,
    strict: bool = False,
    runs_dir: str | None = None,
    timeout_ms: int | None = None,
    inline: bool | None = None,
    quiet: bool = False,
    stream: TextIO | None = None,
    reasoner: Reasoner | None = None,
    max_attempts: int | None = None,
) -> dict[str, Any]:
    """Check claims against evidence, one verdict per claim."""
    settings = resolve_settings(runs_dir=runs_dir, timeout_ms=timeout_ms)
    claims = read_claims(claim=claim, claims_file=claims_file)
    if not claims:
        raise UsageError(
            "No claims were given.",
            "Pass --claim TEXT (repeatable) or --claims-file PATH.",
        )
    if not from_run:
        raise UsageError(
            "No evidence to check against.",
            "Pass --from-run ID to use a run that already gathered evidence. "
            "`fact-check list` shows what is available.",
        )

    thinker = reasoner
    if thinker is None:
        from research_core.reasoning import AgentReasoner

        thinker = AgentReasoner(
            provider=settings["provider"],
            model=settings["model"],
            timeout_ms=settings["timeout_ms"],
        )
    attempts_allowed = max_attempts or settings["max_attempts"]

    # Refuse before anything is created. Reading the source run first means a
    # bad --from-run fails without leaving a half-built run behind it.
    thinker.preflight()
    sources, findings, inherited = evidence_from_run(settings["runs_dir"], from_run)

    writer = RunWriter(
        runs_dir=settings["runs_dir"],
        run_id=new_run_id("fc"),
        tool="fact-check",
        query=f"{len(claims)} claim(s)",
        depth="strict" if strict else settings["depth"],
        backend=getattr(thinker, "name", "unknown"),
        stages=STAGES,
        quiet=quiet,
        stream=stream,
    )

    def progress(event: dict[str, Any]) -> None:
        writer.event(event.pop("type", "progress"), **event)

    try:
        # The sources are inherited, not gathered. Recording where they came from
        # is what lets a reader of this run audit a verdict back to the run that
        # actually found the evidence.
        writer.write_json(
            _runs.SOURCES_FILE,
            {
                "schema": "research-sources/v1",
                "run_id": writer.run_id,
                "inherited_from": inherited,
                "sources": sources,
            },
        )
        writer.count(sources=len(sources), claims=len(claims))
        writer.set(inherited_from=inherited)

        writer.start_stage("triage")
        sorted_claims = stages.triage(
            thinker,
            claims,
            strict=strict,
            max_attempts=attempts_allowed,
            on_event=progress,
        )
        writer.write_json("claims.json", sorted_claims.value)
        writer.record_usage(sorted_claims.usage)
        writer.finish_stage("triage", claims=len(claims), strict=strict)

        by_index = {
            entry["index"]: entry
            for entry in sorted_claims.value["claims"]
            if isinstance(entry, dict)
        }

        writer.start_stage("verify")
        verdicts: list[stages.Verdict] = []
        for index, text in enumerate(claims):
            entry = by_index.get(index, {})
            claim_type = str(entry.get("type") or "complex")
            progress(
                {
                    "type": "claim",
                    "index": index,
                    "of": len(claims),
                    "claim_type": claim_type,
                    "status": "started",
                }
            )
            try:
                verdict, result = stages.verify_one(
                    thinker,
                    index,
                    text,
                    claim_type,
                    sources,
                    findings,
                    max_attempts=attempts_allowed,
                    on_event=progress,
                )
            except AttemptsExhausted as exc:
                # A claim the tool could not check is NOT `unverifiable`. That
                # verdict means "checked, and the evidence was inadequate" -- a
                # finding a caller acts on. Recording a mechanical failure under
                # it would put a fabricated finding in the record.
                raise stages.ClaimUncheckable(
                    text, f"the {exc.stage} stage was rejected {len(exc.attempts)} times"
                ) from exc
            verdicts.append(verdict)
            writer.record_usage(result.usage)
            # Written as it lands: an interrupted run leaves real verdicts, not
            # nothing.
            writer.write_json(
                _runs.VERDICTS_FILE,
                {
                    "schema": "research-verdicts/v1",
                    "run_id": writer.run_id,
                    "complete": len(verdicts) == len(claims),
                    "verdicts": [v.to_dict() for v in verdicts],
                },
            )
            progress(
                {
                    "type": "claim",
                    "index": index,
                    "of": len(claims),
                    "verdict": verdict.verdict,
                    "status": "complete",
                }
            )

        counts = stages.tally(verdicts)
        writer.count(sources=len(sources), claims=len(claims), **counts)
        writer.finish_stage("verify", **counts)

        writer.start_stage("compile")
        summary = stages.compile_summary(
            thinker, verdicts, max_attempts=attempts_allowed, on_event=progress
        )
        writer.record_usage(summary.usage)
        report = str(summary.value["report"]).strip() + "\n"
        if not report.lstrip().startswith("# "):
            report = f"# {len(claims)} claim(s) checked\n\n{report}"
        brief = str(summary.value["brief"]).strip()
        writer.write_file(_runs.REPORT_FILE, report)
        writer.write_file(_runs.BRIEF_FILE, brief + "\n")
        writer.set(confidence=summary.value.get("confidence"))
        writer.finish_stage("compile")

        record = writer.complete()
    except stages.ClaimUncheckable as exc:
        writer.fail(
            stage="verify",
            code="claim_uncheckable",
            message=str(exc),
            remedy=(
                "This is NOT the same as `unverifiable`, which means the claim was "
                "checked and the evidence was inadequate. The tool never got as "
                "far as looking. Verdicts for claims already checked are in "
                "verdicts.json. Raise max_attempts, or re-run with fewer claims."
            ),
        )
        raise SmartToolError(str(exc), "See verdicts.json for what was checked.") from exc
    except SmartToolError as exc:
        current = next(
            (s["name"] for s in writer.record["stages"] if s.get("status") == "running"),
            "verify",
        )
        writer.fail(stage=current, code=exc.code, message=exc.message, remedy=exc.remedy)
        raise

    report_bytes = len(report.encode("utf-8"))
    show_inline = inline if inline is not None else report_bytes <= INLINE_BYTE_THRESHOLD

    envelope: dict[str, Any] = {
        "run_id": writer.run_id,
        "status": record["status"],
        "brief": brief,
        # Small, and it is the answer -- so it travels inline while the per-claim
        # detail stays on disk.
        "tally": counts,
        "claim_count": len(claims),
        "source_count": len(sources),
        "inherited_from": inherited,
        "confidence": record.get("confidence"),
        "path": str(writer.path),
        "report_bytes": report_bytes,
        "inline": bool(show_inline),
        "usage": record.get("usage"),
        "next": {
            "read_verdicts": f"fact-check verdicts {writer.run_id}",
            "read_refuted": f"fact-check verdicts {writer.run_id} --verdict refuted",
            "list_sources": f"fact-check sources {writer.run_id}",
        },
    }
    if show_inline:
        envelope["report"] = report
    return envelope
