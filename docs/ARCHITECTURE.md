# Architecture

How the tools are built. For what a caller may rely on, see
`tools/*/contracts/cli.v1.md`. For why any of this exists, see `docs/VISION.md`.

---

## 1. Three layers

```
evidence acquisition    ResearchBackend seam — where sources come from
reasoning over evidence our stages, our prompts — where the judgment lives
artifact + navigation   deterministic, no credentials, no tokens
```

Keeping the first two apart is the load-bearing decision. A backend that both gathers and
synthesises would leave the research judgment outside the tool, and we would have shipped
an HTTP client with a manifest attached. **The backend is a source of evidence; the
stages are where the expertise lives.**

## 2. Layout

```
amplifier-smart-tools-research/
├── packages/research-core/      # everything both tools share
├── tools/deep-research/         # distribution root: smart-tool.json + package + CLI
└── tools/fact-check/            # distribution root: smart-tool.json + package + CLI
```

Two distribution roots in one repository, which the spec explicitly supports: each has
its own `smart-tool.json`, its own package definition, and exactly one `SMART_TOOL.md`.

`research-core` holds the backend seam, the run-artifact format, the envelope, the error
taxonomy, source normalisation, and the deterministic verbs. Each tool adds its own
model-backed verb and the stages that verb walks.

Because every smart tool must install from git, `research-core` is referenced as a git
dependency with a `#subdirectory=` fragment rather than a relative path — otherwise an
install of one tool cannot resolve the shared package.

## 3. The run directory is the substrate

Everything else is a view over it.

```
<runs-dir>/<run-id>/
├── run.json          THE record: request, status, pid, host, stage timings, usage
├── events.jsonl      append-only log, one JSON object per line
├── brief.md          the short answer
├── report.md         the full synthesis        (deep-research)
├── verdicts.json     one entry per claim       (fact-check)
├── sources.json      normalised, deduped, categorised citations
├── scope.json        the sharpened question, when the scope stage ran
├── attempts.json     each stage's rejected drafts and why they were rejected
├── detached.log      the child process's own output, when --detach was used
└── raw/              backend responses, verbatim, for audit
    └── gather-01.json
```

### Naming, so a caller landing here knows what it is holding

Three rules, and they are worth stating because a run directory is a public surface: a
second tool reads it (`fact-check --from-run`), and so does any agent we hand a `path` to.

| rule | |
|---|---|
| **The extension says HOW to read it** | `.json` one document · `.jsonl` one object per line, append-only · `.md` prose for a person or an agent · `.log` unstructured process output, no schema promised |
| **The name says WHAT it is** | singular for the thing itself (`report.md`), plural for a collection (`sources.json`, `verdicts.json`) |
| **A subdirectory says WHOSE it is** | `raw/` holds somebody else's bytes, verbatim. Anything at the top level is ours and has a shape we promise |

Two consequences we hold to:

- **`.log` is the only file with no schema.** Everything else is parseable, and a caller may
  rely on that. If a thing needs to be read by code, it does not get a `.log` extension.
- **`run.json` is the only file that is rewritten.** Everything else is append-only or
  written once, so a reader racing a writer sees a whole earlier version rather than half of
  a newer one.

Three properties follow, and all three are consequences rather than features:

- **Only the two smart verbs write. Every other verb reads.** That is what makes a shared
  runs directory safe for several callers at once, and why `fact-check --from-run` can
  consume a `deep-research` run with no coordination.
- **A run survives the process that made it.** The directory is created before the first
  stage and updated as stages complete, so a crash leaves evidence rather than nothing.
- **`raw/` makes runs replayable**, which is the basis of the testing strategy (§7).

The runs directory is configurable because sharing it is the point — several callers, or
several machines, pointed at one accumulating evidence store. Nothing reaps it.

## 4. Configuration

Two concerns, deliberately kept apart: **settings**, which say how the tool should
behave, and **credentials**, which are secrets.

### Settings resolution

Every setting resolves the same way, most explicit first:

