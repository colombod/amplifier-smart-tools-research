# `deep-research` CLI contract, v1

What a caller may rely on. Anything not written here is not promised, and anything
promised here changes only with a version bump.

Companion: `tools/fact-check/contracts/cli.v1.md`. Both tools share the run-artifact
format and the envelope; only their smart verb and its workflow differ.

---

## 1. Invocation

```
deep-research <verb> [options]
```

One JSON document per invocation. A **success** is on stdout. A **failure** is on
stderr, with stdout left empty -- so a caller parsing stdout for a result never has to
filter a failure envelope out of it first, and a caller who only reads stdout (as an
earlier version of this document said to) sees nothing at all on failure, which is
itself the signal to check stderr and the exit code. Diagnostics and progress are
always on stderr, never stdout, on both success and failure. Never waits on input a
caller cannot supply: with stdin closed it completes or it fails.

### Success envelope (stdout)

```json
{"result": { ... verb-specific ... }}
```

### Error envelope (stderr)

```json
{"error": {"code": "no_provider", "message": "...", "remedy": "..."}}
```

`code` is stable and branchable. `remedy` is always present and always actionable —
a caller never has to infer what to do from prose or from an empty result.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | the verb did its job — including `check` reporting that the host is broken |
| 1 | the operation failed |
| 2 | the caller asked for something impossible: bad usage, unknown verb, refused action |
| 3 | a model-backed verb was asked for with no backend configured |

A failure never exits 0. An error described in the output while exiting 0 would hide
that error from every caller that branches on status, so it does not happen.

---

## 2. The result is a brief and a pointer

Every `research` run writes a durable artifact and returns a short envelope describing
it. The envelope is bounded; the evidence is addressable.

```json
{"result": {
  "run_id": "dr-1a2b3c4d",
  "status": "complete",
  "brief": "Two independent sources support X; one dissents on grounds Y.",
  "confidence": "medium",
  "source_count": 34,
  "path": "/home/u/.local/state/amplifier-research/runs/dr-1a2b3c4d",
  "report_bytes": 184320,
  "inline": false,
  "usage": {"tokens_in": 18422, "tokens_out": 4110, "cost_usd": "0.2841"},
  "next": {
    "read_report":  "deep-research read dr-1a2b3c4d --sections 1-3",
    "list_sources": "deep-research sources dr-1a2b3c4d --category academic",
    "render":       "deep-research render dr-1a2b3c4d --format bibliography"
  }
}}
```

- `brief` is always inline and always short. It is the answer, not a teaser.
- `inline: true` means `report` is also in the envelope, because it was under the
  threshold. `inline: false` means it is on disk at `path` and `next` says how to read
  it. `--inline` forces inline; `--no-inline` forces the pointer.
- `cost_usd` is a **decimal string**, never a float. `null` means the backend did not
  report a cost — an honest unknown, never a silent `0.00`.
- `next` is part of the contract. A caller that has never seen this tool learns to
  navigate an oversized result from the result itself.

### Run directory

```
<runs-dir>/<run-id>/
├── run.json          # request, status, stage timings, backend, usage
├── brief.md          # the short answer
├── report.md         # the full synthesis
├── sources.json      # normalised, deduped, categorised citations
├── events.jsonl      # append-only stage record, one JSON object per line
└── raw/              # backend responses, verbatim, for audit
```

`run_id` is `dr-` plus eight hex characters. Stable for the life of the directory.

**Runs directory resolution**, first match wins — the same four tiers every setting uses
(§2a):

1. `--runs-dir PATH`
2. `runs_dir` in the config file
3. `$RESEARCH_RUNS_DIR`
4. `$XDG_STATE_HOME/amplifier-research/runs`, falling back to
   `~/.local/state/amplifier-research/runs`

Pointing several callers at one directory is supported and intended: results
**accumulate**, and `fact-check` reads the same format, so it can cite a run this tool
produced. Nothing reaps runs automatically — a run nobody deletes lives until someone
deletes it. `list` shows what is there.

---

## 2a. Configuration

Every setting resolves through four tiers, most explicit first:

