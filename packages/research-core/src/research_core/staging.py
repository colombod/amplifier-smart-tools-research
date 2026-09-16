"""Running a model-backed stage, and repairing it when it fails validation.

Shared by both tools, because the discipline is the same wherever a model
proposes and code decides: the model proposes, code validates, and a rejection
feeds the SPECIFIC finding back into the next attempt. "Try again" buys a second
attempt at the same mistake.

When the attempt budget is spent the caller fails carrying every attempt, rather
than returning the least-bad draft. A partial answer that looks whole is worse
than no answer, because nobody can tell it apart from a good one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from research_core.parsing import NoStructureFound, extract_json
from research_core.reasoning import Reasoner


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
        rejected = [
            a.usage.get("cost_usd")
            for a in self.attempts
            if not a.accepted and a.usage.get("cost_usd")
        ]
        return {
            "tokens_in": total_in,
            "tokens_out": total_out,
            # Every attempt is charged for, including the rejected ones. Reporting
            # only the accepted attempt's cost would understate what the run spent.
            "cost_usd": str(sum(float(c) for c in costs)) if costs else None,
            # And the total ALONE is not enough. "This cost $1.01" and "this cost
            # $1.01, of which $0.66 was thrown away and retried" are different
            # facts, and only the second lets a caller decide to do something.
            "attempts": len(self.attempts),
            "attempts_discarded": sum(1 for a in self.attempts if not a.accepted),
            "discarded_cost_usd": str(sum(float(c) for c in rejected)) if rejected else None,
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
    on_reply=None,
) -> StageResult:
    """Run one stage, repairing on rejection, failing loudly when spent.

    ``validate`` receives the parsed document and either returns it or raises
    StageRejected carrying the specific finding to put in front of the model next
    time. "Try again" teaches nothing; "you cited s4, which does not exist" does.

    ``on_reply`` receives EVERY reply -- accepted and rejected alike -- as
    ``(attempt_number, text, accepted)``. Rejected replies are the ones worth
    keeping: a run once failed synthesis twice at $0.38 a go and the replies were
    discarded at the moment they became interesting, leaving the cause
    undiagnosable. A caller is charged for an attempt whether or not it was
    accepted, so it is entitled to see what it bought.
    """
    attempts: list[Attempt] = []
    current = prompt

    for number in range(1, max(1, max_attempts) + 1):
        thought = reasoner.think(current, on_event=on_event)
        # Recorded BEFORE parsing, so a reply survives even when parsing is the
        # thing that fails -- which is precisely the case we could not diagnose.
        reply_text = getattr(thought, "text", "") or ""
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
                if on_reply:
                    on_reply(number, reply_text, True)
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
        if on_reply:
            on_reply(number, reply_text, False)
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
