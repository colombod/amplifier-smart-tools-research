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

**Run `scripts/preflight.sh`. Do not run the steps below by hand instead.**

```bash
scripts/preflight.sh
```

This is the one command that reproduces what CI actually gates on. The 0.10.0
release went red on `main` twice (`004a623`, `c128f7e`) because the local dev
loop -- `ruff` + `pytest` in your own `.venv` -- is green in exactly the
situation the CI `conformance` job is not: a version bumped in
`SMART_TOOL.md` but not in the matching `tools/*/pyproject.toml`. `pytest`
never runs the external conformance kit; only CI's `conformance` job does,
and only against **built wheels**, not your editable install. `ruff` and
`pytest` passing locally has never been sufficient evidence that CI will
pass -- `scripts/preflight.sh` is.

It builds both tool wheels, installs them (not your editable checkout),
fetches the conformance kit fresh, and runs it against both tool roots --
plus the full `test` job (ruff + pytest) in a fresh venv, run TWICE: once
normally and once with the environment scrubbed (`env -i`), because this
box may resolve real provider credentials through host auth in a way a
GitHub Actions runner never does. See the comment block at the top of the
script for the full job-by-job mapping to `.github/workflows/ci.yml`, the
`install-from-git` job's pre-push limitation, and the `PREFLIGHT_SPEC_KIT_DIR`
override.

**Cost:** budget 1-2 minutes on a warm `uv` cache (network fetch of the
conformance kit dominates); a few seconds more on a cold one. Not a
pre-commit hook -- a pre-push gate. Run it before pushing anything that
touches a version, a manifest, or a generated `SKILL.md`; you do not need it
for every save.

If you want to run the pieces individually anyway (debugging the script
itself, say):

```bash
uv run ruff format . && uv run ruff check . && uv run pytest -q
```

Then the kit, from a clone of [amplifier-smart-tools](https://github.com/microsoft/amplifier-smart-tools):

```bash
uv run conformance/run.py /path/to/tools/deep-research   # expect 15 pass / 0 fail / 0 skip
uv run conformance/run.py /path/to/tools/fact-check
```

A `pass: 10, skip: 5` verdict means the tool was not on `PATH`, not that it conformed.
But note that this manual path is exactly what let two releases through red --
prefer `scripts/preflight.sh`, which cannot be run half-way.

## Bumping the version

**Run `scripts/bump_version.sh NEW_VERSION`. Do not hand-edit the seven files it touches.**

One release version has to agree across seven files (`VERSION`, three
`pyproject.toml`s, two `SMART_TOOL.md`s, two generated `SKILL.md`s --
`scripts/bump_version.sh`'s header lists them exactly). `scripts/bump_version.sh`
is now the single place that edits all seven, reinstalls into your `.venv` so
the installed distribution metadata matches, regenerates both `SKILL.md`
files, and self-checks with the two tests that guard this
(`test_manifest_version_matches_package_version`,
`test_the_committed_skill_file_matches_what_the_library_returns`). It never
touches git -- review the diff and commit it yourself. Run
`scripts/preflight.sh` afterwards as usual before pushing.

This does **not** make any `pyproject.toml`'s version `dynamic` -- every file
still carries a plain static string, so the conformance kit's
`manifest-version-matches-package` rule still evaluates to PASS/FAIL rather
than silently SKIPping (see the comment in
`packages/research-core/pyproject.toml` and the header of
`scripts/bump_version.sh` for why that distinction matters). What changes is
*who* edits the seven files -- the script, not a human doing it seven times.

## Things that will bite you

**Never import the agent engine at module level.** It rewrites `AMPLIFIER_HOME` on import,
which breaks the `loads-without-provider` conformance check and poisons unrelated code.
Import it inside the function that needs it. `tests/test_import_isolation.py` enforces this
in a subprocess, because an import that already happened cannot be un-happened in-process.

**`skills/<slug>/SKILL.md` is GENERATED -- never hand-edit it.** It is committed so a host that
discovers skills by scanning the repo (`npx skills add`) can find the tool at all, but the
source of truth is `<tool>.pointer_skill()`. Editing the source description (a tool's
`SMART_TOOL.md`, `TRIGGERS`, or anything `pointer_skill()` renders) without regenerating the
file leaves it drifted, and `test_the_committed_skill_file_matches_what_the_library_returns` in
`packages/research-core/tests/test_skill.py` fails the build -- this has already happened
twice (commits `35e9d89`, `10b766e`). Regenerate after any such change:

```bash
uv run python -c "import deep_research, pathlib; pathlib.Path('skills/deep-research/SKILL.md').write_text(deep_research.pointer_skill(), encoding='utf-8')"
uv run python -c "import fact_check, pathlib; pathlib.Path('skills/fact-check/SKILL.md').write_text(fact_check.pointer_skill(), encoding='utf-8')"
```

Then re-run the test above to confirm it lands clean before you push.

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
  Use `scripts/bump_version.sh` to change the version everywhere it appears
  without hand-editing seven files; it keeps every value static.
- `requires[].install` points at documentation, never a command.
- Deterministic paths run with **no provider configured**. CI asserts the absence of six
  provider variables rather than assuming it.
- The CLI is thin. If it holds logic, that logic is unreachable from the library, which is a
  defect — `tests/test_library_is_the_tool.py` fails on it.