| Tier | Example |
|---|---|
| 1. explicit argument | `--runs-dir /shared/evidence` |
| 2. config file | `runs_dir = "/shared/evidence"` |
| 3. environment variable | `RESEARCH_RUNS_DIR=/shared/evidence` |
| 4. built-in default | `$XDG_STATE_HOME/amplifier-research/runs` |

The config file is `~/.config/amplifier-research/config.toml`, and its location is
overridable by `RESEARCH_CONFIG`. **It sits above the environment**: a deployment that
wrote a config file is entitled to have it honoured, while an environment variable can
arrive by accident from a parent process.

Configurable: `runs_dir`, `engine_home`, `backend`, `depth`, `provider`, `model`,
`host_config`, `max_read_lines`, `max_attempts`, `timeout_ms`.

**Two paths, and this tool writes nowhere else.** `runs_dir` holds the evidence;
`engine_home` holds everything the embedded engine needs to run — its prepared-bundle
cache, its module clones, and one working directory per turn, created inside it and
removed when the turn ends. A host that confines writes to a workspace points both
somewhere it allows and is done. `engine_home` defaults to whatever the engine itself
would have used (`$AMPLIFIER_AGENT_HOME`, else `~/.amplifier-agent`), so a host that
never had a problem is not moved; it is several hundred megabytes and worth keeping
between runs. It has no `--flag` tier: the binding has to be in place before the engine
is imported, and a detached run is a separate process that re-resolves its own settings —
the config file and the environment reach it, an argument does not.

`AMPLIFIER_HOME` is **not** the lever, however much it looks like one: the engine
overwrites that variable when it is imported, so exporting it changes nothing. `check`
says so when it sees it set.

**When the default is unwritable and nothing named a path**, the tree goes to
`<runs_dir>/.engine` instead of failing, reported as `source: "fallback"` with a `because`
— in `check` and in the run's event log, never silently. `list` ignores it: a directory
with no `run.json` is not a run.

A path that **was** named — by the setting, the config file, or `$AMPLIFIER_AGENT_HOME` —
is never replaced, only refused. Filling a gap in an intention and overruling one are
different acts, and the second is the trap this section exists to close.

A model-backed verb **refuses up front** when no usable path exists —
`engine_unavailable`, exit 1, naming the path, the tier that chose it, the setting that
moves it, and the runs directory too when that was tried and failed as well. Refusing
before the run rather than at its first model-backed stage is the difference between an
error and a bill.

**Absent and wrong-type are different things, and wrong is fatal.** A key that is absent
falls through quietly to the next tier. A value of the wrong type, a value outside a
setting's allowed choices, a key naming a setting that does not exist, or a file that
cannot be parsed is **fatal**: `config_invalid`, exit 2. A caller with a config file
present is entitled to have it honoured or to be told plainly that it is broken, never to
be silently handed a default.

**TOML has no null**, so "no opinion" is spelled by *omitting the key* — there is no
third, explicitly-null case to distinguish. This is stated here rather than left for
someone to discover by writing `depth = ""` and watching it be refused.

A key naming a setting that does not exist is refused rather than ignored, and the error
names it. A setting nobody reads is a setting whose author believes something untrue
about their deployment.

**Credentials are separate and the environment wins.**

| Tier | Source |
|---|---|
| 1 | `PERPLEXITY_API_KEY`, `ANTHROPIC_API_KEY`, … |
| 2 | `~/.config/amplifier-research/credentials.toml`, mode `0600` |
| 3 | the model provider's own resolution |

The credentials file is opt-in and kept out of the settings file, so a config may be
shared or committed. It is **refused if its permissions are not 0600**. A credential value
never appears in any output, log line, event record or error message; only the tier it
resolved from is ever reported.

---

## 3. Verbs

Model-backed verbs are marked. Every other verb runs with **no backend configured** and
requires no credentials of any kind.

### `config` — deterministic

`deep-research config [--format json|table]`

The effective settings and, for each, **which tier it came from**:

