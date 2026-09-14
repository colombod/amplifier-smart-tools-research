# Tuning log

One change per entry, measured before and after against a named fixture set. Changes that
did not help are recorded too — a tuning pass with no record of the failures is a pass
nobody can build on.

Every score here is one live pass. A model changes underneath you without telling you, so
these are evidence about the day they were run.

---

## 000 — Baseline: the clean fixture cannot discriminate

**Fixture:** `claims` · **Live:** 14/14, 0 critical confusions, $0.052644

A perfect first score is not good news. It means the set has no headroom, so nothing can be
tuned against it — any change can only hold or regress. The claims were written by the same
person who wrote the prompts, which is the N=1 eyeball problem moved one level up.

**Action:** built a second fixture set before changing anything.

---

## 001 — Contradiction fixture: headroom found

**Fixture:** `claims-contradiction` · **Live:** 8/12 (0.667), **1 critical confusion**, $0.0555

Evidence that disagrees with itself: two peer-reviewed sources measure the same property and
report incompatible results (~3x vs under 1.2x memory overhead).

| category | | missed |
|---|---|---|
| contested | 1/3 | x01, x02 |
| weak_source | 0/2 | x04, x05 |
| everything else | 7/7 | — |

**Two distinct failure modes, neither visible in the clean set:**

1. **Picking a winner in a contested measurement.** x01 (*"roughly 3x"*) came back
   **`refuted`** and x02 (*"under 1.2x"*) came back **`supported`** — the tool chose `[s2]`
   and then graded both claims against it. The `refuted` is the critical confusion: it
   asserted falsehood on a question the evidence does not settle.
2. **Promoting weak sources.** x04 (one team's blog post) and x05 (a newsletter mention)
   both came back `supported`. An anecdote was read as a general property.

Notably x03 — the *averaging* trap, a range between two incompatible figures — was caught.
The prompt warned against averaging and said nothing about picking a side, and the results
matched the prompt exactly.

---

## 002 — Add contested-evidence and source-strength rules to the persona

**Change:** one edit, to `fact_check/prompts.py` `PERSONA`. Two paragraphs: when sources
disagree the disagreement IS the finding and the verdict is `unverifiable` whichever source
seems better; and match the strength of the source to the strength of the claim, since an
experience report evidences one team's experience and not a general property.

**Fixture:** `claims-contradiction` · **Live:** 11/12 (0.917), **0 critical confusions**, $0.057102

| id | category | expected | before | after | |
|---|---|---|---|---|---|
| x01 | contested | unverifiable | `refuted` | `unverifiable` | **fixed** |
| x02 | contested | unverifiable | `supported` | `unverifiable` | **fixed** |
| x04 | weak_source | unverifiable | `supported` | `unverifiable` | **fixed** |
| x05 | weak_source | unverifiable | `supported` | `unverifiable` | **fixed** |
| x12 | opinion | opinion | `opinion` | `refuted` | **broke** |

**Verdict: KEPT.** Net +3, and the critical confusion went to zero — the one metric that is
the harness's failing condition. Cost was flat (+3%).

### The regression, and it is my fault specifically

x12 is *"The later paper should be trusted over the earlier one."* Expected `opinion` — it is
a judgment about how to weigh sources, not a claim about the world.

My new prompt text says: *"Picking the later paper, the better-argued one, or the one with an
explanation for the discrepancy is resolving a disagreement the evidence has not resolved."*

So the model read x12 as an assertion my instruction had just told it was wrong, and
**refuted it**. The instruction converted a question about method into a proposition with a
right answer.

**Worth naming as a smell:** I wrote *"the later paper"* into a prompt while a fixture claim
used the same phrase. That is prompt text shaped by the test set, which is how a tool learns
the fixture instead of the skill. The fix is to state the principle without naming the
tie-breakers — *"prefer no source over resolving the disagreement yourself"* — not to add a
second rule patching the first.

**Follow-up:** re-word 002 to drop the enumerated tie-breakers, and re-run. Do not add a
separate "x12 is an opinion" instruction; that would be tuning to the fixture twice.
