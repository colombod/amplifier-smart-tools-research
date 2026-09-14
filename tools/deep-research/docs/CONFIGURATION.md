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

Settings: `runs_dir`, `backend`, `depth`, `provider`, `model`, `max_read_lines`,
`max_attempts`, `timeout_ms`.

### Absent, null and wrong-type are three different things

- **Absent** — resolution falls through to the next tier, quietly.
- **Explicitly `null`** — a legal "no opinion". Resolution falls through and says so.
- **Wrong type, or a file that cannot be read** — **fatal**: `config_invalid`, exit 2.

A caller with a config file present is entitled to have it honoured or to be told plainly
that it is broken. Silently substituting a default is how runs end up written somewhere
nobody expects.

### Asking which tier won

`deep-research config` prints the effective settings and, for each, where it came from —
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
