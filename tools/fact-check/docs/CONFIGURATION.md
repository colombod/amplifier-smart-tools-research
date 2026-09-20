# Configuration

Two concerns, kept apart: **settings**, which say how the tool should behave, and
**credentials**, which are secrets.

Deterministic verbs need none of this. They run with nothing configured at all.

## Settings

Every setting resolves through four tiers, most explicit first:

| Tier | Example |
|---|---|
| 1. explicit argument | `--runs-dir /shared/evidence` |
| 2. config file | `runs_dir = "/shared/evidence"` |
| 3. environment variable | `RESEARCH_RUNS_DIR=/shared/evidence` |
| 4. built-in default | `$XDG_STATE_HOME/amplifier-research/runs` |

The config file is `~/.config/amplifier-research/config.toml`. Its location is
overridable by `RESEARCH_CONFIG`, so a deployment or a test can pin it without touching
the user's own.

**The config file sits above the environment.** A deployment that wrote a config file is
entitled to have it honoured; an environment variable can arrive by accident from a parent
process. An explicit argument still beats both, because it is the only tier typed on
purpose for this invocation.

```toml
# ~/.config/amplifier-research/config.toml
runs_dir = "/shared/evidence"
backend  = "perplexity"
depth    = "medium"
```

Settings: `runs_dir`, `engine_home`, `backend`, `depth`, `provider`, `model`,
`host_config`, `max_read_lines`, `max_attempts`, `timeout_ms`.

### The two places this tool writes

Everything it puts on disk goes to one of two paths, and both are settings:

| Setting | Holds | Default |
|---|---|---|
| `runs_dir` | the evidence: reports, sources, events, raw replies | `$XDG_STATE_HOME/amplifier-research/runs` |
| `engine_home` | what the embedded engine needs to run: prepared-bundle cache, module clones, one working directory per turn | `$AMPLIFIER_AGENT_HOME`, else `~/.amplifier-agent` |

**If your host confines writes to a workspace, point both there and you are done.** That
is the whole of it — there is no third location, and in particular nothing is written to
`$TMPDIR` any more. A turn's working directory is created inside `engine_home` and removed
when the turn ends.

```toml
runs_dir    = "/workspace/.runs"
engine_home = "/workspace/.engine"
```

`engine_home` defaults to what the engine itself would have used, so nobody who never had
a problem gets moved, and the cache — several hundred megabytes of module clones — is
shared between runs rather than rebuilt per invocation. Prefer a path that survives
between runs over a temporary one.

**If that default is unwritable and you named nothing, the tree goes inside your runs
directory** (`<runs_dir>/.engine`) rather than failing. One setting, not two: a host that
confines writes has already pointed `runs_dir` somewhere it allows, and that is a location
it chose — even if it did not choose it for this. The substitution is reported as its own
tier, `source: "fallback"`, with a `because`, in `check` and in the run's event log. It is
never silent, and `list` ignores it — a directory without a `run.json` is not a run.

Two things it deliberately will not do. **A path you named is never replaced**, only
refused: your setting doing nothing while nothing says so is the exact trap described
below. And if the runs directory is unwritable too, the refusal names *both*, so you do
not fix the second problem and meet the first one immediately afterwards.

Set `engine_home` explicitly if several machines share one runs directory — this cache is
not written to be shared.

**`AMPLIFIER_HOME` is not the lever, however much it looks like one.** The engine
overwrites that variable when it is imported, so exporting it does nothing at all.
`check` says so when it sees it set. Use `engine_home`, `RESEARCH_ENGINE_HOME`, or the
engine's own `AMPLIFIER_AGENT_HOME`.

`engine_home` has no `--flag` tier, unlike every other setting. The binding has to happen
before the engine is imported, and `--detach` starts a **separate process** that resolves
its own settings: the config file and the environment reach it, an argument would not.