```
1. an explicit argument        --runs-dir, --backend, --depth, or the library kwarg
2. the config file             ~/.config/amplifier-research/config.toml
3. an environment variable     RESEARCH_RUNS_DIR, RESEARCH_BACKEND, ...
4. the built-in default
```

The config file's own location is overridable by `RESEARCH_CONFIG`, so a deployment or a
test can pin it without touching the user's own.

**The config file sits above the environment, not below it.** That is the tmux-fleet
precedent and the reasoning is worth keeping: a deployment that wrote a config file is
entitled to have it honoured, while an environment variable can arrive by accident from a
parent process. An explicit argument still beats both, because it is the only tier the
caller typed on purpose *this time*.

Settings a caller may set: the runs directory, the default depth, the backend, the
provider and model, the read ceiling, the attempt budget, and timeouts.

### Absent and wrong-type are different things, and wrong is fatal

- **Absent** — fall through to the next tier, quietly.
- **Present but wrong type, outside a setting's choices, an unknown setting name, or a
  file that cannot be parsed** — **fatal**. A caller with a config file is entitled to
  have it honoured or to be told plainly that it is broken. Silently substituting the
  default is how someone ends up confidently writing runs into the wrong directory.

The design this follows is tmux-fleet's, which pays for it with a dedicated error type
and refuses rather than degrading. It has a third case we do not: an explicitly-null
value, a legal "no opinion" that falls through *and says so*. **TOML cannot express
null**, so here that case does not exist and "no opinion" is spelled by omitting the key.
Format chosen first, capability discovered second — the honest fix was to correct the
documentation rather than fake a null with an empty string, which would have put the
ambiguity back exactly where the trichotomy exists to remove it.

### Provenance is reportable

Resolution does not just return a value; it returns **which tier won and why**. The
`config` verb prints the effective settings with the source of each, and `check` reports
the same for anything it probes. An ambient variable that was seen and deliberately *not*
honoured is reported as seen and not honoured, rather than vanishing.

Without this, a config layer is a debugging liability: four tiers and no way to ask which
one won.

### Credentials

Separate, and not the config file's job by default. Resolution:

```
1. an environment variable     PERPLEXITY_API_KEY, ANTHROPIC_API_KEY, ...
2. a credentials file          ~/.config/amplifier-research/credentials.toml, mode 0600
3. the engine's own resolution for the model provider
```

Note the inversion: for **credentials** the environment comes first, because that is the
ecosystem norm and what every host already injects. Both reference smart tools state
plainly that they store no credentials of their own; we support a credentials file
because asking is reasonable, but it is opt-in, kept out of the settings file so a config
can be shared or committed, and **refused if its permissions are not 0600**.

A credential value never appears in any output, any log line, any event record, or any
error message. What a credential *resolution* may report is the tier it came from, never
the value.

### Two credential surfaces

| Surface | Purpose | Absent |
|---|---|---|
| `PERPLEXITY_API_KEY` | evidence acquisition | the Perplexity backend is unavailable |
| a model provider | the agent backend and the reasoning stages | model-backed verbs refuse |

Both are declared in `SMART_TOOL.md` `requires`, both optional, each stating exactly what
is lost without it. **Neither is needed for any deterministic verb** — and the config
layer itself must never require a credential to load, or every deterministic verb starts
paying for a secret it does not use.

Preflight refuses *before* a prompt is built. Absence is a loud `no_provider` naming the
variable and the remedy. It never degrades to a lesser deterministic answer — a research
result that quietly was not researched is worse than no result.

## 5. Seams

### `ResearchBackend`

```
run(query, depth, budget) -> RawEvidence
```

- **`PerplexityBackend`** — lifted from the bundle's already-portable code; its parsing,
  citation extraction and URL categorisation carry no Amplifier imports today.
- **`AgentBackend`** — an embedded `amplifier-agent` with web tools mounted.

Two implementations behind one protocol, which is what makes the provider-interface
question answerable with evidence instead of opinion.

### The engine, embedded

Orchestration is `amplifier-agent`, in-process. Four constraints, each a divergence from
what the reference smart tools do, and each with a reason:

