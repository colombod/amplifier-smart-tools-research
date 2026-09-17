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

    Acquisition instructions are deliberately NOT here: a reader running
    `--help` already has the binary. They live in the pointer SKILL.md that
    ``render_pointer_skill`` builds, whose reader may not.
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


def render_verb_skill(
    subparser: argparse.ArgumentParser,
    *,
    prog: str,
    verb: str,
    spends_money: bool,
    returns: str = "",
) -> str:
    """One verb, explained for an agent deciding whether and how to call it.

    The rule, one level down: `-h` is ALWAYS the terse table for a person who
    already knows the verb; `--help` is ALWAYS the agent-facing document for
    whatever scope was asked about. At the root that scope is the tool. Here it
    is this verb.

    Generated from the subparser itself, so a verb added later inherits this
    without anyone remembering to. The argparse table is a reference; this is an
    explanation, and an agent choosing between twelve verbs needs the second.
    """
    lines: list[str] = [
        "---",
        f"name: {prog} {verb}",
        f"description: {' '.join((subparser.description or '').split())}",
        "---",
        "",
        f"# {prog} {verb}",
        "",
    ]

    if spends_money:
        lines += [
            "**This verb spends money and calls a model.** It may answer differently "
            "on a second run, and it fails saying so rather than returning a lesser "
            "answer when no backend is configured.",
            "",
        ]
    else:
        lines += [
            "**Deterministic.** Runs with no provider configured and no credentials "
            "of any kind, costs nothing, and returns the same answer for the same "
            "input.",
            "",
        ]

    required, optional = [], []
    for action in subparser._actions:
        help_text = " ".join((action.help or "").split())

        # POSITIONALS FIRST, and they are required by definition. Skipping them
        # was a real defect: an agent driving `status` had to infer that it takes
        # a run id from a worked example elsewhere, because this document listed
        # only flags. A document that omits the one argument a verb cannot run
        # without is worse than terse -- it is wrong.
        if not action.option_strings:
            if action.dest in ("help", "verb"):
                continue
            entry = f"- `{action.dest}` (positional)"
            required.append(entry + (f" — {help_text}" if help_text else ""))
            continue

        flags = [o for o in action.option_strings if o.startswith("--")]
        if not flags or flags[0] == "--help":
            continue
        entry = f"- `{flags[0]}`" + (f" — {help_text}" if help_text else "")
        (required if action.required else optional).append(entry)

    if required:
        lines += ["## Required", "", *required, ""]
    if optional:
        lines += ["## Optional", "", *optional, ""]

    if returns:
        lines += ["## What comes back", "", returns, ""]

    lines += [
        "## Reading the result",
        "",
        'One JSON document on stdout. Success is `{"result": ...}`; failure is '
        '`{"error": {"code", "message", "remedy", "affordances"}}` with a '
        "non-zero exit. **A refusal carries `affordances` too** — named next moves, "
        "each free and each needing no credential, so being refused is never a dead "
        "end. Progress and diagnostics go to stderr, never stdout.",
        "",
        f"For the whole tool rather than this one verb: `{prog} --help`.",
    ]
    return "\n".join(lines) + "\n"


class VerbSkillAction(argparse.Action):
    """`--help` on a subcommand: the verb's own agent-facing document."""

    def __init__(self, option_strings, dest, render: Callable[[], str], **kwargs):
        super().__init__(option_strings, dest, nargs=0, **kwargs)
        self._render = render

    def __call__(self, parser, namespace, values, option_string=None):
        sys.stdout.write(self._render())
        parser.exit()


def add_verb_help_flags(
    subparser: argparse.ArgumentParser,
    *,
    prog: str,
    verb: str,
    spends_money: bool = False,
    returns: str = "",
) -> None:
    """Wire a subcommand's `-h` to the table and its `--help` to the document.

    The subparser must be built with `add_help=False`, because argparse binds
    both spellings to one action and the whole point is that they differ.
    """
    subparser.add_argument(
        "-h",
        action="help",
        default=argparse.SUPPRESS,
        help="terse summary for a person: this verb's flags",
    )
    subparser.add_argument(
        "--help",
        action=VerbSkillAction,
        render=lambda: render_verb_skill(
            subparser, prog=prog, verb=verb, spends_money=spends_money, returns=returns
        ),
        default=argparse.SUPPRESS,
        help="this verb explained for an agent driving it",
    )


def wire_verb_help(verbs: Any, *, prog: str, model_backed: tuple[str, ...] = ()) -> None:
    """Give EVERY subcommand the same `-h` / `--help` split the root has.

    Applied as a post-pass over the subparser set rather than at each call site,
    for one reason that matters: a verb added later inherits this without anyone
    remembering to wire it. The defect this fixes had already recurred twice in
    other costumes -- a capability present in the tool and invisible to the agent
    consuming it -- and a fix that depends on the next author remembering is the
    same defect with a longer fuse.

    argparse installs its own `-h/--help` pair bound to ONE action, so the pair
    is removed first and replaced with two that differ.
    """
    for verb, subparser in getattr(verbs, "choices", {}).items():
        existing = [
            action for action in subparser._actions if set(action.option_strings) & {"-h", "--help"}
        ]
        for action in existing:
            subparser._actions.remove(action)
            for option in action.option_strings:
                subparser._option_string_actions.pop(option, None)
            for group in subparser._action_groups:
                if action in group._group_actions:
                    group._group_actions.remove(action)

        add_verb_help_flags(subparser, prog=prog, verb=verb, spends_money=verb in model_backed)


