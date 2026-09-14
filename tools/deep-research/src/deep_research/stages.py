"""The reasoning stages, and the check that stands between them and the report.

Each turn is bracketed by deterministic code. The model proposes; code validates;
a rejection feeds the specific finding back into the next attempt. When the budget
is spent the run FAILS carrying every attempt, rather than returning the
least-bad draft -- a partial answer that looks whole is worse than no answer,
because nobody can tell it apart from a good one.

The citation check is the sharpest of these and the cheapest: a model citing a
source it was never given is the characteristic failure of research tooling, and
it is a set membership test with no judgment in it at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from research_core.parsing import NoStructureFound, extract_json
from research_core.reasoning import Reasoner
from research_core.runs import citation_ids

from deep_research import prompts


class StageRejected(RuntimeError):
    """An attempt failed validation. Carries what to tell the model next."""

    def __init__(self, reason: str, *, finding: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.finding = finding


@dataclass
class Attempt:
    """One try at a stage, kept whether it succeeded or not."""

    number: int
    accepted: bool
    reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.number,
            "accepted": self.accepted,
            "reason": self.reason,
            "usage": self.usage,
        }


@dataclass
class StageResult:
    """What a stage produced, and every attempt it took to get there."""

    value: Any
    attempts: list[Attempt]

    @property
    def usage(self) -> dict[str, Any]:
        total_in = sum(int(a.usage.get("tokens_in") or 0) for a in self.attempts)
        total_out = sum(int(a.usage.get("tokens_out") or 0) for a in self.attempts)
        costs = [a.usage.get("cost_usd") for a in self.attempts if a.usage.get("cost_usd")]
        return {
            "tokens_in": total_in,
            "tokens_out": total_out,
            # Every attempt is charged for, including the rejected ones. Reporting
            # only the accepted attempt's cost would understate what the run spent.
            "cost_usd": str(sum(float(c) for c in costs)) if costs else None,
        }


class AttemptsExhausted(RuntimeError):
    """The budget was spent without an acceptable result."""

    def __init__(self, stage: str, attempts: list[Attempt]) -> None:
        super().__init__(
            f"The {stage} stage was rejected {len(attempts)} times and the attempt budget is spent."
        )
        self.stage = stage
        self.attempts = attempts


def run_stage(
    name: str,
    reasoner: Reasoner,
    prompt: str,
    *,
    validate,
    max_attempts: int = 3,
    on_event=None,
) -> StageResult:
    """Run one stage, repairing on rejection, failing loudly when spent.

    ``validate`` receives the parsed document and either returns it or raises
    StageRejected carrying the specific finding to put in front of the model next
    time. "Try again" teaches nothing; "you cited s4, which does not exist" does.
    """
    attempts: list[Attempt] = []
    current = prompt

    for number in range(1, max(1, max_attempts) + 1):
        thought = reasoner.think(current, on_event=on_event)
        try:
            document = extract_json(thought.text)
        except NoStructureFound as exc:
            rejection = StageRejected(
                str(exc),
                finding="Your reply carried no JSON document. Return ONLY the "
                "JSON document asked for, with no prose around it.",
            )
        else:
            try:
                value = validate(document)
            except StageRejected as exc:
                rejection = exc
            else:
                attempts.append(Attempt(number, accepted=True, usage=thought.usage))
                if on_event:
                    on_event(
                        {
                            "type": "stage_attempt",
                            "stage": name,
                            "attempt": number,
                            "accepted": True,
                        }
                    )
                return StageResult(value=value, attempts=attempts)

        attempts.append(
            Attempt(number, accepted=False, reason=rejection.reason, usage=thought.usage)
        )
        if on_event:
            on_event(
                {
                    "type": "stage_attempt",
                    "stage": name,
                    "attempt": number,
                    "accepted": False,
                    "reason": rejection.reason,
                }
            )
        current = f"{prompt}\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED.\n\n{rejection.finding}"

    raise AttemptsExhausted(name, attempts)


# -- the stages --------------------------------------------------------------


def scope(reasoner: Reasoner, query: str, *, max_attempts: int = 3, on_event=None) -> StageResult:
    """Work out what would actually answer the question, before spending on it."""

    def validate(document: Any) -> dict[str, Any]:
        if not isinstance(document, dict) or not document.get("question"):
            raise StageRejected(
                "no sharpened question",
                finding='Your document must carry a non-empty "question" field.',
            )
        return document

    return run_stage(
        "scope",
        reasoner,
        prompts.SCOPE.format(persona=prompts.PERSONA, query=query),
        validate=validate,
        max_attempts=max_attempts,
        on_event=on_event,
    )


def synthesise(
    reasoner: Reasoner,
    query: str,
    sources: list[dict[str, Any]],
    findings: str,
    *,
    max_attempts: int = 3,
    on_event=None,
) -> StageResult:
    """Weigh the evidence and write the report, citing only what it was given."""
    known = {s["id"] for s in sources}
    listing = "\n".join(
        f"[{s['id']}] {s.get('title') or '(untitled)'} — {s['url']}" for s in sources
    )

    def validate(document: Any) -> dict[str, Any]:
        if not isinstance(document, dict):
            raise StageRejected(
                "not an object",
                finding="Return a JSON object with brief, report and confidence.",
            )
        for required in ("brief", "report"):
            if not str(document.get(required) or "").strip():
                raise StageRejected(
                    f"no {required}",
                    finding=f'Your document must carry a non-empty "{required}".',
                )

        cited = citation_ids(f"{document['brief']}\n{document['report']}")
        dangling = [marker for marker in cited if marker not in known]
        if dangling:
            # The specific markers, not "fix your citations". A rejection that
            # does not say what was wrong buys a second attempt at the same
            # mistake.
            raise StageRejected(
                f"cited {', '.join(dangling)}, which no source in this run defines",
                finding=prompts.REPAIR.format(
                    original="",
                    markers=", ".join(dangling),
                    is_are="is" if len(dangling) == 1 else "are",
                ).strip(),
            )
        return document

    return run_stage(
        "synthesise",
        reasoner,
        prompts.SYNTHESISE.format(
            persona=prompts.PERSONA,
            query=query,
            sources=listing or "(no sources were gathered)",
            findings=findings,
        ),
        validate=validate,
        max_attempts=max_attempts,
        on_event=on_event,
    )
