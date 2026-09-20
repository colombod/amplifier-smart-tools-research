"""The `skill` verb renders a tool for the reader that actually calls it.

`--help` is written for a person, and a person seeing `"confidence": "low"` in
a JSON envelope knows what to do without being told. An agent does not. Measured
A/B: given only `--help`, an agent could not say what `confidence` meant --
"I grepped the doc text directly and it does not appear once". Given this
document, it answered correctly and said what it would do about a low one.

So these tests check the two things that difference turned on: the format a host
can consume, and the presence of the interpretation an agent cannot infer.
"""

from __future__ import annotations

import pytest

TOOLS = ("deep_research", "fact_check")


def _skill(name: str) -> str:
    import importlib

    return importlib.import_module(name).skill()


@pytest.mark.parametrize("tool", TOOLS)
def test_it_is_agent_skills_format(tool):
    text = _skill(tool)
    lines = text.splitlines()
    assert lines[0] == "---", "frontmatter must open the document"
    closing = lines.index("---", 1)
    front = "\n".join(lines[1:closing])
    # The two fields the spec requires, and the two a host matches on.
    assert front.startswith("name: ")
    assert "description:" in front
    assert text.count("---") >= 2


@pytest.mark.parametrize("tool", TOOLS)
def test_it_says_which_verbs_spend_money(tool):
    # The agent given `--help` needed turns to work this out; the one given the
    # skill called it "explicit and unambiguous" and moved on. Halved the calls.
    text = " ".join(_skill(tool).split())
    assert "## Cost" in text
    assert "deterministic" in text
    assert "model-backed" in text


@pytest.mark.parametrize("tool", TOOLS)
def test_it_explains_how_to_READ_the_result_not_only_how_to_call(tool):
    # The whole finding. A description that teaches calling but not believing
    # leaves an agent to present a low-confidence answer as fact.
    text = _skill(tool)
    assert "## Reading the result" in text
    assert '{"error"' in text, "the failure shape is part of the contract"


def test_deep_research_defines_confidence_because_an_agent_cannot_guess_it():
    text = _skill("deep_research")
    assert "confidence" in text
    for value in ("low", "medium", "high"):
        assert value in text
    # Not merely the values -- what to DO about the lowest one.
    assert "believe it" in text


def test_fact_check_distinguishes_unverifiable_from_refuted():
    # The distinction the tool is built around is worthless if the caller
    # collapses it. Say it where the caller reads.
    #
    # Assert on whitespace-normalised text: the document is wrapped for reading,
    # so a phrase that matters can land across a line break. A test that breaks
    # on where a line happens to fold tests the folding, not the contract.
    text = " ".join(_skill("fact_check").split())
    assert "unverifiable" in text
    assert "never reported as `refuted`" in text


@pytest.mark.parametrize("tool", TOOLS)
def test_rendering_needs_no_provider_and_no_credentials(tool, monkeypatch):
    for variable in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "PERPLEXITY_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "AZURE_OPENAI_API_KEY",
    ):
        monkeypatch.delenv(variable, raising=False)
    assert _skill(tool).startswith("---")


@pytest.mark.parametrize("tool", TOOLS)
def test_the_verb_table_matches_what_the_library_actually_exposes(tool):
    # A skill that advertises a verb the tool does not have sends an agent to
    # a usage error, which is the one failure mode this document must not have.
    import importlib

    module = importlib.import_module(tool)
    text = _skill(tool)
    for verb in module.CAPABILITIES:
        if verb == "skill":
            continue
        assert f"`{verb}`" in text, f"{verb} is a capability but absent from the skill"


@pytest.mark.parametrize("tool", TOOLS)
def test_dash_h_and_double_help_answer_different_readers(tool, capsys):
    """`-h` is the terse summary; `--help` is the skill.

    Adopted from David Koleczek's Smart Tool Creator after measuring our own
    choice and finding it worse. We had made `skill` a verb, reasoning a host
    would find it in the verb list -- but a host that does not know the tool
    reaches for `--help` first, and ours answered that with prose an agent
    could not extract result-interpretation from.
    """
    import importlib

    cli = importlib.import_module(f"{tool}.cli")

    for flag, expected in (("-h", "usage:"), ("--help", "---")):
        with pytest.raises(SystemExit) as exit_info:
            cli.build_parser().parse_args([flag])
        assert exit_info.value.code == 0, f"{flag} must exit 0"
        out = capsys.readouterr().out
        assert out.startswith(expected), f"{flag} printed the wrong document"

    # And they must genuinely differ -- one action bound to both spellings is
    # the argparse default this exists to undo.
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["-h"])
    terse = capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--help"])
    skill_text = capsys.readouterr().out
    assert terse != skill_text


