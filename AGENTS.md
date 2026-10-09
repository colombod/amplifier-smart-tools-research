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

**Never import the optional Agent runtime at module level.** Deterministic users must
not load the provider stack. Import inside the function that needs it.

**Two write locations, both settings: `runs_dir` and `engine_home`.** Nothing may write
anywhere else — not `$TMPDIR`, not a home directory the caller never named. A host that
confines writes should have to point two settings, not discover a third at the first
model-backed stage of a run it has already paid for. `AMPLIFIER_HOME` is not the lever
for public Agent state placement. Preserve `AMPLIFIER_AGENT_HOME` as this tool's
legacy default alias: config file > `RESEARCH_ENGINE_HOME` > inherited
`AMPLIFIER_AGENT_HOME` > `~/.amplifier-agent`. Temporarily remove the legacy key
only while discovering/constructing the upstream Agent and always restore it;
upstream v0.22 does not recognize that key. Pass public `working_directory` and
`sessions_directory` beneath it. The public binding no longer mutates the host
environment on import, and tests hold that fact directly.

**Use only the public Agent API, pinned to v0.22.0.** The Python distribution is
`#subdirectory=packages/python`, with the same-tag engine dependency at
`packages/engine`. Use typed options and turns, explicit `web_search` / `web_fetch`
only for gathering, narrow approvals, and `tool_error_policy="stop"`. Count real
`tool_call` events and refuse zero-tool gathers. On timeout, cancel and join the
event consumer through terminal before closing handles and removing workspace.
Unknown usage stays unknown through `StageResult` and `RunWriter`; additive
`components`, `known_subtotals`, and `complete` fields distinguish observations
from complete totals. Currencies are never relabelled as USD.
Legacy-environment discovery/construction is serialized with one process-wide
thread lock, acquired nonblocking with async waits, across loops and threads.
Count completed correlated `tool_result` records separately from tool calls;
gathering refuses when no tool completed.
Provider/model policy: Anthropic may inherit the public upstream model default.
Any other selected provider must name a model; refuse actionably in preflight
and again at turn admission. Never replace an explicit model or effort.

Agent turns run in an owned separate process group (`research_core.agent_worker`).
Request serialization precedes launch; asynchronous subprocess pipe delivery is
owned by the deadline supervisor, including broken-pipe cleanup. A result and
settled receipt never authorize success when the worker exit status is nonzero.
Retain that workspace and report exit status.
Parent timeout includes worker startup; SIGTERM requests cancellation, with a
30-second graceful budget, then SIGKILL and one-second exit verification.
Never replay. Parent callbacks are disabled after their first exception and
cannot override timeout/cancellation. Delete a workspace only after a settled
receipt, verified child exit, and absent owned process group. Otherwise retain
and report its path/PID. Arbitrarily blocking synchronous caller callbacks are
not bounded by this process policy. Upstream `run_orchestrator` and
`emit_raw_field_if_configured` coroutine warnings remain unsuppressed.

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
