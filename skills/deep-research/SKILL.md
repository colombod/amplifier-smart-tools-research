---
name: deep-research
description: >-
  Researches a question across many sources and comes back with a short brief
  plus the citations behind it. Reach for it when the ask sounds like "what do we
  actually know about X?", "find me sources on this", "is this approach still the
  consensus?", "what are the options here and who says so?", or "I need to decide
  this and I have not read anything yet". Searches the live web, reads what it
  finds, and synthesises -- the answer is a brief plus a pointer to the full
  evidence kept on disk, so a result too large to hold in one reply can still be
  navigated, re-read and answered against later. Use it before committing to a
  decision, to get a short answer with its sources attached without reading them
  first, or to build a durable evidence record. Do NOT use it to check specific
  claims you already have -- that is fact-check -- or for questions answerable
  from the code or documents already in front of you.
license: MIT
metadata:
  author: colombod
  repository: https://github.com/colombod/amplifier-smart-tools-research
  version: 0.8.0
---

# Using deep-research

Answers a research question with evidence: multi-source web research, synthesised into a
short brief, backed by citations a caller can act on. Reach for it when a decision needs
more than one source and nobody has time to become the researcher. The answer is a brief
plus a pointer to the full evidence on disk, so a result too large to hold can still be
navigated.

## Install

`npx skills add` installs THIS DOCUMENT, not the program. If `deep-research` is not on
your PATH, install it:

```bash
# as a CLI
uv tool install 'git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/deep-research'
# as a library, from another project
uv add 'deep-research @ git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/deep-research'
# once, without installing
uvx --from 'git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/deep-research' deep-research --help
```

## Use it

Run `deep-research --help`. It prints the tool's skill: when to reach for it, every
capability, what each costs, worked invocations, how to read a result too large to hold,
and the sharp edges. Follow it. Confirm every argument against `deep-research <command>
--help` rather than memory -- each verb prints its own agent-facing document, and `-h`
gives the terse argparse summary instead.

That document comes from the binary you actually have, so it is correct for your
installation. This file cannot be, and does not try.

## Staying current

`deep-research manifest` reports the version installed. This pointer was generated from
0.8.0. If they differ, the tool is the authority -- re-read `--help`, because flags and
costs change between releases.

```bash
# what you have
deep-research manifest

# what exists
git ls-remote --tags --refs https://github.com/colombod/amplifier-smart-tools-research | tail -3

# upgrade in place
uv tool install --force 'git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/deep-research'
```
