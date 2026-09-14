"""Render a tool's own manifest and usage as an Agent Skill.

`--help` is written for a person: prose, ordered by what a reader wants to know
first. An agent reading the same text has to infer the contract from English --
which verbs cost money, what shape comes back, how to go deeper without
swallowing a whole run.

This emits the same knowledge in the format hosts already have machinery for:
[Agent Skills](https://agentskills.io/specification) -- YAML frontmatter
carrying `name` and `description`, then a markdown body. A host can write it
straight into a skills directory; an agent can read it as it reads any other
skill.

Nothing here is invented. The frontmatter comes from the manifest the tool
already ships, and the body states the same contract `--help` states, arranged
for a reader who is deciding whether and how to CALL something rather than
deciding whether to install it.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

#: What an agent most needs and a person mostly knows already: which calls are
#: free. A host that cannot tell them apart either burns credit exploring, or
#: refuses to touch the tool at all.
_COST_NOTE = (
    "Every verb below marked `deterministic` runs with **no AI provider and no "
    "credentials**, spends nothing, and is safe to call freely -- including on a "
    "machine that has never been configured. Only the verbs marked "
    "`model-backed` spend tokens."
)


def _wrap(text: str, width: int = 88) -> str:
    """Fold prose without breaking the YAML the frontmatter depends on."""
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return "\n".join(lines)


def render_skill(
    manifest: Any,
    *,
    verbs: dict[str, str],
    model_backed: tuple[str, ...],
    result_shape: str,
    navigation: str,
    examples: tuple[tuple[str, str], ...] = (),
) -> str:
    """Render one tool as a skill document.

    ``verbs`` maps verb name to one line of what it does. ``model_backed`` names
    the ones that spend. ``result_shape`` and ``navigation`` are the two things a
    caller cannot infer from a verb list and most needs before calling.
    """
    data = manifest.to_dict() if hasattr(manifest, "to_dict") else dict(manifest)
    name = data.get("name", "tool")
    description = " ".join(str(data.get("description") or "").split())

    lines = [
        "---",
        f"name: {name}",
        # The description is what a host matches on when deciding whether this
        # skill is relevant, so it carries the WHEN as well as the WHAT.
        "description: >-",
        *[f"  {line}" for line in _wrap(description, 84).splitlines()],
        "---",
        "",
        f"# {name}",
        "",
        _wrap(description),
        "",
    ]

    use_cases = data.get("use_cases") or []
    if use_cases:
        lines += ["## Reach for this when", ""]
        lines += [f"- {_wrap(case, 84)}" for case in use_cases]
        lines += [""]

    lines += ["## Cost", "", _wrap(_COST_NOTE), ""]

    lines += ["## Verbs", "", "| verb | | what it does |", "|---|---|---|"]
    for verb, summary in verbs.items():
        kind = "**model-backed**" if verb in model_backed else "deterministic"
        lines.append(f"| `{verb}` | {kind} | {' '.join(str(summary).split())} |")
    lines += [""]

    lines += ["## Reading the result", "", _wrap(result_shape), ""]
    lines += ["## Going deeper without swallowing everything", "", _wrap(navigation), ""]

    requires = data.get("requires") or []
    if requires:
        lines += ["## What it needs", ""]
        for requirement in requires:
            optional = "optional" if requirement.get("optional") else "required"
            detail = " ".join(str(requirement.get("description") or "").split())
            lines.append(f"- **{requirement.get('name')}** ({optional}) — {detail}")
        lines += [
            "",
            _wrap(
                f"Run `{name} check` to see which of these this host actually has. "
                "It is deterministic, so it answers on a machine with nothing "
                "configured -- and it reports what each missing one would unlock "
                "rather than only that it is missing."
            ),
            "",
        ]

    if examples:
        lines += ["## Examples", ""]
        for intent, command in examples:
            lines += [f"{_wrap(intent)}", "", "```bash", command, "```", ""]

    return "\n".join(lines).rstrip() + "\n"


class SkillHelpAction(argparse.Action):
    """`--help` prints the tool's skill; `-h` keeps the terse human summary.

    Adopted from David Koleczek's Smart Tool Creator after measuring our own
    choice and finding it worse. We had made `skill` a verb, reasoning that a
    host would find it in the verb list -- but a host that does not know the
    tool at all reaches for `--help` first, and ours answered that with prose.
    Our own A/B is the evidence: an agent given that prose could not say what
    `confidence` meant; one given the skill quoted the rule and planned around
    it.

    Two builders reached the `-h` / `--help` split independently, which is a
    better argument for it than either of us makes alone.
    """

    def __init__(self, option_strings, dest, skill: Callable[[], str], **kwargs):
        super().__init__(option_strings, dest, nargs=0, **kwargs)
        self._skill = skill

    def __call__(self, parser, namespace, values, option_string=None):
        # write, not print: the document already ends in a newline, and print
        # would add a second. That one byte is the difference between `--help`
        # and the committed `skills/<name>/SKILL.md` being the SAME document,
        # which is the whole point of shipping both.
        sys.stdout.write(self._skill())
        parser.exit()


def add_help_flags(parser: argparse.ArgumentParser, *, skill: Callable[[], str]) -> None:
    """Wire `-h` to the terse summary and `--help` to the skill.

    The parser must be built with `add_help=False`, because argparse binds both
    spellings to one action and we want them to differ.
    """
    parser.add_argument(
        "-h",
        action="help",
        default=argparse.SUPPRESS,
        help="terse summary for a person: the verbs, a line each",
    )
    parser.add_argument(
        "--help",
        action=SkillHelpAction,
        skill=skill,
        default=argparse.SUPPRESS,
        help="this tool's skill, written for an agent driving it",
    )