```json
{"result": {"settings": {
  "runs_dir":  {"value": "/shared/evidence", "source": "config-file",
                "detail": "runs_dir in /home/u/.config/amplifier-research/config.toml"},
  "depth":     {"value": "medium", "source": "default"},
  "backend":   {"value": "perplexity", "source": "environment",
                "detail": "RESEARCH_BACKEND"}
 },
 "config_path": "/home/u/.config/amplifier-research/config.toml",
 "config_path_exists": true,
 "credentials": {"perplexity": "environment", "model_provider": "absent"},
 "ignored": ["RESEARCH_DEPTH was set but --depth was given on this invocation"]
}}
```

Reporting the source is the point. Four tiers with no way to ask which one won is a
debugging liability, not a feature. Anything seen and deliberately not honoured is
reported as seen and not honoured, rather than vanishing. Credentials report only the
tier they resolved from — never a value, never a prefix, never a length.

### `manifest` — deterministic

The tool's own `SMART_TOOL.md` frontmatter as structured data, read from the copy built
into the package. The declared `deterministic_smoke` capability.

### `check` — deterministic

Reports prerequisites and which backends resolve on this host. **Reporting a problem is
this verb's success** — it exits 0 whether the host is healthy or broken, because the
report is the deliverable. Each failed check carries its own `remedy`.

It also reports both paths this tool writes to — `runs_dir` and `engine_home` — each with
whether it is writable, so a confined host learns that before it spends anything:

```json
{"result": {"engine_home": {
  "path": "/workspace/.runs/.engine", "source": "fallback", "writable": true,
  "detail": "the engine's cache, module clones and per-turn working directories go here",
  "because": "/home/u/.amplifier-agent is not writable on this host and nothing named another path, ..."
}}}
```

`source` is one of the four settings tiers, or `fallback` — which is not a tier, because
no value is stated there: it is this tool saying it chose a working path rather than
failing, and where.

### `estimate` — deterministic

`deep-research estimate --query TEXT [--depth low|medium|high]`

What a run will cost and roughly how long it will take, before anything is spent. Pure
computation over the request parameters. No network, no model.

### `classify` — deterministic

`deep-research classify --url URL...`

Each URL to `academic` | `news` | `docs` | `other`. A pure table lookup, exposed because
a caller assembling its own source list wants the same categorisation the reports use.

### `list` — deterministic

`deep-research list [--runs-dir PATH] [--limit N] [--status STATUS]`

Runs in the runs directory: id, status, query, created, source count, size. Newest
first.

### `status <id>` — deterministic

Current state of one run: `queued` | `running` | `complete` | `failed`, the stage it is
in, stage timings, and usage so far. Safe to poll.

### `read <id>` — deterministic

`deep-research read <id> [--sections RANGE] [--lines N] [--part brief|report]`

A bounded view of a run's prose. Every response carries a completeness block:

```json
{"result": {"text": "...", "completeness": {
  "complete": false,
  "returned_lines": 400,
  "total_lines": 1820,
  "note": "INCOMPLETE: 1420 lines sit beyond this window. Widen --lines (max 5000) or request --sections rather than presenting this slice as the whole report."
}}}
```

A request over the ceiling is **refused** with exit 2, not silently capped. A partial
view always says it is partial. A caller can never mistake a slice for the whole.

### `sources <id>` — deterministic by default; `--verify` reaches the network

`deep-research sources <id> [--category CAT] [--format json|list] [--verify] [--verify-timeout SECONDS]`

Citations as structured data: url, title, category, and where in the report each is
used. This is the reference-navigation path — a caller can walk the evidence without
pulling the report into context.

When the backend received a source entry it could not keep — not an object, no url, a
repeat of one already kept — the result also carries `omitted` (one entry per dropped
source: `index`, `reason`). A partial result is a failure unless it says which parts
succeeded; this is where a caller finds out.

`--verify` is the one exception to this verb being deterministic and network-free: it
HEADs (falling back to GET) every source's URL and reports whether it currently
resolves. Off by default, so a caller who only wants to list what a run recorded never
pays for N round trips it did not ask for. Each source gains `reachable`
(true/false/null), `status_code`, and `checked_at`; a source that could not be checked
at all (DNS failure, timeout, no route) also gains `check_error` and `reachable: null`
-- distinct from `reachable: false`, which means the URL resolved and answered with an
error. The envelope gains `verified: true`, `reachable_count`, `unreachable_count`,
`unknown_count`. `--verify-timeout` (default 5 seconds) bounds how long one source may
take before it counts as unreachable-to-check. **Reachability is not support**: a
source can resolve and still not say what a citation claims -- this only catches the
case where it does not resolve at all. Never raises for a network failure.

