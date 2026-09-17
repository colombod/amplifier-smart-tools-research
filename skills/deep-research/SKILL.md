---
name: deep-research
description: >-
  Answers a research question with evidence: multi-source web research, synthesised
  into a short brief, backed by citations a caller can act on. Reach for it when a
  decision needs more than one source and nobody has time to become the researcher.
  The answer is a brief plus a pointer to the full evidence on disk, so a result too
  large to hold can still be navigated. Use when (1) Find out what is actually known
  about a question before committing to a decision; (2) Get a short answer with the
  sources behind it, without reading the sources first; (3) Build a durable evidence
  record that later questions can be answered against; (4) Produce a bibliography for
  a topic without collecting the references by hand. Triggers on "deep research",
  "research this", "find sources", "what is known about".
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
