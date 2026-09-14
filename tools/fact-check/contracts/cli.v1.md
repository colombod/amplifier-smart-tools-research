# `fact-check` CLI contract, v1

What a caller may rely on. Anything not written here is not promised.

**Shared with `deep-research`** — identical, not merely similar, because both tools are
built on `research-core`: the success/error envelope, the exit-code set, the runs
directory and its resolution order, the four-tier configuration model and its separate
credential resolution, the run-artifact format, the progress convention, the `--help`
contract, and the deterministic verbs `config`, `manifest`, `check`, `estimate`,
`classify`, `list`, `status`, `read`, `sources`, `render`. See
`tools/deep-research/contracts/cli.v1.md` §1–§7 for all of it; this document specifies
only what differs.

Configuration is shared in the strongest sense: both tools read the **same** config file
and the same credentials file, so a deployment configures the pair once. Only the
`RESEARCH_CONFIG` override and the settings themselves are common; nothing is per-tool.

**Why this is a separate tool.** Fact-checking is not a shallower research run. It
starts from claims rather than a question, it fans out per claim, and its result is a
verdict per claim rather than a synthesis. The two workflows are different graphs, not
different parameters of one graph. One shared library, two contracts.

---

## 1. What differs

`run_id` is `fc-` plus eight hex characters.

The run directory carries `verdicts.json` in place of `report.md`:

```
<runs-dir>/<run-id>/
├── run.json
├── brief.md          # the headline: how many claims held, how many failed
├── verdicts.json     # one entry per claim — the primary artifact
├── report.md         # the narrative write-up, generated from the verdicts
├── sources.json      # evidence used, shared format with deep-research
├── events.jsonl
└── raw/
```

Because the runs directory is shared and the source format is common, a `fact-check`
run may cite a `deep-research` run that already exists rather than re-gathering the same
evidence. That is the payoff of one accumulating evidence store.

---

## 2. `check-claims` — **model-backed**

```
fact-check check-claims (--claim TEXT... | --claims-file PATH | --from-run ID)
                        [--strict] [--backend NAME] [--timeout-ms MS]
                        [--runs-dir PATH] [--inline|--no-inline]
```

**Stages:** `triage → verify (per claim) → compile`.

- **triage** sorts each claim into `simple` | `complex` | `opinion` | `context`.
  `--strict` escalates every claim to `complex`, which is slower and more expensive and
  says so in `estimate`.
- **verify** runs per claim. Claims are independent, so this stage fans out; each claim's
  verdict lands in `verdicts.json` as it completes rather than at the end.
- **compile** produces the brief and the narrative report from the verdicts.

`--from-run ID` seeds the evidence from an existing run in the same runs directory
instead of gathering afresh.

### Result

```json
{"result": {
  "run_id": "fc-9f8e7d6c",
  "status": "complete",
  "brief": "4 of 6 claims supported; 1 refuted; 1 unverifiable.",
  "tally": {"supported": 4, "refuted": 1, "unverifiable": 1, "opinion": 0},
  "claim_count": 6,
  "source_count": 22,
  "path": "...",
  "inline": false,
  "usage": {"tokens_in": 30110, "tokens_out": 6204, "cost_usd": "0.4903"},
  "next": {
    "read_verdicts": "fact-check verdicts fc-9f8e7d6c",
    "read_refuted":  "fact-check verdicts fc-9f8e7d6c --verdict refuted",
    "list_sources":  "fact-check sources fc-9f8e7d6c"
  }
}}
```

The `tally` is inline because it is small and it is the answer. The per-claim detail is
on disk.

### Verdict values

`supported` | `refuted` | `unverifiable` | `opinion`

`unverifiable` is a real verdict, not a failure: it means the claim was checked and no
adequate evidence was found either way. It is never reported as `refuted`, and a claim
the tool could not check for a mechanical reason fails the run instead of being quietly
recorded as `unverifiable`.

Each verdict carries the claim, the verdict, a confidence, the reasoning, and the source
ids it rests on — so a caller can audit any single verdict without reading the rest.

---

## 3. `verdicts <id>` — deterministic

```
fact-check verdicts <id> [--verdict VALUE] [--claim-index N] [--format json|table]
```

The per-claim results as structured data, filterable by verdict. Deterministic: the run
is already on disk, so this costs nothing and spends no tokens. This is the primary
navigation path for a large fact-check, the way `read`/`sources` are for a research run.

---

## 4. Backlog — deliberately not in v1

- `--detach`, as in `deep-research`.
- Re-checking a claim against newer evidence while keeping the original verdict as
  history.
- Claim extraction from a document — v1 takes claims, it does not find them.
- Cross-run contradiction detection over an accumulated runs directory.
