"""The Agent Skills specification caps `description` in SKILL.md frontmatter at
1024 characters -- it is the discovery surface a host reads before the skill is
loaded and before `--help` has been run. A real harness enforces this at
discovery time and merely warns and continues, so a skill that goes over does
not fail loudly where a human would notice -- it silently gets a truncated (or
entirely skipped, depending on the host) discovery surface forever after.

Both `skills/deep-research/SKILL.md` and `skills/fact-check/SKILL.md` are
generated pointers (`<pkg>.pointer_skill()`, see test_skill.py), so the actual
fix for an over-limit description lives in the source manifest
(`src/<pkg>/SMART_TOOL.md`'s `description` and `use_cases`), never in the
committed file directly -- see that module's docstring for why a hand-edit
does not stick.

This enumerates every `skills/*/SKILL.md` at the repository root rather than
naming the two tools by hand, so a skill added later is covered without
anyone remembering to write a second test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

#: packages/research-core/tests/ -> packages/research-core -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

#: The Agent Skills specification's hard ceiling on frontmatter `description`.
_DESCRIPTION_LIMIT = 1024


def _skill_files() -> list[Path]:
    return sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))


def _parsed_description(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    assert match, f"{path} must open with a '---' YAML frontmatter fence"
    frontmatter = yaml.safe_load(match.group(1))
    description = frontmatter.get("description")
    assert description, f"{path} frontmatter needs a non-empty 'description'"
    return description


def test_at_least_one_skill_is_found() -> None:
    # A guard that silently checks zero files is not a guard.
    assert _skill_files(), "expected at least one skills/*/SKILL.md in this repository"


@pytest.mark.parametrize("path", _skill_files(), ids=lambda p: p.parent.name)
def test_skill_description_stays_under_the_agent_skills_limit(path: Path) -> None:
    description = _parsed_description(path)
    assert len(description) <= _DESCRIPTION_LIMIT, (
        f"{path} frontmatter 'description' is {len(description)} chars, "
        f"over the Agent Skills spec's {_DESCRIPTION_LIMIT}-char limit. "
        "This file is a generated pointer -- trim the manifest's 'description' "
        "and 'use_cases' in src/<pkg>/SMART_TOOL.md, then regenerate via "
        "<pkg>.pointer_skill(); do not hand-edit the SKILL.md."
    )
