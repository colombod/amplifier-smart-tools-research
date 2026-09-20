---
smart_tool_format: 1
name: deep-research
version: 0.9.1
description: >
  Researches a question across many sources and returns a short brief plus the citations behind it. Reach for it when the ask sounds like "what do we actually know about X?", "find me sources on this", or "I need to decide this and have not read anything yet". Searches the live web and synthesises, returning a brief plus a pointer to the full evidence kept on disk. Do NOT use it to check specific claims you already have -- that is fact-check -- or for questions answerable from the code or documents already in front of you.
use_cases:
  - Find out what is known before committing to a decision
  - Get a short sourced answer without reading the sources first
  - Build a durable evidence record for later questions
  - Produce a bibliography without collecting references by hand
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
      re-rendering and listing runs that already exist -- keeps working. Needs BOTH a
      resolvable credential AND that provider's client library installed -- a credential
      alone does not satisfy preflight. ANTHROPIC_API_KEY is satisfied out of the box:
      this tool installs the `anthropic` client by default. OPENAI_API_KEY,
      AZURE_OPENAI_API_KEY or a GitHub Copilot credential additionally need the
      `research-core[agent-openai]` extra (or `pip install openai`); GOOGLE_API_KEY or
      GEMINI_API_KEY additionally need `research-core[agent-gemini]` (or
      `pip install google-genai`). This tool stores no credentials of its own.
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

`manifest`, `check`, `config`, `list`, `status`, `read`, `sources`, `render`, `classify` and
`estimate` are deterministic and run with no provider configured. `research` is
model-backed: it consumes tokens, may answer differently on a second run, and fails saying
so when nothing is configured rather than returning a lesser answer.

This tool ships its full operational surface today: the manifest verb, the research verb,
and the deterministic navigation verbs named in `contracts/cli.v1.md`. `<verb> --help`
documents each one; `skill` renders the whole tool as an Agent Skill.
