# Agent instructions

Two smart tools — `deep-research` and `fact-check` — over one shared library, `research-core`.

## Read these before changing anything

| | |
|---|---|
| `CONTRIBUTING.md` | the dev loop, and the trap that will bite you |
| `docs/ARCHITECTURE.md` | how the pieces fit |
| `tools/*/contracts/cli.v1.md` | what callers may rely on. Changing it breaks someone |
| `evaluation/TUNING-LOG.md` | every tuning change and its measured effect |

## Before you push: `scripts/preflight.sh`, not memory

`ruff` and `pytest` passing in your own `.venv` is not evidence CI will pass.
0.10.0 went red on `main` twice (`004a623`, `c128f7e`) because the only check
that catches a version bumped in `SMART_TOOL.md` but not in the matching
`tools/*/pyproject.toml` is the external conformance kit's
`manifest-version-matches-package` rule, run against **built wheels** -- and
that kit is fetched and run only by CI's `conformance` job, never by `pytest`.
Run `scripts/preflight.sh` before every push; it mirrors `.github/workflows/ci.yml`
job by job (fresh venv, built wheels, the conformance kit fetched fresh, both
tool roots, plus the full suite re-run under `env -i` because this kind of
box may resolve real provider credentials through host auth in a way CI's
runner never does). Budget 1-2 minutes on a warm cache. See the script's own
header comment for the full mapping and its documented limitations.

Bumping the version touches seven files that must all agree (see
`scripts/bump_version.sh`'s header). Use that script; it edits all seven,
reinstalls, regenerates `SKILL.md`, and self-checks -- it never runs git.

## The rules that are not negotiable

**Deterministic verbs run with no provider and no credentials.** Not "usually" — the
conformance kit checks it and CI scrubs six provider variables to prove it. If your change
makes a deterministic verb need a credential, the change is wrong.

**The library is the tool.** The CLI parses arguments, calls the library, formats the result.
Logic in the CLI is capability the library cannot reach. A test enforces this.

**Never import the agent engine at module level.** It rewrites `AMPLIFIER_HOME` on import.
Import inside the function that needs it.

**Two write locations, both settings: `runs_dir` and `engine_home`.** Nothing may write
anywhere else — not `$TMPDIR`, not a home directory the caller never named. A host that
confines writes should have to point two settings, not discover a third at the first
model-backed stage of a run it has already paid for. `AMPLIFIER_HOME` is not the lever
(the engine overwrites it at import); `AMPLIFIER_AGENT_HOME` is, and
`packages/research-core/tests/test_engine_home.py` holds the engine to both halves of
that claim, since our refusal message states them.

**Fill a gap, never overrule an intention.** A host that named nothing gets a working
path chosen for it (inside `runs_dir`) and is told so. A host that named one that does not
work is refused, never quietly relocated — a setting that does nothing while nothing says
so is the bug we were fixing.

**Refuse rather than degrade.** This codebase would rather fail loudly than return a plausible
answer built on nothing. A gather that called no tool, a run with no sources, a citation
pointing at a source that does not exist, a claim that could not be checked for a mechanical
reason — each one **fails the run**. Do not soften any of them into a warning.

## The mistake this project made four times

Something was **declared** present and was not actually usable, and nothing noticed:

```
provider credential present   →  but no client library
tool in the mount plan        →  but never loaded
guard checking dependencies   →  checking a list that rots
guard reading a registry      →  reading one that does not exist yet
```

When you add a check, ask: **what would this report if the thing had silently failed?** If the
answer is "pass", you have written a check that verifies a request rather than a result. The
one that finally held counts the engine's own tool events and refuses when there are none.

## Quality changes are measured, not asserted

One change at a time. Run the evaluation before and after. Record both in
`evaluation/TUNING-LOG.md`, **including changes that made things worse** — entry 002's
regression was only diagnosable because exactly one thing had changed.

Do not write a fixture's wording into a prompt. That is how a tool learns the test set instead
of the skill, and it has already happened once here.

## Where things go

- Tool-specific code → `tools/<tool>/src/<pkg>/`
- Anything both tools need → `packages/research-core/src/research_core/`
- Tests → `packages/research-core/tests/`, including tests of tool packages
- Evaluation fixtures and harnesses → `evaluation/`
