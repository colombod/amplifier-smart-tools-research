# Research smart tools

Two [smart tools](https://github.com/microsoft/amplifier-smart-tools) for evidence work:

| | |
|---|---|
| **`deep-research`** | Answers a research question with evidence — a short brief plus a pointer to the full evidence on disk. |
| **`fact-check`** | Checks claims against evidence, one auditable verdict per claim. |

They share one library and one runs directory, so `fact-check` can check claims against
evidence `deep-research` already gathered instead of paying to gather it again.

**Most of what these tools do needs no AI provider and no credentials.** Reading runs,
walking citations, filtering verdicts, re-rendering a report, estimating a cost — all
deterministic, all free. Only `research` and `check-claims` call a model, and they say so
before they spend anything.

---

## Install

Each tool installs on its own, no checkout required:

```bash
uv pip install "deep-research @ git+https://github.com/colombod/amplifier-smart-tools-research@main#subdirectory=tools/deep-research"
uv pip install "fact-check    @ git+https://github.com/colombod/amplifier-smart-tools-research@main#subdirectory=tools/fact-check"
```

Both pull the shared `research-core` automatically. Python 3.11+.

## Start here — this part costs nothing

```bash
deep-research check          # what's configured, what isn't, and what you lose without it
deep-research -h             # terse summary for a person: the verbs, a line each
deep-research --help         # the tool's skill, written for an agent driving it
```

**`-h` and `--help` answer different readers, on purpose.** `-h` is the usual verb summary.
`--help` prints the tool as an [Agent Skill](https://agentskills.io/specification) — YAML
frontmatter plus markdown, covering which verbs spend money, how to read a result and what
each field means, and how to navigate a large one. A host can write it straight into a skills
directory; `deep-research skill` returns the same document if you would rather ask by name.

We measured that difference before adopting it: given only the prose help, an agent could not
say what a result's `confidence` field meant; given the skill, it quoted the rule and planned
around a low one.

`check` works on a machine with no credentials at all and tells you exactly what each
missing one would unlock. Nothing else in this README requires you to have configured
anything yet.

## A research run

```bash
export PERPLEXITY_API_KEY=...        # or an ANTHROPIC/OPENAI/GEMINI key for --backend agent
deep-research estimate --query "do state-based CRDTs converge?" --depth low
deep-research research  --query "do state-based CRDTs converge?" --depth low
```

`estimate` tells you the cost before you spend it. `research` streams progress to stderr
while it runs and returns **a brief plus a pointer**, never a wall of text:

```json
{"result": {
  "run_id": "dr-70ce2d29",
  "brief": "State-based CRDTs converge under proved conditions [s1]...",
  "path": "~/.local/state/amplifier-research/runs/dr-70ce2d29",
  "source_count": 3,
  "inline": false,
  "usage": {"tokens_in": 6097, "tokens_out": 3672, "cost_usd": "0.041082"},
  "next": {
    "read_report":  "deep-research read dr-70ce2d29",
    "list_sources": "deep-research sources dr-70ce2d29",
    "render":       "deep-research render dr-70ce2d29 --format bibliography"
  }
}}
```

Every command in `next` is deterministic — it costs nothing, spends no tokens and needs no
credentials. They are also **tested to actually run**, because a navigation hint that
doesn't work is worse than no hint.

```bash
deep-research read    dr-70ce2d29 --lines 40      # a bounded slice; says if it's partial
deep-research sources dr-70ce2d29 --category academic
deep-research render  dr-70ce2d29 --format bibliography
```

## Checking claims against what you already gathered

```bash
fact-check check-claims --from-run dr-70ce2d29 \
  --claim "CRDTs converge without coordination." \
  --claim "CRDTs are the best data structure."
```

```json
{"result": {
  "run_id": "fc-7c26fe85",
  "inherited_from": "dr-70ce2d29",
  "tally": {"supported": 1, "refuted": 0, "unverifiable": 0, "opinion": 1},
  "next": {"read_verdicts": "fact-check verdicts fc-7c26fe85"}
}}
```

**`unverifiable` is a real verdict**, meaning *checked, and the evidence was inadequate*.
It is never reported as `refuted` — asserting falsehood from absence is the error this tool
exists to prevent. A claim the tool could not check for a mechanical reason **fails the
run** rather than being quietly filed under `unverifiable`.

Each verdict carries the claim, the reasoning and the source ids it rests on, so you can
audit any single one without reading the rest:

```bash
fact-check verdicts fc-7c26fe85 --verdict refuted
```

## Use it as a library

The CLI is a thin wrapper. **Everything it can do, the library can do** — with ordinary
arguments and ordinary return values:

```python
import deep_research

deep_research.check()["ready"]
run = deep_research.research(query="do state-based CRDTs converge?", depth="low")
deep_research.sources(run["run_id"], category="academic")
```

Importing pulls in no provider stack and needs no credentials. A test asserts every CLI verb
has a library equivalent, so the wrapper can't grow a capability the library lacks.

## Configuration

Four tiers, highest first: **argument → config file → environment → default**. Ask what is
in effect and where each value came from:

```bash
deep-research config
```

`~/.config/amplifier-research/config.toml` holds settings. **Credentials invert the order** —
environment first, then `credentials.toml`, which is refused if its permissions are wider
than `0600`. Credential *values* are never printed; only the tier they came from.

Point several callers at one `runs_dir` and evidence accumulates. Nothing reaps it; that is
the point.

## Where runs live

`$XDG_STATE_HOME/amplifier-research/runs`, or `~/.local/state/...`. Override per call with
`--runs-dir`, or set `RESEARCH_RUNS_DIR`. A run directory holds the brief, the report, the
sources, the verdicts, the raw backend replies and an event log of everything that happened.

## Maturity — stated plainly

- Both distribution roots pass the [conformance kit](https://github.com/microsoft/amplifier-smart-tools)
  **15/15 with no credentials configured**, re-proved by CI on every push — including a job
  that installs each root alone from git with no checkout present.
- 210 tests. Every model-backed path is exercised through a seam with no provider and no
  spend.
- Both model-backed verbs are **live-verified** end to end.
- Judgment quality is measured, not asserted: see [`evaluation/`](evaluation/). The most
  recent live pass on a fixture set whose evidence contradicts itself scored **11/12 with
  zero critical confusions** — a critical confusion being a claim the evidence doesn't
  settle coming back as `refuted`.
- **Not yet measured:** whether `deep-research`'s scope stage helps. It costs a turn and
  rewrites your question before the backend sees it, and nobody has run the other arm.

## Reading further

| | |
|---|---|
| [`docs/VISION.md`](docs/VISION.md) | why these exist and who they are for |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | how they are put together |
| [`docs/DESIGN-NOTE-one-abstraction.md`](docs/DESIGN-NOTE-one-abstraction.md) | why evidence-gathering and reasoning are two seams, not one |
| [`tools/*/contracts/cli.v1.md`](tools/deep-research/contracts/cli.v1.md) | what callers may rely on |
| [`evaluation/README.md`](evaluation/README.md) | how quality is measured, and how to run it |
| [`evaluation/TUNING-LOG.md`](evaluation/TUNING-LOG.md) | every tuning change, including the ones that failed |

## Exit codes

`0` the verb did its job (including reporting that something is broken) · `1` the operation
failed · `2` the request was impossible or refused · `3` a model-backed verb was asked for
with no provider configured.
