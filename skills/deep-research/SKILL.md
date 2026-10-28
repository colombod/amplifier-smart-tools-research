---
name: deep-research
description: >-
  Research open questions across multiple web sources and return a sourced brief with
  retained evidence. Use when external evidence would inform a recommendation, plan,
  design or implementation: compare approaches or products, investigate feasibility
  and tradeoffs, review prior art or literature, survey a changing field, or
  understand an unfamiliar domain. Consider it within a larger task even when the user
  does not say "research" or name this tool. Use supplied documents and local code
  first for questions they answer; use a direct lookup for one simple fact, and
  fact-check for assessing existing claims. Use when (1) Compare options before
  choosing an architecture, technology or product; (2) Investigate feasibility,
  limitations and prior art before proposing a plan; (3) Build an evidence brief or
  literature review with citations; (4) Reuse retained research evidence for later
  questions.
license: MIT
metadata:
  author: colombod
  repository: https://github.com/colombod/amplifier-smart-tools-research
  version: 0.10.1
---

# Using deep-research

`deep-research --help` documents the installed tool. Read it before choosing commands.

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

## When to bring it into a task

When a missing external comparison or evidence review could change your answer, use this
tool for that part of the task; do not wait for the user to name it. For example,
investigate alternatives before recommending a stack, or prior approaches before
designing a new feature. Form a question tied to the user's decision and constraints,
then read the installed help and check readiness and estimated cost. Reuse relevant
retained evidence when available. A quick lookup or a question settled by supplied files
does not need a new research run.

## Use it

Run `deep-research --help`. It prints the tool's skill: when to reach for it, every
capability, what each costs, worked invocations, how to read a result too large to hold,
and the sharp edges. Follow it. Confirm every argument against `deep-research <command>
--help` rather than memory -- each verb prints its own agent-facing document, and `-h`
gives the terse argparse summary instead.

That document comes from the binary you actually have, so it is correct for your
installation. This file cannot be, and does not try.

`deep-research manifest` reports the version actually installed; this pointer was
generated from 0.10.1. If they differ, re-read `--help` -- flags and costs can change
between releases. Upgrade in place:

```bash
uv tool install --force 'git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/deep-research'
```