@pytest.mark.parametrize(
    "tool,slug", [("deep_research", "deep-research"), ("fact_check", "fact-check")]
)
def test_the_committed_skill_file_matches_what_the_library_returns(tool, slug):
    """`skills/<name>/SKILL.md` on disk must equal `skill()`.

    The file exists so a host that discovers skills by SCANNING a repository --
    `npx skills add <owner>/<repo>`, or anything walking the tree -- finds this
    tool at all. Generated at runtime only, it was invisible to every one of
    them: we had the better content and the worse distribution, and content
    nobody can find is not content.

    A generated file committed to git is a duplication, and duplications rot.
    THIS TEST is the load-bearing part, not the file: regenerate with
    `python -c "import <pkg>; ..."` -- or just read the failure, which says so.
    """
    import importlib
    from pathlib import Path

    module = importlib.import_module(tool)
    expected = module.pointer_skill()
    path = Path(__file__).resolve().parents[3] / "skills" / slug / "SKILL.md"
    assert path.exists(), f"{path} is missing -- regenerate it from {tool}.pointer_skill()"
    assert path.read_text(encoding="utf-8") == expected, (
        f"{path} has drifted from {tool}.pointer_skill(). Regenerate it; do not hand-edit."
    )


@pytest.mark.parametrize(
    "tool,slug", [("deep_research", "deep-research"), ("fact_check", "fact-check")]
)
def test_the_installed_skill_is_a_pointer_and_not_a_copy_of_help(tool, slug, capsys):
    """The file must NOT inline `--help`, and that is a deliberate reversal.

    It used to be exactly `--help` with an install block spliced in, guarded by a
    test asserting the derivation. That test was honest about what it checked and
    checked the wrong thing: it proved the file matched `--help` IN THIS REPO AT
    BUILD TIME, while the two artifacts reach a user from different places --
    `npx skills add <repo>` tracks the default branch, `uv tool install ...@tag`
    is pinned. A host could hold a skill describing flags its binary does not
    have, and nothing here would have failed.

    A pointer cannot go stale, because it asserts nothing `--help` would.
    """
    import importlib
    from pathlib import Path

    cli = importlib.import_module(f"{tool}.cli")
    with pytest.raises(SystemExit) as exit_info:
        cli.build_parser().parse_args(["--help"])
    assert exit_info.value.code == 0
    printed = capsys.readouterr().out

    on_disk = (Path(__file__).resolve().parents[3] / "skills" / slug / "SKILL.md").read_text(
        encoding="utf-8"
    )

    # The spec puts YAML frontmatter at the top, and that is how a host learns a
    # skill's name and description -- which is to say, how it finds it at all.
    assert on_disk.startswith("---\n")

    # A pointer, not a copy. The body of --help must not be in here.
    assert len(on_disk) < len(printed) / 2, (
        "the skill file is the size of --help -- it has become a copy again, and "
        "a copy can describe flags the installed binary does not have"
    )

    # And it must send the reader to the authority. Whitespace-normalised: the
    # document is wrapped for reading, so a line break inside a command is a
    # formatting accident, not a change of meaning. Asserting the raw string
    # would make this test a hostage to the wrap width.
    flat = " ".join(on_disk.split())
    assert f"{slug} --help" in flat, "the pointer does not point anywhere"
    assert f"{slug} <command> --help" in flat, (
        "per-verb documents are where the real detail lives; the pointer must say so"
    )


