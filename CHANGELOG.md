# Changelog

Both tools and `research-core` share a version. They are developed together and a
caller installing one gets the other, so a split version would be a fiction.

## 0.5.0

**Upgrade if you have ever read a cost number out of this tool.** Every run before
this release under-reported what it spent.

### Fixed — correctness

- **A run's reported cost was the last stage's cost, not the run's.** `record_usage`
  accumulated tokens and *assigned* cost, two lines apart, so a run published whatever
  the final stage to record had spent. One measured run reported `$1.008705` and had
  actually spent `$1.039992`. Cost now accumulates, like tokens always did.
- **Synthesis failed roughly two times in three at `--depth high`**, rejecting its own
  well-formed replies with "no JSON document was found in the reply". The model writes
  markdown — tables, bullet lists — *into* JSON string values using real newlines
  instead of `\n` escapes, and `json.loads` rejects raw control characters in strings
  by default. Each candidate is now parsed strictly first, then permissively. Nothing
  else is forgiven: truncation, prose and broken syntax are still refused, and the
  newline is preserved rather than eaten. Two of the replies that actually failed are
  committed as fixtures.
- **`raw/` promised "the backend's own replies, verbatim" and kept one stage's.**
  Rejected replies — the only evidence of why a stage failed — were discarded at the
  moment they became interesting. Every reply is now kept, accepted or not, and a
  string is written as itself rather than JSON-encoded.

### Added

- **`fact-check check-claims --detach`.** This verb makes one model call per claim, so
  its wall-clock scales with the claim list; its own estimate is 330s for three claims
  and 959s for ten. It now has the same detached contract as `research`.
- **`estimate --no-scope`** prices the decision a caller is about to make, applying the
  measured ratio rather than making the caller do the arithmetic. `--max-sources` is
  explicitly *not* modelled, and says so, because there is no measured cost-per-source.
- **Every verb's `--help` is an agent-facing document**, with `-h` left as the terse
  argparse summary. Positional arguments are documented — `status --help` omitted the
  one argument the verb cannot run without.
- **The installed `SKILL.md` carries an `## Install` section.** `npx skills add`
  installs a document, not the program.

### Changed — documentation that was wrong

- **`--no-scope` guidance stated a rule we never measured.** It described the question's
  *author* ("when a program composed the question") where the measurement was about the
  question's *sharpness*. An agent followed it into the wrong call, leaving ~27% of a
  saving on the table. The rule now states the measured criterion.
- **The saving was overstated.** "Saves ~37%" was wrong: 37% is what the scope stage
  *adds*; skipping it *saves* ~27%. Wall-clock likewise, +69% with versus −41% without.
- **The polling contract names the trap it used to hide.** `poll_again_in_seconds` is a
  hint about when new work will exist, not an instruction to sleep that long inside one
  call; a run can outlast a caller's per-call limit; and polling more often is free,
  because `status` is deterministic and needs no credential.

## 0.4.0 and earlier

Not recorded here. `0.4.0` was, for a time, the version of fifteen different things —
which is the defect this file exists to stop.