### `render <id>` — deterministic

`deep-research render <id> --format markdown|json|bibliography [--out PATH]`

Re-shape a stored run. Costs nothing and spends no tokens, because the run is already
on disk. `--out` writes the artifact and returns its path instead of inlining it.

### `research` — **model-backed**

```
deep-research research --query TEXT
                       [--depth low|medium|high] [--max-sources N]
                       [--backend NAME] [--timeout-ms MS]
                       [--runs-dir PATH] [--inline|--no-inline]
```

Runs the workflow, writes the run directory, returns the brief and the pointer.

**Stages:** `scope → gather → synthesise → report`. Each stage transition appends to
`events.jsonl` and updates `run.json`.

Fails loudly with `no_provider` (exit 3) when no backend is configured. **It never falls
back to a degraded deterministic answer** — a research result that quietly wasn't
researched is worse than no result.

Exceeding `--timeout-ms` fails the run rather than returning a partial judgment. A run
that fails mid-workflow keeps its directory, with `status: "failed"` and the stage it
reached, so the evidence gathered so far is not thrown away.

---

## 4. Progress

`research` may run for minutes. While it runs it emits newline-delimited JSON progress
objects on **stderr**, one per stage transition and per tool call:

```
{"type":"stage","run_id":"dr-1a2b3c4d","stage":"gather","index":2,"of":4,"at":"..."}
{"type":"tool","run_id":"dr-1a2b3c4d","name":"web_search","status":"started","at":"..."}
{"type":"usage","run_id":"dr-1a2b3c4d","tokens_in":18422,"tokens_out":4110,"at":"..."}
```

The spec already reserves stderr for diagnostics and names progress messages as a
diagnostic category, so this is additive. A caller that ignores stderr sees exactly
today's behaviour.

**The same records are written to `events.jsonl`.** Progress is persisted, not merely
streamed — a caller that was not watching can still reconstruct what happened, which a
pure stream cannot offer.

`--quiet` suppresses the stderr stream. The file is always written.

---

## 5. `--help`

**`-h` and `--help` answer different readers.** Both exit 0 with every provider variable
scrubbed from the environment.

`-h` is the terse summary for a person: the verbs, a line each.

