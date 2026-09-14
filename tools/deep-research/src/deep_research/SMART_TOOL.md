---
smart_tool_format: 1
name: deep-research
version: 0.1.0
description: >
  Answers a research question with evidence: multi-source web research, synthesised into
  a short brief, backed by citations a caller can act on. Reach for it when a decision
  needs more than one source and nobody has time to become the researcher. The answer is
  a brief plus a pointer to the full evidence on disk, so a result too large to hold can
  still be navigated.
use_cases:
  - Find out what is actually known about a question before committing to a decision
  - Get a short answer with the sources behind it, without reading the sources first
  - Build a durable evidence record that later questions can be answered against
  - Produce a bibliography for a topic without collecting the references by hand
platforms:
  - linux
  - macos
requires:
  - name: perplexity
    purpose: >
      A PERPLEXITY_API_KEY in the environment, or a perplexity entry in
      ~/.config/amplifier-research/credentials.toml at mode 0600. It supplies the evidence
      a research run is built from. Without it the research verb fails saying so rather
      than returning a lesser answer, so what is lost is the gathering of new evidence;
      every run already on disk stays readable. Run `deep-research check` to see whether
      this host has it. The SDK is not listed here: it ships as a resolved dependency.
    optional: true
    install: docs/CONFIGURATION.md
  - name: ai-provider
    purpose: >
      Backs the reasoning stages that scope a question and synthesise the gathered
      evidence. Without it the research verb refuses rather than degrading, so what is
      lost is research itself; every deterministic verb -- reading, filtering,
      re-rendering and listing runs that already exist -- keeps working. Any one of
      ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, GEMINI_API_KEY or
      AZURE_OPENAI_API_KEY satisfies it. This tool stores no credentials of its own.
    optional: true
    install: docs/CONFIGURATION.md
---

# deep-research

One library, one thin `deep-research` CLI. Every response is a single JSON document on
stdout; failures are a JSON error envelope carrying `code`, `message` and `remedy`, with
a non-zero exit. Diagnostics and progress go to stderr.

## What it is good at

Answering a question that needs more than one source, and leaving behind evidence that
outlives the call. A completed run is a directory on disk: the brief, the full report,
the normalised sources, and the raw backend responses. Reading, filtering and re-rendering
that directory costs nothing and needs no credential, so an expensive answer is paid for
once and consulted freely.

## What it is deliberately bad at

It is not a search engine and does not index the web. It is not a citation manager. It
does not decide that a question has one true answer -- where the evidence disagrees, the
brief says so, and confidence is stated rather than implied.

## Straight and smart paths

`manifest` is deterministic and runs with no provider configured. The model-backed verbs
consume tokens, may answer differently on a second run, and fail saying so when nothing
is configured.

This version ships the manifest verb only; the research and navigation verbs named in
`contracts/cli.v1.md` arrive next.
