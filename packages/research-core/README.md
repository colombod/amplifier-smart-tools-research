# research-core

Shared core for the research smart tools. Not a smart tool itself: it carries no
`smart-tool.json` and no `SMART_TOOL.md`, so it is not a distribution root.

What lives here is everything `deep-research` and `fact-check` genuinely share — the
manifest accessor, the result envelope, the error taxonomy, and (from M1) configuration
resolution and the run-artifact format.

**The rule this package exists to hold:** nothing here imports an agent engine at module
level. That import rewrites `AMPLIFIER_HOME` in the environment, which poisons unrelated
code, makes deterministic verbs pay for a provider stack they do not use, and breaks the
conformance check that runs `--help` with the environment scrubbed. One cause, three
symptoms.
