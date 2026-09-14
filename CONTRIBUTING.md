# Contributing

## The dev loop

One venv at the repo root, the shared library editable, then the two tools on top of it:

```bash
uv venv
uv pip install -e packages/research-core
uv pip install --no-deps -e tools/deep-research -e tools/fact-check
```

`--no-deps` on the tools is deliberate: their `pyproject.toml` declares `research-core` by a
git URL, and without the flag uv would fetch that published copy and shadow your local edits.

**Put `.venv/bin` on `PATH` before running the conformance kit.** The kit resolves
`cli_argv[0]` on `PATH` and **skips** its five runtime checks when it cannot find the binary —
a skip that reads like a pass at a glance:

```bash
export PATH="$PWD/.venv/bin:$PATH"
```

## Before you push

```bash
uv run ruff format . && uv run ruff check . && uv run pytest -q
```

Then the kit, from a clone of [amplifier-smart-tools](https://github.com/microsoft/amplifier-smart-tools):

```bash
uv run conformance/run.py /path/to/tools/deep-research   # expect 15 pass / 0 fail / 0 skip
uv run conformance/run.py /path/to/tools/fact-check
```

A `pass: 10, skip: 5` verdict means the tool was not on `PATH`, not that it conformed.

## The one thing that will bite you

**Never import the agent engine at module level.** It rewrites `AMPLIFIER_HOME` on import,
which breaks the `loads-without-provider` conformance check and poisons unrelated code.
Import it inside the function that needs it. `tests/test_import_isolation.py` enforces this
in a subprocess, because an import that already happened cannot be un-happened in-process.

## Testing against a model

Every model-backed path is exercised through a seam that needs no provider — see
`research_core.backends.scripted` and `research_core.reasoning.ScriptedReasoner`. **A test
that needs a credential is a test nobody will run.**

For quality work, the evaluation harnesses live in `evaluation/`. Both have an `oracle` mode
(free, proves the plumbing) and an `adversary` mode (free, deliberately wrong but structurally
valid, proves the scorer can fail). Run those before spending anything on `live`.

Every tuning change goes in `evaluation/TUNING-LOG.md` with before and after scores —
**including the ones that did not help**, which is most of what makes the log worth reading.

## Conventions worth knowing

- Static versions in every `pyproject.toml`. A dynamic version makes
  `manifest-version-matches-package` **SKIP**, losing a real check silently.
- `requires[].install` points at documentation, never a command.
- Deterministic paths run with **no provider configured**. CI asserts the absence of six
  provider variables rather than assuming it.
- The CLI is thin. If it holds logic, that logic is unreachable from the library, which is a
  defect — `tests/test_library_is_the_tool.py` fails on it.
