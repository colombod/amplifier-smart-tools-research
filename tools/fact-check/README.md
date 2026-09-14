# fact-check

A smart tool that checks claims against evidence and returns a verdict per claim —
supported, refuted, unverifiable or opinion — with the sources each verdict rests on.

Claims are checked **independently**, so one false claim does not condemn the rest, and a
single verdict can be audited without reading the others. `unverifiable` is a real
verdict, not a failure: it means the claim was checked and no adequate evidence was found
either way.

```bash
uv tool install "fact-check @ git+https://github.com/colombod/amplifier-smart-tools-research@main#subdirectory=tools/fact-check"
fact-check --help
```

Runs share an evidence store with `deep-research`, so a check can be run against sources a
research run already gathered rather than gathering them again.

- **What it is and what it needs**: `src/fact_check/SMART_TOOL.md`
- **What callers may rely on**: `contracts/cli.v1.md`
- **Why it exists**: `../../docs/VISION.md`
- **How it is built**: `../../docs/ARCHITECTURE.md`
- **Configuration and credentials**: `docs/CONFIGURATION.md`
