# deep-research

A smart tool that answers a research question with evidence: multi-source research,
synthesised into a short brief, backed by citations a caller can act on.

The answer is a **brief plus a pointer**. A completed run is a directory on disk — the
brief, the full report, the normalised sources, the raw responses — so a result too large
to hold can still be navigated, and an expensive answer is paid for once and consulted
freely thereafter.

```bash
uv tool install "deep-research @ git+https://github.com/colombod/amplifier-smart-tools-research@main#subdirectory=tools/deep-research"
deep-research --help
```

- **What it is and what it needs**: `src/deep_research/SMART_TOOL.md`
- **What callers may rely on**: `contracts/cli.v1.md`
- **Why it exists**: `../../docs/VISION.md`
- **How it is built**: `../../docs/ARCHITECTURE.md`
- **Configuration and credentials**: `docs/CONFIGURATION.md`

Deterministic verbs run with no AI provider configured and no credentials of any kind.
Model-backed verbs fail loudly naming the missing precondition rather than degrading to a
lesser answer.
