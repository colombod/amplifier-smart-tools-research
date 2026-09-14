#!/usr/bin/env python3
"""Measure whether deep-research's ANSWERS are honest, not whether it answers.

A tool that always answers scores perfectly on "does it answer". The question
worth asking is whether the confidence it reports matches the evidence it
actually found, and whether every citation resolves to something it really
gathered.

So the fixture set is weighted toward questions where a confident answer would
be WRONG -- including two about things that DO NOT EXIST, where search will
return plausible adjacent results and hand the tool everything it needs to
confabulate fluently.

Three modes, same discipline as the fact-check harness:

  oracle     scripted, returns what the fixture expects. Proves the plumbing.
  adversary  scripted, answers everything with high confidence and a dangling
             citation -- the two failures this measures. Proves the scorer bites.
  live       the real thing. Costs money; records model, provider and spend.

    uv run evaluation/research.py --mode oracle
    uv run evaluation/research.py --mode adversary
    uv run evaluation/research.py --mode live --out evaluation/results/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"

#: A citation pointing at a source the run does not have. Tracked on its own and
#: treated as the failing condition: it is the one defect that makes a report
#: actively misleading rather than merely weak, because it looks like evidence.
CRITICAL = "dangling_citations"

#: Refusal codes that mean "I looked and the evidence was not there". Anything
#: else is the tool breaking, which is never a correct answer to a question.
HONEST_REFUSALS = {"no_evidence"}


def load_questions() -> dict[str, Any]:
    return json.loads((FIXTURES / "questions.json").read_text(encoding="utf-8"))


def scripted(question: dict[str, Any], *, wrong: bool):
    """Answer from the fixture rather than from a model."""
    from research_core.backends.base import Evidence, Source
    from research_core.backends.scripted import ScriptedBackend
    from research_core.reasoning import ScriptedReasoner

    expect = question.get("expect") or {}
    if wrong:
        # The two failures worth measuring, committed on purpose: confident
        # about everything, and citing a source that was never gathered.
        confidence = "high"
        report = "## 1. Answer\n\nStated plainly in [s1] and [s9].\n"
    else:
        allowed = expect.get("confidence_in")
        if allowed:
            confidence = allowed[0]
        else:
            forbidden = set(expect.get("confidence_not") or [])
            confidence = next(c for c in ("medium", "low", "high") if c not in forbidden)
        report = "## 1. Answer\n\nStated plainly in [s1].\n"

    evidence = Evidence(
        text="Findings [1].",
        sources=[
            Source(url=f"https://example.invalid/{i}", title=f"Source {i}") for i in range(1, 4)
        ],
        usage={},
        backend="fixture",
    )
    return ScriptedBackend(evidence), ScriptedReasoner(
        json.dumps({"question": question["text"]}),
        json.dumps({"brief": "A brief.", "report": report, "confidence": confidence}),
    )


def judge(
    question: dict[str, Any],
    envelope: dict[str, Any] | None,
    sources: list[dict[str, Any]],
    report: str,
    refused: str | None,
) -> dict[str, Any]:
    """Score one question. Every check here is deterministic."""
    from research_core.runs import citation_ids

    expect = question.get("expect") or {}
    checks: dict[str, Any] = {}

    if refused is not None:
        # NOT ALL REFUSALS ARE THE SAME, and treating them alike scored the
        # adversary as CORRECT on the very questions it was built to fail.
        #
        # A refusal because the evidence was inadequate is an honest answer to a
        # question with no answer. A refusal because the machinery broke -- a
        # repair loop exhausted, a backend error -- says nothing about the
        # question at all, and counting it as a good outcome rewards a tool for
        # falling over on exactly the inputs that are hardest to get right.
        #
        # This is the same distinction fact-check draws between `unverifiable`
        # and a claim it could not check. It had to be learned twice.
        honest = refused in HONEST_REFUSALS
        allowed = honest and bool(expect.get("allow_refusal"))
        return {
            "id": question["id"],
            "category": question["category"],
            "refused": refused,
            "checks": {
                "refusal_was_about_evidence": honest,
                "refusal_allowed_here": allowed,
            },
            "dangling": 0,
            "correct": allowed,
        }

    known = {s["id"] for s in sources}
    cited = set(citation_ids(report))
    dangling = sorted(marker for marker in cited if marker not in known)
    checks["citations_resolve"] = not dangling

    if "min_sources" in expect:
        checks["enough_sources"] = len(sources) >= expect["min_sources"]
    confidence = (envelope or {}).get("confidence")
    if "confidence_in" in expect:
        checks["confidence_expected"] = confidence in expect["confidence_in"]
    if "confidence_not" in expect:
        checks["confidence_not_overstated"] = confidence not in expect["confidence_not"]

    return {
        "id": question["id"],
        "category": question["category"],
        "confidence": confidence,
        "sources": len(sources),
        "checks": checks,
        "dangling": len(dangling),
        "correct": all(checks.values()),
    }


def run_pass(
    mode: str, *, model: str | None, provider: str | None, backend: str | None
) -> dict[str, Any]:
    import deep_research
    from research_core.errors import SmartToolError

    fixtures = load_questions()
    questions = fixtures["questions"]
    started = datetime.now(UTC)
    results: list[dict[str, Any]] = []
    spend = {"cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0, "backend_calls": 0}

    with tempfile.TemporaryDirectory() as scratch:
        for question in questions:
            kwargs: dict[str, Any] = {"runs_dir": scratch, "quiet": True, "depth": "low"}
            if mode in ("oracle", "adversary"):
                back, reasoner = scripted(question, wrong=(mode == "adversary"))
                kwargs.update(backend=back, reasoner=reasoner)
            elif backend:
                kwargs["backend"] = backend

            envelope: dict[str, Any] | None = None
            refused: str | None = None
            sources: list[dict[str, Any]] = []
            report = ""
            try:
                envelope = deep_research.research(question["text"], **kwargs)
                found = deep_research.sources(envelope["run_id"], runs_dir=scratch)
                sources = found["sources"]
                report = deep_research.read(envelope["run_id"], runs_dir=scratch, part="report")[
                    "text"
                ]
                usage = envelope.get("usage") or {}
                spend["cost_usd"] += float(usage.get("cost_usd") or 0)
                spend["tokens_in"] += int(usage.get("tokens_in") or 0)
                spend["tokens_out"] += int(usage.get("tokens_out") or 0)
            except SmartToolError as exc:
                # Refusing is a real outcome, not a crash. Which questions a tool
                # refuses is one of the things being measured.
                refused = exc.code

            results.append(judge(question, envelope, sources, report, refused))

    per_category: dict[str, dict[str, Any]] = {}
    for result in results:
        bucket = per_category.setdefault(result["category"], {"n": 0, "correct": 0, "missed": []})
        bucket["n"] += 1
        if result["correct"]:
            bucket["correct"] += 1
        else:
            bucket["missed"].append(result["id"])
    for bucket in per_category.values():
        bucket["accuracy"] = round(bucket["correct"] / bucket["n"], 3)

    right = sum(b["correct"] for b in per_category.values())
    return {
        "pass": {
            "mode": mode,
            "at": started.isoformat(),
            "seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
            "question_count": len(questions),
            "model": model or os.environ.get("RESEARCH_MODEL") or "provider default",
            "provider": provider or os.environ.get("RESEARCH_PROVIDER") or "first resolvable",
            "backend": backend or ("fixture" if mode != "live" else "default"),
            "spend": {
                "cost_usd": round(spend["cost_usd"], 6),
                "tokens_in": spend["tokens_in"],
                "tokens_out": spend["tokens_out"],
            },
        },
        "per_category": per_category,
        "overall": {
            "n": len(results),
            "correct": right,
            "accuracy": round(right / len(results), 3),
        },
        CRITICAL: {
            "description": "citations pointing at sources the run does not have -- "
            "the defect that makes a report look like evidence when it is not",
            "count": sum(r["dangling"] for r in results),
        },
        "questions": results,
    }


def render(result: dict[str, Any]) -> str:
    info = result["pass"]
    spend = info["spend"]
    lines = [
        f"mode={info['mode']}  questions={info['question_count']}  {info['seconds']}s",
    ]
    if info["mode"] == "live":
        lines.append(
            f"model={info['model']}  backend={info['backend']}  "
            f"spend=${spend['cost_usd']}  tokens={spend['tokens_in']}/{spend['tokens_out']}"
        )
    lines += ["", f"{'category':<14} {'n':>3} {'correct':>8} {'accuracy':>9}   missed"]
    for name, bucket in sorted(result["per_category"].items()):
        lines.append(
            f"{name:<14} {bucket['n']:>3} {bucket['correct']:>8} "
            f"{bucket['accuracy']:>9}   {', '.join(bucket['missed']) or '-'}"
        )
    critical = result[CRITICAL]["count"]
    lines += [
        "",
        f"{'OK' if not critical else '!!'} dangling citations: {critical}",
        f"   overall {result['overall']['correct']}/{result['overall']['n']} "
        f"= {result['overall']['accuracy']}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--mode", choices=("oracle", "adversary", "live"), default="oracle")
    parser.add_argument("--backend", help="live only: perplexity or agent")
    parser.add_argument("--model")
    parser.add_argument("--provider")
    parser.add_argument("--out", metavar="DIR")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = run_pass(args.mode, model=args.model, provider=args.provider, backend=args.backend)

    if args.out:
        directory = Path(args.out).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = result["pass"]["at"].replace(":", "").replace("-", "")[:15]
        path = directory / f"research-{args.mode}-{stamp}.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(f"written: {path}", file=sys.stderr)

    print(json.dumps(result, indent=2, sort_keys=True) if args.json else render(result))
    return 1 if result[CRITICAL]["count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
