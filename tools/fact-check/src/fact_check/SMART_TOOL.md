---
smart_tool_format: 1
name: fact-check
version: 0.9.1
description: >
  Takes things someone has asserted and checks each one against evidence, returning a verdict per claim -- supported, refuted, unverifiable or opinion -- with the sources each rests on. Reach for it when the ask sounds like "is any of this actually true?", "check the claims in this draft before it goes out", or "where did that number come from?". Claims are checked INDEPENDENTLY, so one false claim does not condemn the rest of a document. Do NOT use it for an open question with no claim in it yet -- that is deep-research -- or to check code against its tests.
use_cases:
  - Check the claims in a draft before it goes out
  - Find which assertions hold and which merely sound right
  - Audit a single verdict down to its sources
  - Re-check claims against evidence a previous research run gathered
platforms:
  - linux
  - macos
requires:
  - name: perplexity
    purpose: >
      A PERPLEXITY_API_KEY in the environment, or a perplexity entry in
      ~/.config/amplifier-research/credentials.toml at mode 0600. It supplies the evidence
      claims are checked against. Without it the check verb fails saying so rather than
      guessing, so what is lost is checking new claims; verdicts already on disk stay
      readable. Run `fact-check check` to see whether this host has it. The SDK is not
      listed here: it ships as a resolved dependency.
    optional: true
    install: docs/CONFIGURATION.md
  - name: ai-provider
    purpose: >
      Backs the stages that sort claims by type and weigh evidence against each one.
      Without it no claim can be checked and the verb refuses rather than guessing, so
      what is lost is checking itself; reading, filtering and re-rendering runs that
      already exist keeps working. Needs BOTH a resolvable credential AND that
      provider's client library installed -- a credential alone does not satisfy
      preflight. ANTHROPIC_API_KEY is satisfied out of the box: this tool installs the
      `anthropic` client by default. OPENAI_API_KEY, AZURE_OPENAI_API_KEY or a GitHub
      Copilot credential additionally need the `research-core[agent-openai]` extra (or
      `pip install openai`); GOOGLE_API_KEY or GEMINI_API_KEY additionally need
      `research-core[agent-gemini]` (or `pip install google-genai`). This tool stores no
      credentials of its own.
    optional: true
    install: docs/CONFIGURATION.md
---

# fact-check

One library, one thin `fact-check` CLI. Every response is a single JSON document on
stdout; failures are a JSON error envelope carrying `code`, `message` and `remedy`, with
a non-zero exit. Diagnostics and progress go to stderr.

## What it is good at

Taking several claims and telling you which hold. Each claim is checked independently and
carries its own verdict, confidence, reasoning and sources, so a single verdict can be
audited without reading the rest. A completed run is a directory on disk, and reading or
re-rendering it costs nothing and needs no credential.

It shares an evidence store with `deep-research`: a check can be run against sources a
research run already gathered rather than gathering them again.

## What it is deliberately bad at

It does not find claims -- it checks the ones it is given. It does not rate a document
overall, because "mostly true" is the kind of summary that hides which part was false.

`unverifiable` is a real verdict, not a failure: it means the claim was checked and no
adequate evidence was found either way. It is never reported as `refuted`.

## Straight and smart paths

`manifest`, `check`, `config`, `list`, `status`, `read`, `sources`, `render`, `verdicts`,
`classify` and `estimate` are deterministic and run with no provider configured.
`check-claims` is model-backed: it consumes tokens, may answer differently on a second
run, and fails saying so when nothing is configured rather than guessing.

This tool ships its full operational surface today: the manifest verb, `check-claims`, and
the deterministic navigation verbs named in `contracts/cli.v1.md`. `<verb> --help`
documents each one; `skill` renders the whole tool as an Agent Skill.
