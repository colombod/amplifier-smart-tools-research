"""Every capability's `--help` is LIBRARY-OWNED and DOCUMENTS THE WHOLE THING.

Two deviations, one enforcement mechanism. `help-comes-from-library` wants a
verb's `--help` to come from the library's own knowledge of the capability,
not from reading the argparse subparser that happens to expose it on a CLI.
`capability-skills-complete` wants every argument -- with its real default --
a worked invocation, the result shape, and the concrete failure conditions.

The cheap version of this test asserts a handful of named flags appear
somewhere in the text, which is exactly the shape of test that let
`--no-scope` ship invisible to every agent consumer even though a similar
test already existed for a different flag. So this enumerates BOTH sides
instead: every argument argparse actually accepts, and every keyword
``research_core.api``'s public function actually takes, must appear in the
capability's ``CapabilitySkill`` metadata -- by name on the CLI side, by
parameter name on the library side.
"""

from __future__ import annotations

import inspect

import pytest
from research_core import api
from research_core.verbs import _CAPABILITIES

TOOLS = ("deep_research", "fact_check")

#: The library function backing each common verb.
VERB_TO_API_FUNC: dict[str, str] = {
    "check": "check",
    "list": "list_runs",
    "status": "status",
    "read": "read",
    "sources": "sources",
    "verdicts": "verdicts",
    "render": "render",
    "classify": "classify",
    "estimate": "estimate",
    "manifest": "manifest",
    "config": "config",
}

#: Library parameters that are wiring, not a caller decision, so a capability
#: skill need not document them as an argument: `check`'s ``package`` is fixed
#: per tool (never chosen by a caller), `status`'s ``prog`` is always the
#: calling tool's own name, supplied by the CLI itself, and `manifest`'s
#: ``package`` is the same fixed-per-tool wiring as `check`'s.
INTERNAL_PARAMS: dict[str, set[str]] = {
    "check": {"package"},
    "status": {"prog"},
    "manifest": {"package"},
}


def _subparsers(tool: str):
    import importlib

    cli = importlib.import_module(f"{tool}.cli")
    parser = cli.build_parser()
    return parser._subparsers._group_actions[0].choices


def _parser_arg_names(subparser) -> set[str]:
    """Every argument a subparser accepts, spelled the way a caller spells it:
    the positional's dest, or the flag's first long spelling."""
    names = set()
    for action in subparser._actions:
        if action.dest in ("help",):
            continue
        if not action.option_strings:
            names.add(action.dest)
            continue
        flags = [o for o in action.option_strings if o.startswith("--")]
        if flags and flags[0] != "--help":
            names.add(flags[0])
    return names


@pytest.mark.parametrize("tool", TOOLS)
def test_every_common_verbs_parser_arguments_are_all_documented(tool):
    subparsers = _subparsers(tool)
    for verb, capability in _CAPABILITIES.items():
        if verb not in subparsers:
            continue  # this tool does not register this common verb (e.g. verdicts)
        parser_args = _parser_arg_names(subparsers[verb])
        documented = {a.name for a in capability.args}
        missing = parser_args - documented
        assert not missing, (
            f"{tool} {verb}: the parser accepts {sorted(missing)} which "
            "CapabilitySkill.args does not document -- an agent reading "
            "--help cannot discover it"
        )
        extra = documented - parser_args
        assert not extra, (
            f"{tool} {verb}: CapabilitySkill.args documents {sorted(extra)}, "
            "which this tool's parser does not actually accept -- a stale entry"
        )


@pytest.mark.parametrize("verb,func_name", sorted(VERB_TO_API_FUNC.items()))
def test_every_common_verb_documents_every_public_library_parameter(verb, func_name):
    # The reviewer's finding, generalised: a generated skill that derives only
    # from the CLI parser can omit a parameter the PUBLIC LIBRARY actually
    # accepts. Cross-checking the library signature directly is what closes
    # that gap rather than trusting the parser to have kept up with it.
    capability = _CAPABILITIES[verb]
    documented_params = {a.param for a in capability.args}
    excluded = INTERNAL_PARAMS.get(verb, set())

    signature = inspect.signature(getattr(api, func_name))
    library_params = {name for name in signature.parameters if name not in ("self", *excluded)}

    missing = library_params - documented_params
    assert not missing, (
        f"api.{func_name} accepts {sorted(missing)}, which the {verb!r} "
        "capability skill does not document"
    )
    stale = documented_params - library_params
    assert not stale, (
        f"the {verb!r} capability skill documents {sorted(stale)} as library "
        f"parameters, but api.{func_name} does not accept them"
    )


@pytest.mark.parametrize("tool", TOOLS)
def test_read_help_exits_cleanly_via_capability_skill(tool):
    # The concrete miss the reviewer named: `read --part` defaults to
    # `report`, invisible in the old generic renderer. This only proves the
    # capability-owned path is wired for both tools; the default itself is
    # checked below against deep-research's actual --help output.
    import importlib

    cli = importlib.import_module(f"{tool}.cli")

    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["read", "--help"])


def test_deep_research_render_help_states_its_real_default(capsys):
    import deep_research.cli as cli

    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["render", "--help"])
    text = capsys.readouterr().out
    assert "markdown" in text, "render --format's default must be visible in --help"
    assert "## Worked invocation" in text
    assert "## Result" in text
    assert "## Failures" in text