@pytest.mark.parametrize(
    "tool,slug", [("deep_research", "deep-research"), ("fact_check", "fact-check")]
)
def test_the_pointer_says_which_version_it_came_from(tool, slug):
    """So a mismatch is VISIBLE rather than discovered through a missing flag.

    The pointer makes no claim about behaviour, but it can still be older or
    newer than the installed binary. It names its own version and tells the
    reader that `manifest` reports theirs, so the two can be compared.
    """
    import importlib

    module = importlib.import_module(tool)
    text = module.pointer_skill()
    version = module.manifest().to_dict()["version"]

    assert f"version: {version}" in text, "the pointer does not say which release built it"
    assert f"{slug} manifest" in text, "nothing tells the reader how to find their own version"
    assert "upgrade" in text.lower(), "a version mismatch with no remedy is just bad news"


@pytest.mark.parametrize(
    "tool,slug", [("deep_research", "deep-research"), ("fact_check", "fact-check")]
)
def test_acquisition_lives_in_the_pointer_and_never_in_help(tool, slug, capsys):
    """Two readers, two needs.

    `--help` is run by someone who already HAS the binary, so telling them how to
    obtain it is incoherent. A host that ran `npx skills add` may hold the
    document WITHOUT the program, because that command installs a document and
    not a program.

    RECORDED DISAGREEMENT, not oversight: a spec reviewer asked for install
    commands to appear in the rendered `--help`. An earlier agent implemented
    that suggestion, watched this test go red, and reverted -- correctly. The
    reasoning above is why this repo declines the reviewer's suggestion: a
    `--help` reader already HAS the binary that printed it, so "how do I get
    this" is a question that reader cannot coherently be asking, and the
    answer belongs in the artifact whose reader might actually lack the tool
    (the committed pointer `SKILL.md`, which `pointer_skill()` builds and
    which DOES carry `## Install`). If a future run of that review raises the
    same suggestion again, this comment is the answer -- re-litigate it here
    against this reasoning before touching this test, rather than "fixing" it
    by weakening or deleting the assertion.
    """
    import importlib

    cli = importlib.import_module(f"{tool}.cli")
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--help"])
    printed = capsys.readouterr().out

    assert "## Install" not in printed, (
        "`--help` is read by someone who HAS the tool; acquisition does not belong there"
    )
    assert "## Install" in importlib.import_module(tool).pointer_skill(), (
        "the pointer's reader may not have the program -- `npx skills add` "
        "installs this document, not the binary"
    )


def test_the_brief_is_bounded_because_it_is_the_proxy():
    """The brief is what a caller with no context budget gets. Six lines, stated.

    A bound nothing checks is a hope. This asserts the prompt still carries the
    limit, because the whole ladder rests on the bottom rung being small enough
    to hand to anyone.
    """
    from deep_research import prompts

    assert "Six lines at most" in prompts.SYNTHESISE
    assert "IS the answer" in prompts.SYNTHESISE


#: Flags an agent-facing skill may omit, each with the reason it is omitted.
#: An entry here is a decision somebody wrote down. Anything NOT here and not in
#: the skill is an oversight, and the test below calls it one.
SKILL_EXEMPT = {
    "--help": "it IS the skill -- documenting it inside itself is circular",
    "--quiet": "suppresses stderr progress; an agent parsing stdout is unaffected",
    "--timeout-ms": "operational knob with a sensible default; no decision for a caller",
    "--max-attempts": (
        "retry knob with a sensible default (3); documented in `research --help` "
        "via RESEARCH_CAPABILITY, not the root overview"
    ),
    "--out": "a destination path for `render`, obvious from the verb",
    "--limit": "pagination on `list`; the default is fine and the flag is discoverable",
    "--status": "a filter on `list`, same",
    "--tool": "a filter on `list`, same",
    "--url": "the sole argument of `classify`; the verb is meaningless without it",
    "--claims": "`estimate`'s fact-check variant; the fact-check skill covers it",
    "--inline": "documented as the pair `--no-inline`, which is the one worth reaching for",
    "--format": "documented in the skill's navigation text",
    "--category": "documented in the skill's navigation text",
    "--depth": "documented in the skill's examples",
    "--query": "documented in the skill's examples",
    "--detach": "documented in the skill's navigation text",
    "--lines": "documented in the skill's navigation text",
    "--sections": "documented in the skill's navigation text",
}


def _every_flag(parser) -> set[str]:
    """Every long flag the CLI actually accepts, across all verbs."""
    flags = set()
    for group in parser._subparsers._group_actions:
        for sub in group.choices.values():
            for action in sub._actions:
                flags.update(o for o in action.option_strings if o.startswith("--"))
    return flags


