---
name: fact-check
description: >-
  Checks claims against evidence and returns a verdict per claim -- supported,
  refuted, unverifiable or opinion -- with the sources each verdict rests on. Reach
  for it when something asserts several things and you need to know which of them
  hold, rather than whether the piece as a whole sounds right. Claims are checked
  independently, so one false claim does not condemn the rest. Use when (1) Check the
  claims in a document or a draft before it goes out; (2) Find which of several
  assertions actually hold, and which merely sound right; (3) Audit a single verdict
  down to the sources it rests on; (4) Re-check claims against evidence a previous
  research run already gathered. Triggers on "fact check", "verify this claim", "is
  this true", "check claims".
license: MIT
metadata:
  author: colombod
  repository: https://github.com/colombod/amplifier-smart-tools-research
  version: 0.6.0
---

# Using fact-check

Checks claims against evidence and returns a verdict per claim -- supported, refuted,
unverifiable or opinion -- with the sources each verdict rests on. Reach for it when
something asserts several things and you need to know which of them hold, rather than
whether the piece as a whole sounds right. Claims are checked independently, so one
false claim does not condemn the rest.

## Install

`npx skills add` installs THIS DOCUMENT, not the program. If `fact-check` is not on your
PATH, install it:

```bash
# as a CLI
uv tool install 'git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/fact-check'
# as a library, from another project
uv add 'fact-check @ git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/fact-check'
# once, without installing
uvx --from 'git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/fact-check' fact-check --help
```

## Use it

Run `fact-check --help`. It prints the tool's skill: when to reach for it, every
capability, what each costs, worked invocations, how to read a result too large to hold,
and the sharp edges. Follow it. Confirm every argument against `fact-check <command>
--help` rather than memory -- each verb prints its own agent-facing document, and `-h`
gives the terse argparse summary instead.

That document comes from the binary you actually have, so it is correct for your
installation. This file cannot be, and does not try.

## Staying current

`fact-check manifest` reports the version installed. This pointer was generated from
0.6.0. If they differ, the tool is the authority -- re-read `--help`, because flags and
costs change between releases.

```bash
# what you have
fact-check manifest

# what exists
git ls-remote --tags --refs https://github.com/colombod/amplifier-smart-tools-research | tail -3

# upgrade in place
uv tool install --force 'git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/fact-check'
```