def render_pointer_skill(
    manifest: Any,
    *,
    install: tuple[tuple[str, str], ...],
    repository: str,
    author: str,
    triggers: tuple[str, ...] = (),
) -> str:
    """The installed SKILL.md: a POINTER, not a copy of `--help`.

    We used to splice the install block into the whole `--help` document and
    commit the result -- 155 lines, byte-derived from the tool, with a test
    asserting the derivation. The test was honest about what it checked and
    checked the wrong thing: it guaranteed the file matched `--help` IN OUR
    REPO AT BUILD TIME, while the two artifacts reach a user from different
    places. `npx skills add <repo>` tracks the default branch; `uv tool install
    ...@v0.5.0` is pinned. A host can hold a skill describing flags its binary
    does not have, and nothing would have caught it.

    A pointer cannot go stale, because it asserts nothing `--help` would. The
    tool's own `--help` is the skill -- printed by the binary that is actually
    installed, so it is correct by construction.

    This is the shape the smart-tool-creator scaffolds by default, and adopting
    it costs us nothing we measured: three harnesses drove this tool correctly,
    and every one of them read `--help` after the skill rather than instead of
    it.
    """
    data = manifest.to_dict() if hasattr(manifest, "to_dict") else dict(manifest)
    name = data.get("name", "tool")
    version = data.get("version", "")
    description = " ".join(str(data.get("description") or "").split())

    summary = description
    cases = data.get("use_cases") or []
    if cases:
        numbered = "; ".join(f"({i}) {' '.join(str(c).split())}" for i, c in enumerate(cases, 1))
        summary = f"{description} Use when {numbered}."
    # NO "Triggers on ..." CLAUSE, and the parameter is kept only so callers do
    # not break. A real user had to name our video tool explicitly in Codex
    # before it would be reached for, and the cause was exactly this: a trailing
    # keyword list tells a matcher to look for PHRASES rather than intent, and
    # nobody asking a real question says "deep research" out loud.
    #
    # Hand-editing the committed SKILL.md did not fix it -- this generator put
    # the clause straight back, which is what the drift test caught. The fix has
    # to live here.
    _ = triggers

    lines = [
        "---",
        f"name: {name}",
        "description: >-",
        *[f"  {line}" for line in _wrap(summary, 84).splitlines()],
        "license: MIT",
        "metadata:",
        f"  author: {author}",
        f"  repository: {repository}",
        # The version this POINTER was generated from. The pointer makes no claim
        # about the tool's behaviour, but it can still be older than the binary --
        # so it says which release it came from, and `manifest` reports what is
        # actually installed. A reader comparing the two sees a mismatch rather
        # than discovering it through a flag that does not exist.
        f"  version: {version}",
        "---",
        "",
        f"# Using {name}",
        "",
        # NOT the description again. It is already in the frontmatter directly
        # above, and repeating ~900 characters verbatim pushed this file past
        # the size guard that keeps it a POINTER rather than a copy of --help.
        _wrap(f"`{name} --help` is the real document. This file only says how to get the tool."),
        "",
        "## Install",
        "",
        _wrap(
            f"`npx skills add` installs THIS DOCUMENT, not the program. If `{name}` is "
            "not on your PATH, install it:"
        ),
        "",
        "```bash",
    ]
    for comment, command in install:
        lines += [f"# {comment}", command]
    lines += ["```"]

    # WHAT EACH THING NEEDS, spelled out here rather than discovered by failure.
    # Reported from real use: an agent hit "not configured" partway through a
    # task, had to work out which of two separate things was missing, and
    # substituted a different tool entirely. The manifest knew the answer the
    # whole time; the skill just never said it.
    requires = data.get("requires") or []
    if requires:
        needed = [r for r in requires if not r.get("optional")]
        optional = [r for r in requires if r.get("optional")]
        lines += ["", "## What needs setting up", ""]
        def _line(item: Any) -> str:
            purpose = " ".join(str(item.get("purpose", "")).split())
            return f"- **{item.get('name')}** -- {purpose.split('.')[0][:110]}."

        if needed:
            lines += ["Required:", ""] + [_line(i) for i in needed] + [""]
        if optional:
            lines += [
                "Optional -- everything else runs without them:",
                "",
                *[_line(i) for i in optional],
                "",
            ]
        lines.append(
            _wrap(
                f"`{name} config` says which of these THIS machine has and what to run "
                "for each gap. Check it before calling a capability unavailable."
            )
        )

    lines += [
        "",
        "## Use it",
        "",
        _wrap(
            f"Run `{name} --help`. It prints the tool's skill: when to reach for it, "
            "every capability, what each costs, worked invocations, how to read a "
            "result too large to hold, and the sharp edges. Follow it. Confirm every "
            f"argument against `{name} <command> --help` rather than memory -- each "
            "verb prints its own agent-facing document, and `-h` gives the terse "
            "argparse summary instead."
        ),
        "",
        _wrap(
            "That document comes from the binary you actually have, so it is correct "
            "for your installation. This file cannot be, and does not try."
        ),
        "",
        "## Staying current",
        "",
        _wrap(
            f"`{name} manifest` reports the version installed. This pointer was "
            f"generated from {version}. If they differ, the tool is the authority -- "
            "re-read `--help`, because flags and costs change between releases."
        ),
        "",
        "```bash",
        "# what you have",
        f"{name} manifest",
        "",
        "# what exists",
        f"git ls-remote --tags --refs {repository} | tail -3",
        "",
        "# upgrade in place",
        install[0][1].replace("uv tool install ", "uv tool install --force "),
        "```",
        "",
    ]
    return "\n".join(lines)
