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

One JSON document on stdout, always. Diagnostics and progress on stderr, never stdout.
Never waits on input a caller cannot supply: with stdin closed it completes or it fails.

### Success envelope

```json
{"result": { ... verb-specific ... }}
```

### Error envelope

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

Configurable: `runs_dir`, `backend`, `depth`, `provider`, `model`, `max_read_lines`,
`max_attempts`, `timeout_ms`.

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

### `sources <id>` — deterministic

`deep-research sources <id> [--category CAT] [--format json|list]`

Citations as structured data: url, title, category, and where in the report each is
used. This is the reference-navigation path — a caller can walk the evidence without
pulling the report into context.

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

`-h` is the summary; `--help` is complete. Both exit 0 with every provider variable
scrubbed from the environment. `--help` answers three questions in order:

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
