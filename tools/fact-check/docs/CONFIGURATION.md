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

## What is lost without each

| Absent | Consequence |
|---|---|
| `PERPLEXITY_API_KEY` | the Perplexity backend is unavailable |
| a model provider | the reasoning stages cannot run |
| both | every deterministic verb still works; model-backed verbs exit 3 with `no_provider` |

A model-backed verb with nothing configured fails loudly naming the missing precondition.
It never falls back to a degraded deterministic answer.
