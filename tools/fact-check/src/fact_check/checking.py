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

import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from research_core import runs as _runs
from research_core.affordances import free
from research_core.config import resolve_settings
from research_core.errors import NoEvidence, SmartToolError, UsageError
from research_core.reasoning import Reasoner
from research_core.staging import AttemptsExhausted
from research_core.writer import SCHEMA as RUN_SCHEMA
from research_core.writer import RunWriter, new_run_id

from fact_check import stages

STAGES = ("triage", "verify", "compile")
INLINE_BYTE_THRESHOLD = 8_000


def _reply_keeper(writer, stage: str):
    """Persist EVERY backend reply for a stage, accepted or rejected.

    `raw/` is documented as "the backend's own replies, verbatim, for audit".
    fact-check wrote NOTHING there -- not one reply, accepted or otherwise. A
    sibling run in deep-research then failed a stage twice at $0.38 an attempt
    and the replies were discarded at the instant they became the only evidence
    of why. A caller is charged for a rejected attempt and is entitled to see
    what it paid for.
    """

    def keep(attempt: int, text: str, accepted: bool) -> None:
        suffix = "" if accepted else "-rejected"
        writer.write_raw(f"{stage}-{attempt:02d}{suffix}.txt", text)

    return keep


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


def _mark_detached_failure(run_path: Path, *, code: str, message: str, remedy: str) -> None:
    """Persist a failure into run.json when nothing else will.

    `check_claims()` already calls `writer.fail()` for anything that goes
    wrong once its own `RunWriter` exists. This is the fallback for
    everything else: a preflight that somehow still failed inside the child,
    or any exception `check_claims()` itself never anticipated. Without it, a
    detached run that dies before it has a writer stays `status: "running"`
    forever -- the exact silent-failure shape detaching must not introduce.
    """
    import json as _json

    run_file = run_path / _runs.RUN_FILE
    try:
        record = _json.loads(run_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return  # No record to correct; nothing safe to write from here.
    if record.get("status") == "failed":
        return  # check_claims() already persisted the real failure; do not clobber it.
    record["status"] = "failed"
    record["updated_at"] = datetime.now(UTC).isoformat()
    record["failure"] = {
        "stage": None,
        "code": code,
        "message": message,
        "remedy": f"{remedy} Log retained at {run_path / 'detached.log'}.",
    }
    run_file.write_text(_json.dumps(record, sort_keys=True), encoding="utf-8")


def _run_detached_child(arguments: dict[str, Any]) -> None:
    """Entry point for the detached child process.

    Bridges the gap between "the parent already wrote run.json as running"
    and "check_claims() can only update that record once its own RunWriter
    exists". Anything that goes wrong before that -- or any exception
    check_claims() itself does not already turn into a persisted failure --
    lands here instead of a run that reads as `running` after its process is
    gone.
    """
    run_path = Path(arguments["runs_dir"]) / arguments["run_id"]
    try:
        check_claims(**arguments)
    except SmartToolError as exc:
        _mark_detached_failure(run_path, code=exc.code, message=exc.message, remedy=exc.remedy)
        raise
    except Exception as exc:  # noqa: BLE001 - last resort so "running" is never permanent
        _mark_detached_failure(
            run_path,
            code="detached_crash",
            message=f"{type(exc).__name__}: {exc}",
            remedy="This is a defect in the tool. See the retained log for the traceback.",
        )
        raise


def _detach(
    *,
    claims: list[str],
    claim: list[str] | None,
    claims_file: str | None,
    from_run: str,
    strict: bool,
    settings: dict[str, Any],
    inline: bool | None,
    max_attempts: int | None,
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
    import shutil
    import subprocess
    import sys

    runs_dir = Path(settings["runs_dir"]).expanduser().resolve()
    run_id = new_run_id("fc")
    run_path = runs_dir / run_id
    run_path.mkdir(parents=True, exist_ok=True)

    arguments = {
        "claim": claim,
        "claims_file": claims_file,
        "from_run": from_run,
        "strict": strict,
        "runs_dir": str(runs_dir),
        "timeout_ms": settings["timeout_ms"],
        "inline": inline,
        "max_attempts": max_attempts,
        "quiet": True,
        "run_id": run_id,
    }
    bootstrap = (
        "import json,sys;from fact_check.checking import _run_detached_child;"
        "_run_detached_child(json.loads(sys.argv[1]))"
    )
    try:
        with (run_path / "detached.log").open("wb") as log:
            child = subprocess.Popen(  # noqa: S603
                [sys.executable, "-c", bootstrap, _json.dumps(arguments)],
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                cwd=str(runs_dir),
            )
    except OSError as exc:
        # The child never started, so no "running" record should sit there
        # claiming otherwise. Remove the directory this call claimed rather
        # than leave a run nobody will ever finish.
        shutil.rmtree(run_path, ignore_errors=True)
        raise SmartToolError(
            f"Could not start the detached run: {exc}",
            "The claimed run directory has been removed. Retry --detach, or "
            "run without it to see the failure directly.",
        ) from exc

    # Claim the run before the child gets there, so a caller that asks for status
    # immediately finds a record rather than a gap. The child's RunWriter
    # overwrites this with the same pid, because that pid IS the child.
    now = datetime.now(UTC).isoformat()
    (run_path / _runs.RUN_FILE).write_text(
        _json.dumps(
            {
                "schema": RUN_SCHEMA,
                "run_id": run_id,
                "tool": "fact-check",
                "status": "running",
                "pid": child.pid,
                "host": socket.gethostname(),
                "query": f"{len(claims)} claim(s)",
                "depth": "strict" if strict else settings["depth"],
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
        "path": str(run_path.resolve()),
        "pid": child.pid,
        "claim_count": len(claims),
        "inherited_from": from_run,
        # Said plainly, because an accepted request looks a great deal like an
        # answer if nobody says otherwise.
        "not_yet_true": [
            "no claim has been assessed",
            "no verdict exists",
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
                    command=f"fact-check status {run_id}",
                    call=f"fact_check.status({run_id!r})",
                ),
                free(
                    "verdicts",
                    "one verdict per claim, once they exist",
                    command=f"fact-check verdicts {run_id}",
                    call=f"fact_check.verdicts({run_id!r})",
                ),
                free(
                    "read",
                    "a bounded slice of the narrative, once one exists",
                    command=f"fact-check read {run_id} --lines 40",
                    call=f"fact_check.read({run_id!r}, lines=40)",
                ),
            )
        ],
    }


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
    detach: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Check claims against evidence, one verdict per claim.

    ``detach`` returns part one immediately and continues in the background.
    This verb makes ONE MODEL CALL PER CLAIM, so its own estimator predicts 330
    seconds for three claims and 959 for ten -- both far past the per-call limit
    of a typical agent harness, and that estimator is known to under-predict.
    A caller that blocks on ten claims will be killed and billed.
    """
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

    # Refuse before anything is created or sent -- for the blocking path AND
    # the detached one. A `--detach` request that will die on its own preflight
    # moments after the caller was told `accepted: true` has been misled about
    # what it received.
    thinker.preflight()

    if detach:
        # After the argument checks and the preflight above, and before any
        # model contact, so a malformed or unconfigured request still fails in
        # the caller's face rather than inside a child process nobody is
        # watching. The child re-preflights defensively, but this is what keeps
        # an unconfigured request from ever being accepted.
        return _detach(
            claims=claims,
            claim=claim,
            claims_file=claims_file,
            from_run=from_run,
            strict=strict,
            settings=settings,
            inline=inline,
            max_attempts=max_attempts,
        )

    # Reading the source run first means a bad --from-run fails without
    # leaving a half-built run behind it.
    sources, findings, inherited = evidence_from_run(settings["runs_dir"], from_run)

    writer = RunWriter(
        runs_dir=settings["runs_dir"],
        # The detached parent already published this id and a caller may already
        # be polling it. Minting a second one here would strand that caller on a
        # record that never advances.
        run_id=run_id or new_run_id("fc"),
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
            on_reply=_reply_keeper(writer, "triage"),
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
                    on_reply=_reply_keeper(writer, f"verify-{index:02d}"),
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
            thinker,
            verdicts,
            max_attempts=attempts_allowed,
            on_event=progress,
            on_reply=_reply_keeper(writer, "summary"),
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
        remedy = (
            "This is NOT the same as `unverifiable`, which means the claim was "
            "checked and the evidence was inadequate. The tool never got as "
            "far as looking. Verdicts for claims already checked are in "
            "verdicts.json. Raise max_attempts, or re-run with fewer claims."
        )
        writer.fail(stage="verify", code="claim_uncheckable", message=str(exc), remedy=remedy)
        # The SAME corrective remedy travels with the re-raised error -- a
        # caller reading the exception should not get a worse, less actionable
        # message than the one already persisted to the run record. The run
        # directory travels as a first-class `artifact_path` rather than being
        # folded into the prose.
        raise SmartToolError(
            str(exc),
            remedy,
            artifact_path=writer.path,
            affordances=[
                free(
                    "verdicts",
                    "the verdicts already recorded before this run stopped",
                    command=f"fact-check verdicts {writer.run_id}",
                    call=f"fact_check.verdicts({writer.run_id!r})",
                ),
            ],
        ) from exc
    except SmartToolError as exc:
        current = next(
            (s["name"] for s in writer.record["stages"] if s.get("status") == "running"),
            "verify",
        )
        writer.fail(stage=current, code=exc.code, message=exc.message, remedy=exc.remedy)
        # Enrich the SAME exception in place -- its code and exit_code are the
        # caller's contract and must not change. `with_artifact` attaches where
        # the evidence gathered so far is retained as a first-class field.
        exc.with_artifact(writer.path)
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
        "path": str(writer.path.resolve()),
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
