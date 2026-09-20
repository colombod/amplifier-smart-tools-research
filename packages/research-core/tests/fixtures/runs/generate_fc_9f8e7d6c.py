"""Regenerate the `fc-9f8e7d6c` fixture as a REAL recording.

D2 (see FINDINGS.md in the hackathon workspace): `fc-9f8e7d6c` used to be
hand-authored, field by field, before any writer existed. Its `run.json` carried
a top-level `tally` key and a `from_run` key that no real writer has ever
written, and was missing `confidence`, `host`, `inherited_from`, and `pid`,
which every real run carries. `verdicts.json` used 1-based claim indices; the
real writer indexes from 0 (`enumerate(claims)`). Both fictions made the reader
bug (`runs.py` reading `run.record["tally"]`, which no writer ever set) invisible
to the test suite: the fixture was built from the fields the reader consulted,
so it could only ever confirm the shape the reader already assumed.

This script drives the REAL pipeline -- `fact_check.check_claims()` -- through
the no-credential ScriptedReasoner seam (see CONTRIBUTING.md, "Testing against
a model"), against the existing `dr-1a2b3c4d` fixture as the evidence run. The
result is copied verbatim into this directory; only `host`, `pid`, and the
`run.json`/stage timestamps are scrubbed afterwards, since a committed fixture
should not carry this machine's hostname or process id. No credential is used
anywhere -- `ScriptedReasoner` never reaches a network.

Run from the repo root, with the dev venv active:

    .venv/bin/python packages/research-core/tests/fixtures/runs/generate_fc_9f8e7d6c.py

Then re-run `pytest packages/research-core/tests/test_runs.py` and diff the
result before committing -- a regenerated fixture that changes silently is
exactly the failure mode this file exists to avoid.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import fact_check
from research_core.reasoning import ScriptedReasoner

FIXTURES = Path(__file__).parent
RUN_ID = "fc-9f8e7d6c"
EVIDENCE_RUN_ID = "dr-1a2b3c4d"

CLAIMS = [
    "State-based CRDTs converge regardless of the order in which updates arrive.",
    "If two CRDT replicas converge, the value they converge on is correct.",
    "Most production CRDT implementations apply validation outside the lattice.",
]


def _reasoner() -> ScriptedReasoner:
    return ScriptedReasoner(
        json.dumps(
            {
                "claims": [
                    {
                        "index": 0,
                        "text": CLAIMS[0],
                        "type": "simple",
                        "reason": "direct property claim",
                    },
                    {
                        "index": 1,
                        "text": CLAIMS[1],
                        "type": "complex",
                        "reason": "requires distinguishing convergence from correctness",
                    },
                    {
                        "index": 2,
                        "text": CLAIMS[2],
                        "type": "complex",
                        "reason": "requires a survey claim",
                    },
                ]
            }
        ),
        json.dumps(
            {
                "verdict": "supported",
                "confidence": "high",
                "reasoning": (
                    "Both primary sources state the property directly, and it "
                    "follows from merge being associative, commutative and "
                    "idempotent [s1][s2]."
                ),
                "sources": ["s1", "s2"],
            }
        ),
        json.dumps(
            {
                "verdict": "refuted",
                "confidence": "high",
                "reasoning": (
                    "Convergence is agreement, not correctness. The sources are "
                    "explicit that strong eventual consistency says every "
                    "replica agrees on a state, and says nothing about that "
                    "state being one an application would accept [s2][s5]."
                ),
                "sources": ["s2", "s5"],
            }
        ),
        json.dumps(
            {
                "verdict": "unverifiable",
                "confidence": "low",
                "reasoning": (
                    "The claim is plausible and one source argues it from "
                    "individual cases, but no source surveys implementations, so "
                    "there is no evidence either way about 'most'. Checked and "
                    "not established -- not refuted [s5]."
                ),
                "sources": ["s5"],
            }
        ),
        json.dumps(
            {
                "brief": (
                    "3 claims assessed: 1 supported, 1 refuted, 1 unverifiable. "
                    "Convergence and correctness are frequently conflated."
                ),
                "report": (
                    "## 1. Summary\n\n"
                    "3 claims assessed: 1 supported, 1 refuted, 1 unverifiable. "
                    "Convergence and correctness are frequently conflated in "
                    "casual descriptions of CRDTs -- the evidence supports the "
                    "former but says nothing about the latter.\n"
                ),
                "confidence": "high",
            }
        ),
    )


def main() -> None:
    work_dir = FIXTURES.parent / "_fc_fixture_scratch"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    shutil.copytree(FIXTURES / EVIDENCE_RUN_ID, work_dir / EVIDENCE_RUN_ID)

    fact_check.check_claims(
        claim=CLAIMS,
        from_run=EVIDENCE_RUN_ID,
        reasoner=_reasoner(),
        runs_dir=str(work_dir),
        quiet=True,
        run_id=RUN_ID,
    )

    recorded = work_dir / RUN_ID
    run_file = recorded / "run.json"
    record = json.loads(run_file.read_text(encoding="utf-8"))
    # Scrub the two fields that identify the machine that recorded this, and
    # pin timestamps so re-running this script does not produce a pointless
    # diff. Nothing here is a credential -- ScriptedReasoner never reaches a
    # network -- this is purely "do not commit this sandbox's hostname".
    record["host"] = "ci-runner"
    record["pid"] = 41234
    record["created_at"] = "2026-09-20T12:00:00Z"
    record["updated_at"] = "2026-09-20T12:00:04Z"
    for stage in record["stages"]:
        stage["started_at"] = "2026-09-20T12:00:00Z"
        stage["ended_at"] = "2026-09-20T12:00:04Z"
    run_file.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    destination = FIXTURES / RUN_ID
    if destination.exists():
        shutil.rmtree(destination)
    shutil.move(str(recorded), str(destination))
    shutil.rmtree(work_dir)
    print(f"Recorded {destination}")


if __name__ == "__main__":
    main()