A model-backed verb **refuses before it starts** when `engine_home` cannot be written to,
naming the path, the tier that chose it and the setting that moves it. That refusal
replaces the failure it was built from: a run in a sandboxed host that gathered its
evidence, paid for it, and then died on a bare `PermissionError` naming a directory
nobody had chosen. `check` reports both paths and whether each is writable, so the answer
is available before anything is spent.

### Absent and wrong-type are different things, and wrong is fatal

- **Absent** — resolution falls through to the next tier, quietly.
- **Wrong type, outside the allowed choices, an unknown setting name, or a file that
  cannot be parsed** — **fatal**: `config_invalid`, exit 2.

**TOML has no null**, so "no opinion" is spelled by *omitting the key*. There is no third,
explicitly-null case: `depth = ""` is a wrong value, not an abstention, and is refused as
one.

A caller with a config file present is entitled to have it honoured or to be told plainly
that it is broken. Silently substituting a default is how runs end up written somewhere
nobody expects — and a key naming a setting that does not exist is refused too, because a
setting nobody reads is a setting whose author believes something untrue.

### Asking which tier won

`fact-check config` prints the effective settings and, for each, where it came from —
plus anything that was seen and deliberately not honoured. Four tiers with no way to ask
which one won would be a debugging liability rather than a feature.

## Credentials

Separate, and the environment comes first — the inverse of settings, because that is what
every host already injects.

| Tier | Source |
|---|---|
| 1 | `PERPLEXITY_API_KEY`, `ANTHROPIC_API_KEY`, … |
| 2 | `~/.config/amplifier-research/credentials.toml`, permissions `0600` |
| 3 | the model provider's own resolution |

```bash
export PERPLEXITY_API_KEY=...     # evidence acquisition
export ANTHROPIC_API_KEY=...      # the reasoning stages
```

The credentials file is opt-in and deliberately **not** the settings file, so a config can
be shared or committed without carrying a secret. It is **refused unless its permissions
are 0600**:

```bash
chmod 600 ~/.config/amplifier-research/credentials.toml
```

A credential value never appears in any output, log line, event record or error message.
What a resolution reports is the tier a credential came from — never the value, never a
prefix, never a length.

### A provider needs its client library too, not only its credential

**A credential alone does not satisfy preflight.** The embedded agent engine ships no
provider client of its own, so `check-claims` also needs that provider's Python client
installed — found the hard way, by a run that preflighted clean on a resolvable
credential and then died at mount time with `No module named 'anthropic'`.

| Credential | Client library | Shipped by default? |
|---|---|---|
| `ANTHROPIC_API_KEY` | `anthropic` | yes — this tool installs it |
| `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`, a GitHub Copilot credential | `openai` | no — opt in |
| `GOOGLE_API_KEY` or `GEMINI_API_KEY` | `google-genai` | no — opt in |

To use a provider beyond the default Anthropic one, either reinstall this tool's shared
core with the matching extra:

```bash
uv pip install 'research-core[agent-openai] @ git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=packages/research-core'
# or
uv pip install 'research-core[agent-gemini] @ git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=packages/research-core'
```

or add the client library directly into the same environment:

```bash
pip install openai        # OPENAI_API_KEY, AZURE_OPENAI_API_KEY, GitHub Copilot
pip install google-genai   # GOOGLE_API_KEY, GEMINI_API_KEY
```

`check` reports both halves of this precondition — credential resolved and client library
importable — rather than only the credential, and a preflight failure names whichever
half is missing.

## What is lost without each

| Absent | Consequence |
|---|---|
| `PERPLEXITY_API_KEY` | the Perplexity backend is unavailable |
| a model provider's credential | the reasoning stages cannot run |
| a model provider's client library, credential present | preflight fails naming the missing library, same as no credential at all |
| both credential and library | every deterministic verb still works; model-backed verbs exit 3 with `no_provider` |

A model-backed verb with nothing configured fails loudly naming the missing precondition.
It never falls back to a degraded deterministic answer.
