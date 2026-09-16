"""The checking stages: triage, verify per claim, compile.

`verify` is the reason this tool exists as a separate workflow rather than a verb
on the research tool. Claims are independent, so the stage fans out over N of
them where N is not known until runtime, and each verdict is written as it lands
rather than at the end -- a run interrupted after three of six claims leaves
three real verdicts on disk, not nothing.

That shape is also why a graph orchestrator was assessed and declined: a fan-out
whose width is a runtime value, with no branching, is a for-loop wearing a
diagram.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from research_core.reasoning import Reasoner
from research_core.runs import citation_ids
from research_core.staging import StageRejected, StageResult, run_stage

from fact_check import prompts

VERDICTS = ("supported", "refuted", "unverifiable", "opinion")
CLAIM_TYPES = ("simple", "complex", "opinion", "context")


class ClaimUncheckable(RuntimeError):
    """A claim could not be checked for a MECHANICAL reason.

    Deliberately not a verdict. `unverifiable` means the tool looked and the
    evidence was inadequate -- a finding a caller can act on. This means the tool
    never got as far as looking, which is a different thing entirely, and
    recording it as `unverifiable` would put a fabricated finding in the record.
    The run fails instead.
    """

    def __init__(self, claim: str, reason: str) -> None:
        super().__init__(f"{claim!r} could not be checked: {reason}")
        self.claim = claim
        self.reason = reason


@dataclass
class Verdict:
    """One claim's assessment, auditable on its own."""

    index: int
    claim: str
    claim_type: str
    verdict: str
    confidence: str | None = None
    reasoning: str = ""
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "claim": self.claim,
            "claim_type": self.claim_type,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "sources": list(self.sources),
        }


def triage(
    reasoner: Reasoner,
    claims: list[str],
    *,
    strict: bool = False,
    max_attempts: int = 3,
    on_event=None,
    on_reply=None,
) -> StageResult:
    """Sort claims by what checking each would take.

    ``strict`` escalates everything to `complex` WITHOUT asking a model: if the
    caller has already decided every claim deserves the expensive treatment,
    paying for a classification turn to be told so is waste.
    """
    if strict:
        return StageResult(
            value={
                "claims": [
                    {
                        "index": i,
                        "text": c,
                        "type": "complex",
                        "reason": "--strict was requested",
                    }
                    for i, c in enumerate(claims)
                ]
            },
            attempts=[],
        )

    numbered = "\n".join(f"[{i}] {c}" for i, c in enumerate(claims))

    def validate(document: Any) -> dict[str, Any]:
        if not isinstance(document, dict) or not isinstance(document.get("claims"), list):
            raise StageRejected(
                "no claims array",
                finding='Your document must carry a "claims" array.',
            )
        seen = {entry.get("index") for entry in document["claims"] if isinstance(entry, dict)}
        missing = [i for i in range(len(claims)) if i not in seen]
        if missing:
            # Silently dropping a claim would understate the tally and nobody
            # would notice the claim that vanished.
            raise StageRejected(
                f"claims {missing} were not classified",
                finding=(
                    f"You did not classify claim(s) {missing}. Every claim must "
                    "appear exactly once, keyed by its index."
                ),
            )
        for entry in document["claims"]:
            if entry.get("type") not in CLAIM_TYPES:
                raise StageRejected(
                    f"claim {entry.get('index')} has type {entry.get('type')!r}",
                    finding=(
                        f"{entry.get('type')!r} is not a claim type. Use one of: "
                        f"{', '.join(CLAIM_TYPES)}."
                    ),
                )
        return document

    return run_stage(
        "triage",
        reasoner,
        prompts.TRIAGE.format(persona=prompts.PERSONA, claims=numbered),
        validate=validate,
        max_attempts=max_attempts,
        on_event=on_event,
        on_reply=on_reply,
    )


