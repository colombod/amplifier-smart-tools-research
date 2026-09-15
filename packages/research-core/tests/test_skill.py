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

    expected = importlib.import_module(tool).skill()
    path = Path(__file__).resolve().parents[3] / "skills" / slug / "SKILL.md"
    assert path.exists(), f"{path} is missing -- regenerate it from {tool}.skill()"
    assert path.read_text(encoding="utf-8") == expected, (
        f"{path} has drifted from {tool}.skill(). Regenerate it; do not hand-edit."
    )


@pytest.mark.parametrize(
    "tool,slug", [("deep_research", "deep-research"), ("fact_check", "fact-check")]
)
def test_help_output_is_byte_identical_to_the_installed_skill_file(tool, slug, capsys):
    """`--help` and `skills/<name>/SKILL.md` must be the SAME document.

    Two ways to get a tool's skill -- run `--help`, or let a host install the
    file -- and if they differ by so much as a byte, a caller who compares them
    has to work out which one is authoritative. They were briefly off by one
    trailing newline, because `print()` adds one to a string that already ends
    in a newline. Nobody would have noticed by reading.
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
    assert printed == on_disk, "--help and the installed SKILL.md have diverged"


def test_the_brief_is_bounded_because_it_is_the_proxy():
    """The brief is what a caller with no context budget gets. Six lines, stated.

    A bound nothing checks is a hope. This asserts the prompt still carries the
    limit, because the whole ladder rests on the bottom rung being small enough
    to hand to anyone.
    """
    from deep_research import prompts

    assert "Six lines at most" in prompts.SYNTHESISE
    assert "IS the answer" in prompts.SYNTHESISE
