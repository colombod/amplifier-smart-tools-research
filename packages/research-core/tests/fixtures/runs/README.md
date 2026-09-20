# Fixture runs

| Run | Shape it exercises | Provenance |
|---|---|---|
| `dr-1a2b3c4d` | a clean completed research run; report long enough that a bounded read is genuinely partial | hand-authored |
| `dr-7f3e9a21` | a **dangling citation**: the report cites `[s7]`, which is not in `sources.json` | hand-authored |
| `dr-c0ffee11` | **failed mid-gather**: status `failed`, one stage `failed`, two `not_started`, evidence gathered so far kept | hand-authored |
| `fc-9f8e7d6c` | a fact-check run: `verdicts.json`, a tally, and sources inherited from `dr-1a2b3c4d` | **recorded** -- see below |

Nothing here needs a credential to read, which is the point: the whole deterministic
surface and the validation spine are testable against these with nothing configured and
no tokens spent.

## `dr-*` fixtures are hand-authored, and that is a known, reported gap

The three `dr-*` runs above were hand-authored **as if written by a real run**, field by
field, before any reader existed. That order was deliberate: a format designed from the
reader's side reads beautifully and turns out to be awkward to write, and nobody
discovers that until the writer arrives.

`fc-9f8e7d6c` was hand-authored the same way, and it hid a real bug for exactly that
reason (see the next section). The `dr-*` fixtures were swept for the same class of
fiction -- diffed key-by-key against a real recorded `run.json` -- and DO carry the same
kind of drift (each is missing `confidence`, `host`, `pid`, and has no `detached` key
since a real non-detached run has none either -- that part is actually correct; what is
missing is genuinely absent). They were **not** rewritten in this pass: the ~15 tests
against them assert on hand-crafted report/brief prose (section headers, specific
dangling-citation markers, specific category groupings) that a scripted recording would
have to reproduce byte-for-byte to avoid a much larger rewrite, for a lower-value target
than `fc-9f8e7d6c` was. Recorded first, because `fc-9f8e7d6c` is where a live reader/writer
key mismatch actually hid. Treat the `dr-*` fixtures as a follow-up of the same kind.

## `fc-9f8e7d6c` is a RECORDING, not hand-authored

It used to be hand-authored too, and that fiction hid a real bug: the old `run.json`
carried a top-level `tally` key (and a `from_run` key) that no writer has ever produced,
and was missing `confidence`, `host`, `inherited_from`, and `pid`, which every real run
carries. The reader (`runs.py`'s `verdicts_of`) used to read `run.record.get("tally")` --
which was always `None` on a real run, because the real writer only ever writes
`counts`. The fixture agreed with the reader's assumption instead of with what the
writer actually produces, so the mismatch was invisible to the whole test suite.

`fc-9f8e7d6c` is now a REAL recording: `generate_fc_9f8e7d6c.py` in this directory drives
the actual `fact_check.check_claims()` pipeline through the no-credential
`ScriptedReasoner` seam, against `dr-1a2b3c4d` as evidence, and the result is committed
verbatim (only `host`/`pid`/timestamps are scrubbed -- see the script's docstring). Its
claim indices are 0-based (`enumerate(claims)`), unlike the old fixture's 1-based ones --
another fiction the old hand-authoring introduced. Regenerate with:

```bash
.venv/bin/python packages/research-core/tests/fixtures/runs/generate_fc_9f8e7d6c.py
```
