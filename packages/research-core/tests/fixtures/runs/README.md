# Fixture runs

Hand-authored **as if written by a real run**, field by field, before any reader existed.
That order was deliberate: a format designed from the reader's side reads beautifully and
turns out to be awkward to write, and nobody discovers that until the writer arrives.

| Run | Shape it exercises |
|---|---|
| `dr-1a2b3c4d` | a clean completed research run; report long enough that a bounded read is genuinely partial |
| `dr-7f3e9a21` | a **dangling citation**: the report cites `[s7]`, which is not in `sources.json` |
| `dr-c0ffee11` | **failed mid-gather**: status `failed`, one stage `failed`, two `not_started`, evidence gathered so far kept |
| `fc-9f8e7d6c` | a fact-check run: `verdicts.json`, a tally, and sources inherited from `dr-1a2b3c4d` |

Nothing here needs a credential to read, which is the point: the whole deterministic
surface and the validation spine are testable against these with nothing configured and
no tokens spent.
