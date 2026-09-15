---
name: deep-research
description: >-
  Answers a research question with evidence: multi-source web research, synthesised
  into a short brief, backed by citations a caller can act on. Reach for it when a
  decision needs more than one source and nobody has time to become the researcher.
  The answer is a brief plus a pointer to the full evidence on disk, so a result too
  large to hold can still be navigated.
---

# deep-research

Answers a research question with evidence: multi-source web research, synthesised into a
short brief, backed by citations a caller can act on. Reach for it when a decision needs
more than one source and nobody has time to become the researcher. The answer is a brief
plus a pointer to the full evidence on disk, so a result too large to hold can still be
navigated.

## Reach for this when

- Find out what is actually known about a question before committing to a decision
- Get a short answer with the sources behind it, without reading the sources first
- Build a durable evidence record that later questions can be answered against
- Produce a bibliography for a topic without collecting the references by hand

## Cost

Every verb below marked `deterministic` runs with **no AI provider and no credentials**,
spends nothing, and is safe to call freely -- including on a machine that has never been
configured. Only the verbs marked `model-backed` spend tokens.

## Verbs

| verb | | what it does |
|---|---|---|
| `research` | **model-backed** | answer a research question with evidence |
| `estimate` | deterministic | what a run will cost and how long, BEFORE spending |
| `check` | deterministic | whether this host has what the tool needs, and what each gap costs you |
| `config` | deterministic | the effective settings and which tier each came from |
| `list` | deterministic | runs in the runs directory, newest first |
| `status` | deterministic | one run's state, stage progress and usage |
| `read` | deterministic | a bounded slice of a run's prose; says if it is partial |
| `sources` | deterministic | a run's citations as structured data |
| `render` | deterministic | re-shape a stored run: markdown, json, bibliography |
| `classify` | deterministic | sort URLs into academic, news, docs or other |
| `manifest` | deterministic | this tool's own manifest |

## Reading the result

One JSON document on stdout. Success is {"result": ...}; failure is{"error": {"code",
"message", "remedy"}} with a non-zero exit. Progressand diagnostics go to stderr, never
stdout, so you can parse one without filtering the other. A research result is a BRIEF
plus a POINTER: `brief` is short and IS the answer, not a teaser; `path` names a run
directory that outlives the call; `inline` says whether the full report came back with
the envelope or was left on disk because it was too large. `confidence` is one of low,
medium or high and reflects what the evidence actually supports -- when it says low,
believe it.

## Going deeper without swallowing everything

Never swallow a whole run. Every response -- INCLUDING A REFUSAL -- carries
`affordances`: named next moves, each with a CLI form, a library form, what it returns,
what it costs, and whether it needs a credential. They are all $0.00 and all
credential-free, so an agent on an unconfigured host can still explore a result someone
else paid for. `read <id> --lines N` returns a bounded slice and ALWAYS carries a
completeness block: when a view is partial it says so and how much was left out, and an
over-ceiling request is refused rather than silently truncated -- so never present a
slice as the whole. `sources <id> --category academic` returns citations as filterable
data. `render <id> --format bibliography` reshapes a stored run without re-running it.
FOR A LONG RUN, use `--detach`. It returns in under a second with part one: the run id,
where the rest will appear, and an explicit `not_yet_true` list -- read that before
treating an accepted request as an answer. Then ask `status <id>` and read
`liveness.state`: `growing` means wait `poll_again_in_seconds` and ask again, `final`
means the work is done, and `abandoned` means the process is gone and nothing more is
coming, so whatever reached disk is all there will be. Poll `liveness.state`, never the
stage names.

## What it needs

- **perplexity** (optional) — 
- **ai-provider** (optional) — 

Run `deep-research check` to see which of these this host actually has. It is
deterministic, so it answers on a machine with nothing configured -- and it reports what
each missing one would unlock rather than only that it is missing.

## Examples

Find out what is known, cheaply, before committing to a decision:

```bash
deep-research estimate --query 'do state-based CRDTs converge?' --depth low
 deep-research research --query 'do state-based CRDTs converge?' --depth low
```

Read a large result without pulling all of it into context:

```bash
deep-research read dr-70ce2d29 --lines 40
 deep-research sources dr-70ce2d29 --category academic
```

Check what this host can actually do, spending nothing:

```bash
deep-research check
```
