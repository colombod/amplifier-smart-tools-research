# Changelog

Both tools and `research-core` share a version. They are developed together and a
caller installing one gets the other, so a split version would be a fiction.

## 0.7.0

**Upgrade if you run this anywhere that confines writes** — a sandboxed agent host, a
container, CI. Before this release those hosts lost model-backed runs *after* paying for
the evidence.

### Fixed — a confined host could not complete a run, and was not told why

A real run in a sandboxed host gathered 54 sources, spent its money, and then died on the
synthesis stage with a bare `PermissionError` naming `~/.amplifier-agent` — a directory
nobody had chosen, that no setting mentioned, and that the run had never said it needed.

Two locations were being written outside the caller's control: the embedded engine's tree
(several hundred megabytes of prepared-bundle cache and module clones) and a scratch
working directory taken from `$TMPDIR`. Neither was nameable, so neither could be pointed
somewhere the host allowed.

- **New setting `engine_home`** (`RESEARCH_ENGINE_HOME`, or `engine_home` in the config
  file). Everything written outside `runs_dir` now goes there. **Two paths, and no
  others** — point both into your workspace and the tool stays inside it.
- **The turn's working directory moved inside it**, and is now *removed when the turn
  ends*. It used to be a fresh `$TMPDIR` directory per turn that nothing ever deleted.
- **Model-backed verbs refuse up front** when that path is unwritable — `engine_unavailable`,
  naming the path, the tier that chose it, and the setting that moves it. Before the run,
  not at its first model-backed stage.
- **`check` reports both paths** and whether each is writable, so a host can find this out
  before it spends anything.

The default is unchanged: whatever the engine itself would have used. Nobody who never had
a problem is moved, and the cache stays shared between runs rather than rebuilt per
invocation.

### Fixed — the obvious lever was the wrong one, silently

`AMPLIFIER_HOME` is the variable the storage layer reads, so it is the one anybody reaching
for a lever exports first. The engine **overwrites it at import**, so exporting it does
nothing whatsoever, in silence. `check` now says so when it sees it set, the refusal above
repeats it, and a test holds the engine to both halves of that claim — that
`AMPLIFIER_AGENT_HOME` moves the tree and `AMPLIFIER_HOME` does not — so a message that
quietly stopped being true would fail the build instead of misdirecting the next person.

## 0.6.0

### Changed — the installed `SKILL.md` is now a pointer, not a copy

`npx skills add` used to install a 155-line document: the whole of `--help` with an
install block spliced in, guarded by a test asserting that derivation.

**That test checked the wrong thing.** It proved the file matched `--help` *in this
repository at build time*, while the two artifacts reach a user from different places —
`npx skills add <repo>` tracks the default branch, `uv tool install …@v0.5.0` is pinned.
A host could hold a skill describing flags its binary does not have, and nothing here
would have failed.

The file is now 69 lines and says four things: what the tool is, how to install it, that
`--help` is the real skill (and `<command> --help` for each verb), and how to tell whether
your copy is current. **A pointer cannot go stale, because it asserts nothing `--help`
would.**

- `--help` is unchanged — still the full agent-facing document, printed by the binary you
  actually have, so it is correct by construction.
- Frontmatter gains `license` and `metadata` (`author`, `repository`, `version`), matching
  what `smart-tool-creator` scaffolds by default.
- New **Staying current** section: `<tool> manifest` reports your version, the pointer
  names the release it was built from, and the upgrade command is right there.

This is the shape the smart-tool-creator has scaffolded all along. Adopting it cost
nothing measured: three harnesses drove this tool correctly, and every one read `--help`
*after* the skill rather than instead of it.

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

- **Every cost estimate was low, and grew worse with depth.** The profiles were
  guesses dressed as arithmetic; not one measured run came in under its estimate.

  ```
  depth  old estimate   observed            ratio
  low    $0.0405        $0.0580 - $0.1275   1.4x - 3.1x
  high   $0.1605        $0.8385 - $1.0087   5.2x - 6.3x
  ```

  Profiles are now calibrated to the observed mean of four real runs, and
  `estimate` publishes a **band** (`estimated_cost_usd_range`) rather than only a
  point — because a stage that fails validation is retried *and billed for every
  attempt*, which no estimate can predict. A test asserts the band contains every
  run it was calibrated on; at the first candidate width it did not.
- **`run.json` claimed the `scope` stage ran when `--no-scope` was passed.**
  `scope.json` recorded the skip correctly, but nothing points an auditor there,
  and the prominent record was the misleading one. A skipped stage is no longer
  listed as a stage of the run.
- **`run.json` recorded `detached: None` on every detached run.** The parent
  claims the record before spawning the child so a caller polling immediately
  finds a run rather than a gap; the child's `RunWriter` then wrote straight over
  it. The flag survived about a second. `RunWriter` now carries forward any
  pre-claimed key it does not itself define — general on purpose, because this
  was the second time a later writer silently destroyed an earlier truth.
- **`--detach` help said runs take "60 to 550 seconds".** Two measured runs took
  659 and 784. It now states the real range.

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