`--help` prints the tool as an [Agent Skill](https://agentskills.io/specification) — YAML
frontmatter carrying `name` and `description`, then a markdown body. A host can write it
straight into a skills directory. The `skill` verb returns the same document, for a caller
that would rather ask by name than by flag.

*Changed in 0.2.0. Before, `--help` printed prose. A caller that parsed that prose will need
updating; one that simply displayed it gets a better document. We measured the difference
before making it: given the prose, an agent could not say what `confidence` meant; given the
skill, it quoted the rule and planned around a low value.*

The skill answers three questions in order:

1. **How to use the tool.** Every verb, what it is for, and which are model-backed.
2. **How to use the result you get back.** What `brief`, `report`, `sources` and `path`
   are for; that `path` is durable evidence; that `cost_usd` is a string.
3. **How to navigate safely when the result is big.** `read` / `sources` / `render`,
   how slicing works, how to tell a partial view from a whole one, and how to walk the
   references without pulling the corpus into context.

Point 3 is a requirement, not a courtesy. A tool whose results exceed a caller's context
must teach the caller how to consume them, or the capability is unusable by the agents
most likely to call it.

---

## 6. Errors

| `code` | Exit | Meaning |
|---|---|---|
| `usage` | 2 | unknown verb or bad arguments |
| `refused` | 2 | the request was understood and declined; the message says why |
| `config_invalid` | 2 | the config file is unreadable, or a setting is the wrong type |
| `credentials_insecure` | 2 | the credentials file exists but its permissions are not 0600 |
| `no_provider` | 3 | a model-backed verb with no backend configured |
| `backend_error` | 1 | the backend was reached and failed |
| `run_not_found` | 1 | no such run id in this runs directory |
| `runs_dir_unusable` | 1 | the runs directory is missing or not writable |
| `timed_out` | 1 | the run exceeded its budget and was aborted |
| `manifest` | 1 | the tool's own `SMART_TOOL.md` is malformed — a defect in the tool |

A capability never silently returns the portion that worked. Partial is failure, and a
failed run says so in `run.json`.

### The result is a proxy, and the rungs above it are declared

*Added in 0.4.0.* A successful `research` envelope carries two new fields beside `next`.

`ladder` names what exists above the brief, with **real sizes read from disk** — never
estimated, `null` when unknown, because a caller can only refuse to fetch something enormous
if the number is true:

```json
"ladder": [
  {"rung": "brief",   "does": "the answer, standalone -- you already have it",
   "bytes": 24,  "cost_usd": "0.00", "ready": true},
  {"rung": "report",  "does": "the full synthesis with numbered sections",
   "bytes": 65,  "cost_usd": "0.00", "ready": true},
  {"rung": "sources", "does": "all 2 citations as filterable data",
   "bytes": 404, "cost_usd": "0.00", "ready": true},
  {"rung": "raw",     "does": "the backend's own replies, verbatim, for audit",
   "bytes": 294, "cost_usd": "0.00", "ready": true}
]
```

`affordances` are the verbs to climb, in the same shape a refusal carries, each with a CLI
form **and** a library form. Every one is `$0.00` and needs no credential.

**The brief is the proxy.** The synthesis prompt now states that explicitly: most callers read
it and nothing else, and a caller with a limited context window may be unable to afford the
report at all — so the brief is not a summary of the answer, it *is* the answer, standing
alone, in six lines at most.

**`next` is unchanged and still supported.** It is a documented contract term and a caller may
be parsing it; removing it would be a breaking change for a cosmetic gain. `affordances` is
the typed form of the same intent, and new callers should prefer it.

### Every refusal carries a way onward

*Added in 0.3.0.* An error envelope may carry `affordances`: named next moves, each with a
CLI form, a library form, what it returns, what it costs, and whether it needs a credential.

```json
{"error": {"code": "no_evidence", "message": "...", "remedy": "...",
  "affordances": [
    {"name": "check",  "does": "what this host resolves...",
     "command": "deep-research check", "call": "deep_research.check()",
     "returns": "json", "cost_usd": "0.00", "needs_credentials": false},
    {"name": "status", "does": "this run's stages and where it stopped...",
     "command": "deep-research status dr-e1f19ba2",
     "call": "deep_research.status('dr-e1f19ba2')", ...}]}}
```

A library caller reads the same list off the exception (`exc.affordances`); neither path is
second-class, because the library is the tool.

**Why this is a contract term and not a courtesy.** Hypermedia learned it expensively with
`204 No Content`: a response carrying no representation carries no way onward, and strands
the caller exactly when it most needs direction. Ours did the same. Every affordance offered
on a refusal is free and needs no credential — a caller that has just been refused may be on
a host with nothing configured, and offering it something it cannot run is offering it
nothing.

---

## 7. Guarantees

- Every capability is reachable from the library. The CLI parses arguments, calls the
  library, and formats the result. Domain logic in the CLI would be capability the
  library cannot reach, which is a defect.
- No engine or backend import happens at module load. Deterministic verbs never pay for
  a provider stack, and `--help` works with the environment scrubbed.
- This tool stores no credentials of its own.
- `research` sends the query, and whatever context is passed, to the configured backend.

---

## 8. Backlog — deliberately not in v1

- **`--detach`**: return the handle immediately and let the caller poll `status`. The
  stronger answer to the spec's long-running question and the larger build. v1 is
  attached-with-progress; the run directory and `status` verb already carry the shape
  detached mode would need, so adding it later changes no existing contract.
- **Resuming or continuing a run** — refining a completed run without starting over.
- **Automatic reaping** of old runs. Today nothing reaps; `list` shows what is there.
- **Resume of a failed run** — the run directory already holds the stage record, so the
  shape is there. When added, resume refuses loudly on a mismatched or already-completed
  run rather than silently restarting.
- **Cross-run synthesis** — answering from several accumulated runs at once, which the
  shared runs directory makes possible but v1 does not attempt.