- **Keep the tools mounted.** The reference tools run tool-less single turns and clear the
  mount plan. We filter it down to web search and fetch instead — that access is the job.
- **Stages are turns.** A stable session id plus resume-enabled handler construction is
  what lets a workflow walk its stages while keeping the thread. Within one turn the model
  already loops over tool calls by itself; that loop is not hand-rolled.
- **Progress comes from our own display implementation.** A one-method protocol with a
  closed event taxonomy, push-based. The reference tools pin it to quiet and discard
  exactly the events a long run needs.
- **Every engine import lives inside a function body.** Importing the engine package
  rewrites `AMPLIFIER_HOME` in the environment at import time. A module-level import would
  poison the environment for unrelated code, make deterministic verbs pay for a provider
  stack, and fail the conformance check that runs `--help` with the environment scrubbed.
  One cause, three symptoms.
- **Where the engine writes is ours to decide.** Left alone it puts hundreds of megabytes
  under `~/.amplifier-agent` and a scratch directory wherever `$TMPDIR` points — two
  locations the caller never chose, which is harmless on a workstation and fatal in a
  sandbox that confines writes. `engine_home` names the first, the turn's working
  directory moved inside it, and preflight proves it is writable before a token is spent.
  The lever is `AMPLIFIER_AGENT_HOME`, **not** `AMPLIFIER_HOME`: the engine overwrites
  that one at import, so exporting it does nothing — and a test holds the engine to both
  halves of that claim, because our refusal message states them.

**The rule that keeps this honest:** `research_core` imports nothing from the engine at
module level, ever.

## 6. The deterministic spine

Deterministic code runs in two places, and the second is easy to miss.

**As the verbs** — pure readers over the run directory: slice a report and attach a
completeness block, filter sources, reshape a stored run, scan the runs directory. Two
verbs do not read disk at all: cost estimation and URL classification are pure
computation over their arguments.

**Between every model turn** — the stages are not model calls in a row. Each turn is
bracketed:

```
scope        turn
             parse and validate the structure the turn was asked for
gather       backend call
             normalise, dedupe by URL, categorise, write sources.json and raw/
synthesise   turn, given the gathered sources
             check every citation marker resolves to a real source id
             reject and repair when it does not
report       render the outputs from validated parts, close the run
```

That citation check is the one that earns its keep: a model citing a source it was never
given is the characteristic failure of research tooling, and it is catchable with a set
membership test — no judgment required.

The draft → check → repair loop follows the pattern the digital-twin-universe tool
established: the model proposes a structured document, deterministic code validates it,
and a rejection feeds the specific findings back into the next attempt. When the attempt
budget is spent it fails loudly carrying every attempt, rather than returning the
least-bad draft. Partial is failure.

## 7. Testing

The layering is what makes this cheap, and it falls out rather than being built for.

- **Fixtures are directories.** A clean run, a run with a dangling citation, a run that
  failed mid-gather. Every deterministic verb and the whole validation spine is covered by
  ordinary tests with nothing mocked.
- **The smart path is tested through the seam, not through HTTP.** A scripted backend
  returns fixture evidence; an unconfigured one asserts its own run method is never
  called, which proves preflight refuses before a prompt is ever built.
- **Because `raw/` holds verbatim responses, a recorded run replays** the entire
  workflow — parsing, validation, citation checks, rendering — with zero credentials and
  zero tokens.
- **Conformance runs in CI against a built artifact with no credentials present**, per
  distribution root, from the first commit rather than at the end.

## 8. Consequences we accept

- **Nothing reaps runs.** An accumulating evidence store is the point, so the tool does
  not decide when evidence stops being useful. `list` shows what is there.
- **A full run wants both credentials.** The split that keeps the expertise inside the
  tool is also what makes it want two keys.
- **Model-backed results are not reproducible.** Same question, different day, possibly
  different answer. The run directory is what makes that auditable rather than merely
  true.
- **Prompts and context go to the configured backend and provider.** Stated plainly in
  the manifest rather than buried.
