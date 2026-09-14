"""fact-check: checks claims against evidence, one verdict per claim.

The library is the tool. Everything the CLI can do is reachable from here, and
nothing here requires a credential to import.
"""

from research_core import Manifest, load_manifest

__version__ = "0.1.0"

PACKAGE = "fact_check"


def manifest() -> Manifest:
    """This tool's own manifest, read from the copy built into the package."""
    return load_manifest(PACKAGE)


__all__ = ["PACKAGE", "Manifest", "__version__", "manifest"]
