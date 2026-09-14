#!/usr/bin/env python3
"""Measure whether fact-check's judgments are any GOOD, not merely that it runs.

Conformance proves a tool is SHAPED right. For a tool whose entire output is
judgments, that is the weak half. This measures the other half.

Three modes, and the middle one is the one that makes the other two trustworthy:

  oracle     a scripted reasoner that returns the expected verdict for every
             claim. Proves the harness plumbing works end to end. Should score
             100%, and a score below that is a bug in the HARNESS, not the tool.
  adversary  a scripted reasoner that returns deliberately wrong -- but valid --
             verdicts. Proves the scorer can FAIL. A harness that cannot report
             a bad score is not a measurement, it is decoration.
  live       the real thing. Costs money. Records the model and the spend
             alongside the scores so a later pass can be compared honestly.

Neither scripted mode needs a provider or spends a token, so the harness can be
developed and trusted for free.

    uv run evaluation/run.py --mode oracle
    uv run evaluation/run.py --mode adversary
    uv run evaluation/run.py --mode live --out evaluation/results/
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

#: The confusion the whole tool exists to prevent. Tracked on its own rather
#: than folded into an accuracy number, because it is the one error that turns a
#: cautious tool into a confidently wrong one.
CRITICAL_CONFUSION = ("unverifiable", "refuted")


def load_fixtures() -> dict[str, Any]:
    return json.loads((FIXTURES / "claims.json").read_text(encoding="utf-8"))


def seed_runs_dir(runs_dir: Path, evidence_run: str) -> None:
    """Copy the fixture evidence into a scratch runs directory."""
    import shutil

    runs_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        FIXTURES / "evidence" / evidence_run, runs_dir / evidence_run, dirs_exist_ok=True
    )


def scripted_reasoner(claims: list[dict[str, Any]], *, wrong: bool):
    """A reasoner that answers from the fixture rather than from a model.

    ``wrong`` produces deliberately incorrect but STRUCTURALLY VALID verdicts --
    valid so they pass the tool's own validators and reach the scorer, which is
    the only way to prove the scorer notices.
    """
    from research_core.reasoning import ScriptedReasoner

    replies = [
        json.dumps(
            {
                "claims": [
                    {
                        "index": i,
                        "text": c["text"],
                        "type": "opinion" if c["expected"] == "opinion" else "complex",
                        "reason": "fixture",
                    }
                    for i, c in enumerate(claims)
                ]
            }
        )
    ]
    for claim in claims:
        verdict = claim["expected"]
        if wrong:
            # The specific wrong answer matters: turning every `unverifiable`
            # into `refuted` is the exact failure the tool is built to avoid,
            # so the adversary commits it on purpose.
            verdict = {
                "unverifiable": "refuted",
                "supported": "unverifiable",
                "refuted": "supported",
                "opinion": "supported",
            }[claim["expected"]]
        # A `refuted` verdict must cite a source or the tool rejects it, so the
        # adversary cites one -- its wrongness has to survive validation to be
        # measured.
        sources = ["s1"] if verdict in ("supported", "refuted") else []
        replies.append(
            json.dumps(
                {
                    "verdict": verdict,
                    "confidence": "medium",
                    "reasoning": f"Fixture reply for {claim['id']}, citing [s1].",
                    "sources": sources,
                }
            )
        )
    replies.append(
        json.dumps(
            {
                "brief": "Fixture compile.",
                "report": "## 1. Fixture\n\nScripted.",
                "confidence": "medium",
            }
        )
    )
    return ScriptedReasoner(*replies)


def score(claims: list[dict[str, Any]], verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    """Per category, never one number. One number hides the only thing worth knowing."""
    by_index = {v["index"]: v for v in verdicts}
    per_category: dict[str, dict[str, Any]] = {}
    critical = 0
    detail = []

    for index, claim in enumerate(claims):
        actual = (by_index.get(index) or {}).get("verdict")
        correct = actual == claim["expected"]
        bucket = per_category.setdefault(claim["category"], {"n": 0, "correct": 0, "missed": []})
        bucket["n"] += 1
        if correct:
            bucket["correct"] += 1
        else:
            bucket["missed"].append(claim["id"])
        if (claim["expected"], actual) == CRITICAL_CONFUSION:
            critical += 1
        detail.append(
            {
                "id": claim["id"],
                "category": claim["category"],
                "expected": claim["expected"],
                "actual": actual,
                "correct": correct,
            }
        )

    for bucket in per_category.values():
        bucket["accuracy"] = round(bucket["correct"] / bucket["n"], 3) if bucket["n"] else None

    total = len(claims)
    right = sum(b["correct"] for b in per_category.values())
    return {
        "per_category": per_category,
        # Reported last and deliberately not first: it is the least informative
        # figure here and the easiest to quote out of context.
        "overall": {"n": total, "correct": right, "accuracy": round(right / total, 3)},
        "critical_confusions": {
            "description": "claims where the evidence was inadequate and the tool "
            "answered `refuted` -- asserting falsehood from absence",
            "count": critical,
        },
        "claims": detail,
    }


def run_pass(mode: str, *, model: str | None, provider: str | None) -> dict[str, Any]:
    import fact_check

    fixtures = load_fixtures()
    claims = fixtures["claims"]

    with tempfile.TemporaryDirectory() as scratch:
        runs_dir = Path(scratch) / "runs"
        seed_runs_dir(runs_dir, fixtures["evidence_run"])

        reasoner = None
        if mode in ("oracle", "adversary"):
            reasoner = scripted_reasoner(claims, wrong=(mode == "adversary"))

        started = datetime.now(UTC)
        envelope = fact_check.check_claims(
            claim=[c["text"] for c in claims],
            from_run=fixtures["evidence_run"],
            runs_dir=str(runs_dir),
            reasoner=reasoner,
            quiet=True,
        )
        elapsed = (datetime.now(UTC) - started).total_seconds()

        found = fact_check.verdicts(envelope["run_id"], runs_dir=str(runs_dir))["verdicts"]

    result = score(claims, found)
    result["pass"] = {
        "mode": mode,
        "at": started.isoformat(),
        "seconds": round(elapsed, 1),
        "claim_count": len(claims),
        # Recorded so a later pass is comparable rather than merely different.
        "model": model or os.environ.get("RESEARCH_MODEL") or "provider default",
        "provider": provider or os.environ.get("RESEARCH_PROVIDER") or "first resolvable",
        "usage": envelope.get("usage"),
        "tally": envelope.get("tally"),
    }
    return result


def render(result: dict[str, Any]) -> str:
    lines = []
    info = result["pass"]
    lines.append(f"mode={info['mode']}  claims={info['claim_count']}  {info['seconds']}s")
    if info["mode"] == "live":
        usage = info.get("usage") or {}
        lines.append(
            f"model={info['model']}  provider={info['provider']}  "
            f"cost=${usage.get('cost_usd')}  tokens={usage.get('tokens_in')}"
            f"/{usage.get('tokens_out')}"
        )
    lines.append("")
    lines.append(f"{'category':<20} {'n':>3} {'correct':>8} {'accuracy':>9}   missed")
    for name, bucket in sorted(result["per_category"].items()):
        missed = ", ".join(bucket["missed"]) or "-"
        lines.append(
            f"{name:<20} {bucket['n']:>3} {bucket['correct']:>8} {bucket['accuracy']:>9}   {missed}"
        )
    lines.append("")
    critical = result["critical_confusions"]
    marker = "OK" if critical["count"] == 0 else "!!"
    lines.append(
        f"{marker} asserted falsehood from absence (unverifiable -> refuted): {critical['count']}"
    )
    overall = result["overall"]
    lines.append(f"   overall {overall['correct']}/{overall['n']} = {overall['accuracy']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--mode",
        choices=("oracle", "adversary", "live"),
        default="oracle",
        help="oracle and adversary spend nothing; live costs money",
    )
    parser.add_argument("--model", help="recorded with the scores")
    parser.add_argument("--provider", help="recorded with the scores")
    parser.add_argument("--out", metavar="DIR", help="write the result document here")
    parser.add_argument("--json", action="store_true", help="emit JSON on stdout")
    args = parser.parse_args(argv)

    result = run_pass(args.mode, model=args.model, provider=args.provider)

    if args.out:
        directory = Path(args.out).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = result["pass"]["at"].replace(":", "").replace("-", "")[:15]
        path = directory / f"{args.mode}-{stamp}.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(f"written: {path}", file=sys.stderr)

    print(json.dumps(result, indent=2, sort_keys=True) if args.json else render(result))

    # A harness that always exits 0 teaches nothing. The critical confusion is
    # the failing condition, not the overall score.
    return 1 if result["critical_confusions"]["count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
