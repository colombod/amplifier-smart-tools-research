---
smart_tool_format: 1
name: fact-check
version: 0.5.0
description: >
  Checks claims against evidence and returns a verdict per claim -- supported, refuted,
  unverifiable or opinion -- with the sources each verdict rests on. Reach for it when
  something asserts several things and you need to know which of them hold, rather than
  whether the piece as a whole sounds right. Claims are checked independently, so one
  false claim does not condemn the rest.
use_cases:
  - Check the claims in a document or a draft before it goes out
  - Find which of several assertions actually hold, and which merely sound right
  - Audit a single verdict down to the sources it rests on
  - Re-check claims against evidence a previous research run already gathered
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
      already exist keeps working. Any one of ANTHROPIC_API_KEY, OPENAI_API_KEY,
      GOOGLE_API_KEY, GEMINI_API_KEY or AZURE_OPENAI_API_KEY satisfies it. This tool
      stores no credentials of its own.
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

`manifest` is deterministic and runs with no provider configured. The model-backed verbs
consume tokens, may answer differently on a second run, and fail saying so when nothing
is configured.

This version ships the manifest verb only; the verbs named in `contracts/cli.v1.md`
arrive next.
