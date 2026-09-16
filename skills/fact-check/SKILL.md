---
name: fact-check
description: >-
  Checks claims against evidence and returns a verdict per claim -- supported,
  refuted, unverifiable or opinion -- with the sources each verdict rests on. Reach
  for it when something asserts several things and you need to know which of them
  hold, rather than whether the piece as a whole sounds right. Claims are checked
  independently, so one false claim does not condemn the rest.
---

## Install

You may be reading this without having `fact-check` yet -- `npx skills add` installs this document, not the program.

```bash
# as a CLI
uv tool install 'git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/fact-check'
# as a library, from another project
uv add 'fact-check @ git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/fact-check'
# once, without installing
uvx --from 'git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/fact-check' fact-check --help
```

# fact-check

Checks claims against evidence and returns a verdict per claim -- supported, refuted,
unverifiable or opinion -- with the sources each verdict rests on. Reach for it when
something asserts several things and you need to know which of them hold, rather than
whether the piece as a whole sounds right. Claims are checked independently, so one
false claim does not condemn the rest.

## Reach for this when

- Check the claims in a document or a draft before it goes out
- Find which of several assertions actually hold, and which merely sound right
- Audit a single verdict down to the sources it rests on
- Re-check claims against evidence a previous research run already gathered

## Cost

Every verb below marked `deterministic` runs with **no AI provider and no credentials**,
spends nothing, and is safe to call freely -- including on a machine that has never been
configured. Only the verbs marked `model-backed` spend tokens.

## Verbs

| verb | | what it does |
|---|---|---|
| `check-claims` | **model-backed** | assess claims against evidence, one verdict per claim |
| `verdicts` | deterministic | a run's verdicts, filterable by verdict |
| `estimate` | deterministic | what a check will cost and how long, BEFORE spending |
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
"message", "remedy"}} with a non-zero exit. The `tally`travels inline because it is
small and it IS the answer; the per-claim detail stays on disk. VERDICT MEANINGS MATTER
HERE: `supported` and `refuted` mean the evidence says so; `unverifiable` means the
claim was CHECKED and no adequate evidence was found either way -- it is never reported
as `refuted`, and you must not read it as one. `opinion` means the claim is not
checkable against evidence at all. A claim the tool could not check for a mechanical
reason FAILS the run rather than being filed under `unverifiable`.

## Going deeper without swallowing everything

Never swallow a whole run. Every response -- INCLUDING A REFUSAL -- carries
`affordances`: named next moves, each with a CLI form, a library form, what it returns,
what it costs, and whether it needs a credential. They are all $0.00 and all
credential-free. `verdicts <id>` returns every verdict as data and `--verdict refuted`
filters to the ones a caller usually acts on; each carries the claim, the reasoning and
the source ids it rests on, so you can audit one without reading the rest. `read <id>
--lines N` always carries a completeness block -- when a view is partial it says so and
by how much, so never present a slice as the whole. Evidence is not gathered here: pass
`--from-run <id>` to reuse a deep- research run that already has sources, which is the
point of a shared runs directory.GO DEEPER PER VERB. This document covers the tool;
every verb has its own. `<verb> --help` returns that verb's agent-facing document --
what it does, whether it spends money, every flag and what it is FOR, and how to read
what comes back. `<verb> -h` is the terse flag table for a person. The split holds at
every level: -h is always for a human who already knows the verb, --help is always the
document for an agent deciding whether and how to call it. When you are about to call
something and want more than this overview gives you, ask the verb directly.WHEN THE RUN
IS LONG. This verb makes ONE MODEL CALL PER CLAIM, so its wall-clock scales with the
claim count rather than being fixed. Measured: two claims took 42 seconds and $0.15. Our
own estimator predicts 330 seconds for three claims and 959 for ten -- it is PESSIMISTIC
here, where the same estimator is optimistic for research, so treat both as rough. If
your per-call limit is tight or the claim list is long, pass `--detach`: it returns part
one in about a second with the run id and an explicit `not_yet_true` list, and you
rejoin with `status <id>`. `liveness.state` is `growing` while work continues, `final`
when it is done, and `abandoned` when the process is gone and nothing more is coming --
that last one is TERMINAL, so stop polling. Whatever reached disk before a death stays
readable, so a dead run is usually salvageable rather than a total loss. THE WAIT IS
YOURS TO SHAPE: `poll_again_in_seconds` is a hint about when new work will exist, not an
instruction to sleep that long inside one call, and polling more often is free because
`status` is deterministic and needs no credential.

## What it needs

- **perplexity** (optional) — 
- **ai-provider** (optional) — 

Run `fact-check check` to see which of these this host actually has. It is
deterministic, so it answers on a machine with nothing configured -- and it reports what
each missing one would unlock rather than only that it is missing.

## Examples

Check claims against evidence another run already gathered:

```bash
fact-check check-claims --from-run dr-70ce2d29 \
 --claim 'CRDTs converge without coordination.' \
 --claim 'CRDTs are the best data structure.'
```

Look at only the claims the evidence contradicted:

```bash
fact-check verdicts fc-7c26fe85 --verdict refuted
```
