# Evaluation — does it judge WELL, not just run?

Conformance proves a tool is *shaped* right: manifest valid, deterministic paths run
without credentials, exit codes correct. For a tool whose entire output is judgments, that
is the weak half.

This measures the other half.

```bash
uv run evaluation/run.py --mode oracle      # free — proves the harness works
uv run evaluation/run.py --mode adversary   # free — proves the harness can FAIL
uv run evaluation/run.py --mode live --out evaluation/results/   # costs money
```

## What is measured, and what is deliberately not

**Per-category accuracy, never one number.** A single aggregate hides the only thing worth
knowing. A tool can score 90% overall while failing every hard case, because most claims in
any realistic set are easy.

**The critical confusion, tracked on its own:** how often a claim the evidence does not
settle came back as `refuted`. That is asserting falsehood from absence — the error that
turns a cautious tool into a confidently wrong one, and the one this tool exists to
prevent. It is the harness's **failing condition**: a pass with any critical confusion
exits non-zero regardless of the overall score.

## The fixture set is weighted toward the hard cases on purpose

Eight of fourteen claims expect `unverifiable`. That is not an accident of sampling — it is
the point. Accuracy on cleanly-true claims tells you nothing about a tool you would rely on.

| Category | n | What it probes |
|---|---|---|
| `supported` | 2 | the easy case, present as a control |
| `refuted` | 2 | the evidence **contradicts** the claim — distinct from being silent |
| `unverifiable` | 4 | the evidence says nothing either way |
| `opinion` | 2 | a value judgment wearing factual grammar |
| `true_in_part` | 2 | one half evidenced, the other absent |
| `unsupported_reason` | 2 | conclusion plausible, but the evidence gives no basis for the *reason* |

`unsupported_reason` is where confident tools fail invisibly. *"CRDTs are being adopted
because they remove the need for consensus"* — the adoption is evidenced, the **because** is
nowhere, and a tool that answers `supported` has graded the half it recognised.

Every expectation is decidable from `fixtures/evidence/dr-eval0001/report.md` alone, and
each claim records the line that makes its expectation correct. **If you cannot point at
that line, the claim does not belong in the set.**

## Why three modes

`oracle` and `adversary` exist so the harness can be built and trusted for free — neither
needs a provider or spends a token.

**`adversary` is the one that makes the whole thing credible.** It returns deliberately
wrong but *structurally valid* verdicts — valid so they pass the tool's own validators and
actually reach the scorer. It turns every `unverifiable` into `refuted` on purpose:

```
!! asserted falsehood from absence (unverifiable -> refuted): 8
   overall 0/14 = 0.0                                        exit=1
```

A harness that cannot report a bad score is not a measurement. Run `adversary` whenever you
change the scorer; if it stops failing, the scorer is broken.

## Live passes

A live pass records the **model, provider, cost and token counts** alongside the scores, so
a later pass is comparable rather than merely different. Write them to
`evaluation/results/` and keep them: the tuning work (`smart_tools-7o5`) needs a before to
have an after.

Results are a moment in time. A model changes underneath you without telling you, so a
score from last month is evidence about last month.
