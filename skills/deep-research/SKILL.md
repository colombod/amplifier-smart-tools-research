---
name: deep-research
description: >-
  Researches a question across many sources and returns a short brief plus the
  citations behind it. Reach for it when the ask sounds like "what do we actually know
  about X?", "find me sources on this", or "I need to decide this and have not read
  anything yet". Searches the live web and synthesises, returning a brief plus a
  pointer to the full evidence kept on disk. Do NOT use it to check specific claims
  you already have -- that is fact-check -- or for questions answerable from the code
  or documents already in front of you. Use when (1) Find out what is known before
  committing to a decision; (2) Get a short sourced answer without reading the sources
  first; (3) Build a durable evidence record for later questions; (4) Produce a
  bibliography without collecting references by hand.
license: MIT
metadata:
  author: colombod
  repository: https://github.com/colombod/amplifier-smart-tools-research
  version: 0.10.0
---

# Using deep-research

`deep-research --help` is the real document. This file only says how to get the tool.

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

`deep-research manifest` reports the version actually installed; this pointer was
generated from 0.10.0. If they differ, re-read `--help` -- flags and costs can change
between releases. Upgrade in place:

```bash
uv tool install --force 'git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/deep-research'
```