def test_deep_research_read_help_states_its_real_default_value(capsys):
    import deep_research.cli as cli

    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["read", "--help"])
    text = capsys.readouterr().out
    assert "report" in text, "read --part's default must be visible in --help"


def test_capability_help_is_not_derived_from_the_subparser_description():
    # help-comes-from-library: the rendered document must not depend on the
    # argparse subparser's own description text -- it comes from
    # CapabilitySkill, a library-owned object with no argparse in it.
    from research_core.skill import render_capability_skill
    from research_core.verbs import _CAPABILITIES

    text = render_capability_skill(_CAPABILITIES["read"], prog="deep-research")
    assert "deep-research read" in text
    assert "## Required" in text
    assert "## Optional" in text


# -- each tool's PRIMARY capability: `research` and `check-claims` ----------
#
# Unlike the nine verbs above, these are declared directly on each tool's own
# CLI rather than through `research_core.verbs.register` -- they are the one
# capability each tool exists for, and the two that most need the full
# document. Both used to fall back to the generic, argparse-subparser-derived
# renderer because neither had a `CapabilitySkill` wired; the tests below
# hold that fixed the same way the common verbs above are held.

#: (verb name, the public library function backing it), keyed by the
#: importable tool package -- mirrors `VERB_TO_API_FUNC` above, but pointed at
#: each tool's own module instead of `research_core.api`.
PRIMARY_CAPABILITY: dict[str, tuple[str, str]] = {
    "deep_research": ("research", "research"),
    "fact_check": ("check-claims", "check_claims"),
}

#: Library parameters that are wiring or a Python-embedding seam, not a
#: caller decision reachable from the CLI: `reasoner` and `stream` have no CLI
#: spelling at all (a `Reasoner` object, a writable stream), and `run_id` is
#: how the detached child resumes the identifier its parent already
#: published -- never a caller's own choice. `max_attempts` used to be listed
#: here too ("a real tunable with no CLI flag yet"), which was exactly the gap
#: a spec reviewer named: a real library parameter, invisible to every agent
#: reading `--help`. It now has a `--max-attempts` flag and an `ArgSpec` on
#: both `RESEARCH_CAPABILITY` and `CHECK_CLAIMS_CAPABILITY`, so it is no
#: longer excluded here -- the cross-check below is what holds it in place.
PRIMARY_INTERNAL_PARAMS: set[str] = {"reasoner", "stream", "run_id"}


def _primary_capability(tool: str):
    subparsers = _subparsers(tool)
    verb, func_name = PRIMARY_CAPABILITY[tool]
    capability = subparsers[verb]._defaults.get("_capability_skill")
    assert capability is not None, (
        f"{tool} {verb}: not wired to a CapabilitySkill -- `--help` would fall "
        "back to the generic, argparse-subparser-derived renderer"
    )
    module = __import__(tool)
    return verb, capability, subparsers[verb], getattr(module, func_name)


@pytest.mark.parametrize("tool", sorted(PRIMARY_CAPABILITY))
def test_the_primary_capability_documents_every_parser_argument(tool):
    verb, capability, subparser, _func = _primary_capability(tool)
    parser_args = _parser_arg_names(subparser)
    documented = {a.name for a in capability.args}
    missing = parser_args - documented
    assert not missing, (
        f"{tool} {verb}: the parser accepts {sorted(missing)} which "
        "CapabilitySkill.args does not document -- an agent reading "
        "--help cannot discover it"
    )
    extra = documented - parser_args
    assert not extra, (
        f"{tool} {verb}: CapabilitySkill.args documents {sorted(extra)}, "
        "which this tool's parser does not actually accept -- a stale entry"
    )


@pytest.mark.parametrize("tool", sorted(PRIMARY_CAPABILITY))
def test_the_primary_capability_documents_every_public_library_parameter(tool):
    # The reviewer's finding, generalised to the two capabilities most worth
    # generalising it to: a skill derived only from the CLI parser can omit a
    # parameter the PUBLIC LIBRARY FUNCTION actually accepts.
    verb, capability, _subparser, func = _primary_capability(tool)
    documented_params = {a.param for a in capability.args}

    signature = inspect.signature(func)
    library_params = {name for name in signature.parameters if name not in PRIMARY_INTERNAL_PARAMS}

    missing = library_params - documented_params
    assert not missing, (
        f"{tool}.{func.__name__} accepts {sorted(missing)}, which the "
        f"{verb!r} capability skill does not document"
    )
    stale = documented_params - library_params
    assert not stale, (
        f"the {verb!r} capability skill documents {sorted(stale)} as library "
        f"parameters, but {tool}.{func.__name__} does not accept them"
    )


@pytest.mark.parametrize("tool", sorted(PRIMARY_CAPABILITY))
def test_the_primary_capability_renders_through_help_not_the_fallback(tool, capsys):
    # The concrete gap this closes: `research` and `check-claims` rendered
    # `--help` through `render_verb_skill` -- the generic renderer derived
    # from the argparse subparser -- because neither had been wired to a
    # `CapabilitySkill`. Only `render_capability_skill`'s own document ever
    # produces these three section headers from library-owned metadata, so
    # their presence is proof of which renderer actually ran.
    import importlib

    verb, _func_name = PRIMARY_CAPABILITY[tool]
    cli = importlib.import_module(f"{tool}.cli")

    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([verb, "--help"])
    text = capsys.readouterr().out
    assert "## Worked invocation" in text
    assert "## Result" in text
    assert "## Failures" in text