def test_every_flag_is_either_in_the_skill_or_exempted_on_purpose():
    """The skill is the ONLY document an agent gets. A flag missing from it does
    not exist, however well `--help` describes it.

    THIS DEFECT HAPPENED TWICE. First `--sections`, which our own completeness
    note told callers to use while the skill never mentioned it -- an agent
    followed our advice exactly and could not comply. Then `--no-scope`, added
    with carefully measured help text, invisible to every agent consumer.

    The test written after the first occurrence asserted `--sections` appears in
    the skill. It checked ONE flag while its name claimed it checked every flag,
    and it passed on the commit that introduced the second one. So this version
    enumerates the parser instead of naming favourites: a new flag with no skill
    text and no exemption FAILS here, which is the only way this stops recurring.
    """
    import deep_research
    from deep_research.cli import build_parser

    skill = deep_research.skill()
    undocumented = sorted(
        flag
        for flag in _every_flag(build_parser())
        if flag not in skill and flag not in SKILL_EXEMPT
    )
    assert not undocumented, (
        f"these flags exist but no agent can discover them: {undocumented}. "
        "Document each in the skill, or add it to SKILL_EXEMPT with the reason "
        "an agent does not need it."
    )


def test_the_exemption_list_does_not_rot():
    """An exemption for a flag that no longer exists is a stale excuse.

    Without this, SKILL_EXEMPT accumulates entries for deleted flags and quietly
    grows into a list nobody trusts -- which is how an allow-list stops being a
    record of decisions and becomes a place to hide things.
    """
    from deep_research.cli import build_parser

    stale = sorted(set(SKILL_EXEMPT) - _every_flag(build_parser()))
    assert not stale, f"SKILL_EXEMPT names flags that no longer exist: {stale}"


def test_the_skill_teaches_the_flag_that_costs_or_saves_money():
    """`--no-scope` is the one flag with a measured price on both sides."""
    import deep_research

    skill = " ".join(deep_research.skill().split())
    assert "--no-scope" in skill
    # Both halves, or a caller cannot tell when to reach for it.
    assert "37%" in skill and "6 for 6" in skill


@pytest.mark.parametrize("tool", TOOLS)
def test_every_verb_answers_h_and_help_differently(tool, capsys):
    """The split holds at EVERY level, not just the root.

    `-h` is always the terse table for a person who already knows the verb.
    `--help` is always the document for an agent deciding whether and how to
    call it. At the root that scope is the tool; at a verb it is the verb.

    This is enumerated rather than spot-checked because the same defect has now
    appeared three times -- `--sections` invisible to agents, then `--no-scope`,
    then every subcommand answering an agent with an argparse table. A check
    that names one case is how the second and third got through.
    """
    import importlib

    cli = importlib.import_module(f"{tool}.cli")
    parser = cli.build_parser()
    verbs = parser._subparsers._group_actions[0].choices

    for verb in verbs:
        outputs = {}
        for flag in ("-h", "--help"):
            with pytest.raises(SystemExit) as exit_info:
                parser.parse_args([verb, flag])
            assert exit_info.value.code == 0, f"{verb} {flag} did not exit 0"
            outputs[flag] = capsys.readouterr().out

        assert outputs["-h"].startswith("usage:"), f"{verb} -h is not the terse table"
        assert outputs["--help"].startswith("---"), (
            f"`{verb} --help` returned an argparse table, not an agent-facing "
            "document. Every verb gets one via wire_verb_help()."
        )
        assert outputs["-h"] != outputs["--help"]


@pytest.mark.parametrize("tool", TOOLS)
def test_the_root_skill_tells_an_agent_to_ask_a_verb_directly(tool):
    """An overview that does not say deeper documentation exists hides it.

    The root skill covers the tool. Each verb has more. An agent only learns
    that if the root says so -- otherwise per-verb `--help` is a capability
    nobody discovers, which is the exact defect this whole line of work exists
    to stop repeating.
    """
    import importlib

    skill = " ".join(importlib.import_module(tool).skill().split())
    assert "--help" in skill
    assert "verb" in skill.lower()
