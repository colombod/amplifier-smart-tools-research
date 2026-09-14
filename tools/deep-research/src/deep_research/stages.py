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

from typing import Any

from research_core.reasoning import Reasoner
from research_core.runs import citation_ids
from research_core.staging import StageRejected, StageResult, run_stage

from deep_research import prompts

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