def verify_one(
    reasoner: Reasoner,
    index: int,
    claim: str,
    claim_type: str,
    sources: list[dict[str, Any]],
    findings: str,
    *,
    max_attempts: int = 3,
    on_event=None,
    on_reply=None,
) -> tuple[Verdict, StageResult]:
    """Assess one claim. Claims are independent, so this is the unit that fans out."""
    known = {s["id"] for s in sources}
    listing = "\n".join(
        f"[{s['id']}] {s.get('title') or '(untitled)'} — {s['url']}" for s in sources
    )

    def validate(document: Any) -> dict[str, Any]:
        if not isinstance(document, dict):
            raise StageRejected(
                "not an object", finding="Return a JSON object, not a list or a string."
            )
        given = document.get("verdict")
        if given not in VERDICTS:
            raise StageRejected(
                f"verdict {given!r} is not one of {VERDICTS}",
                finding=(
                    f"{given!r} is not a verdict. Use exactly one of: "
                    f"{', '.join(VERDICTS)}. If you checked and found no adequate "
                    "evidence either way, that is `unverifiable` -- never `refuted`."
                ),
            )
        if not str(document.get("reasoning") or "").strip():
            raise StageRejected(
                "no reasoning",
                finding=(
                    'Your document must carry "reasoning". A verdict nobody can '
                    "audit is not a verdict."
                ),
            )

        cited = set(document.get("sources") or []) | set(
            citation_ids(str(document.get("reasoning") or ""))
        )
        dangling = sorted(marker for marker in cited if marker not in known)
        if dangling:
            raise StageRejected(
                f"cited {', '.join(dangling)}, which this run does not have",
                finding=(
                    f"You cited {', '.join(dangling)}, which is not in the source "
                    "list you were given. Cite only what you were given, or state "
                    "the point as unsupported with no marker."
                ),
            )

        # A refutation that rests on nothing is the failure mode this tool is
        # built to prevent: it is the shape "I could not confirm it" takes when
        # it wants to sound decisive.
        if document["verdict"] == "refuted" and not cited:
            raise StageRejected(
                "refuted with no source",
                finding=(
                    "You returned `refuted` while citing no source. Refuted means "
                    "the evidence CONTRADICTS the claim, so name the source that "
                    "does. If you simply found nothing adequate, the verdict is "
                    "`unverifiable`."
                ),
            )
        return document

    result = run_stage(
        f"verify[{index}]",
        reasoner,
        prompts.VERIFY.format(
            persona=prompts.PERSONA,
            claim=claim,
            sources=listing or "(no sources were gathered)",
            findings=findings or "(no findings were recorded)",
        ),
        validate=validate,
        max_attempts=max_attempts,
        on_event=on_event,
        on_reply=on_reply,
    )
    document = result.value
    return (
        Verdict(
            index=index,
            claim=claim,
            claim_type=claim_type,
            verdict=document["verdict"],
            confidence=document.get("confidence"),
            reasoning=str(document.get("reasoning") or ""),
            sources=[s for s in (document.get("sources") or []) if s in known],
        ),
        result,
    )


def tally(verdicts: list[Verdict]) -> dict[str, int]:
    """The counts. Deterministic, and small enough to travel inline."""
    counts: dict[str, int] = {name: 0 for name in VERDICTS}
    for verdict in verdicts:
        counts[verdict.verdict] = counts.get(verdict.verdict, 0) + 1
    return counts


def compile_summary(
    reasoner: Reasoner,
    verdicts: list[Verdict],
    *,
    max_attempts: int = 3,
    on_event=None,
    on_reply=None,
) -> StageResult:
    """Say what the set of verdicts means together."""
    rendered = "\n\n".join(
        f"[{v.index}] {v.claim}\n  verdict: {v.verdict} ({v.confidence})\n"
        f"  reasoning: {v.reasoning}"
        for v in verdicts
    )

    def validate(document: Any) -> dict[str, Any]:
        if not isinstance(document, dict):
            raise StageRejected("not an object", finding="Return a JSON object.")
        for required in ("brief", "report"):
            if not str(document.get(required) or "").strip():
                raise StageRejected(
                    f"no {required}",
                    finding=f'Your document must carry a non-empty "{required}".',
                )
        return document

    return run_stage(
        "compile",
        reasoner,
        prompts.COMPILE.format(persona=prompts.PERSONA, verdicts=rendered),
        validate=validate,
        max_attempts=max_attempts,
        on_event=on_event,
        on_reply=on_reply,
    )
