"""Sorting a URL into the kind of source it is.

A pure table lookup: no network, no model, no credentials. Ported from the bundle
this tool grew out of, where the same table decided how a reference list was
grouped.

The categories are deliberately coarse. The question a reader asks of a reference
list is "is this a paper, a news piece, or documentation", and a finer taxonomy
would invite arguments the table cannot settle.
"""

from __future__ import annotations

from urllib.parse import urlparse

ACADEMIC = "academic"
NEWS = "news"
DOCS = "docs"
OTHER = "other"

CATEGORIES = (ACADEMIC, NEWS, DOCS, OTHER)

#: Matched against the host, longest rule first, as a substring. Ordered by
#: category so an addition lands somewhere obvious.
_RULES: tuple[tuple[str, str], ...] = (
    ("arxiv.org", ACADEMIC),
    ("doi.org", ACADEMIC),
    ("pubmed.ncbi.nlm.nih.gov", ACADEMIC),
    ("ncbi.nlm.nih.gov", ACADEMIC),
    ("ieee.org", ACADEMIC),
    ("acm.org", ACADEMIC),
    ("springer.com", ACADEMIC),
    ("sciencedirect.com", ACADEMIC),
    ("nature.com", ACADEMIC),
    ("science.org", ACADEMIC),
    ("jstor.org", ACADEMIC),
    ("semanticscholar.org", ACADEMIC),
    ("researchgate.net", ACADEMIC),
    ("biorxiv.org", ACADEMIC),
    ("ssrn.com", ACADEMIC),
    ("hal.science", ACADEMIC),
    ("inria.fr", ACADEMIC),
    ("reuters.com", NEWS),
    ("bloomberg.com", NEWS),
    ("ft.com", NEWS),
    ("wsj.com", NEWS),
    ("nytimes.com", NEWS),
    ("theguardian.com", NEWS),
    ("bbc.co.uk", NEWS),
    ("bbc.com", NEWS),
    ("techcrunch.com", NEWS),
    ("theverge.com", NEWS),
    ("arstechnica.com", NEWS),
    ("wired.com", NEWS),
    ("infoq.com", NEWS),
    ("theregister.com", NEWS),
    ("github.com", DOCS),
    ("gitlab.com", DOCS),
    ("readthedocs.io", DOCS),
    ("readthedocs.org", DOCS),
    ("w3.org", DOCS),
    ("ietf.org", DOCS),
    ("rfc-editor.org", DOCS),
    ("developer.mozilla.org", DOCS),
    ("microsoft.com/en-us/docs", DOCS),
    ("learn.microsoft.com", DOCS),
    ("docs.python.org", DOCS),
    ("kubernetes.io", DOCS),
    ("pypi.org", DOCS),
    ("npmjs.com", DOCS),
)

#: Host prefixes that mean documentation whatever the domain is.
_DOC_PREFIXES = ("docs.", "developer.", "devdocs.", "api.")

#: Suffixes that mean academic whatever the rest of the host is.
_ACADEMIC_SUFFIXES = (".edu", ".ac.uk", ".edu.au", ".ac.jp")


def classify_url(url: str) -> str:
    """Sort one URL into academic, news, docs or other.

    An unparseable or empty URL is ``other`` rather than an error: this runs over
    whatever a backend returned, and one malformed entry should not fail a whole
    reference list.
    """
    if not url or not url.strip():
        return OTHER

    host = (urlparse(url.strip()).hostname or "").lower()
    if not host:
        return OTHER

    path = urlparse(url.strip()).path.lower()
    haystack = host + path

    if any(host.endswith(suffix) for suffix in _ACADEMIC_SUFFIXES):
        return ACADEMIC
    if any(host.startswith(prefix) for prefix in _DOC_PREFIXES):
        return DOCS

    for needle, category in _RULES:
        if needle in haystack:
            return category
    return OTHER


def classify_urls(urls: list[str]) -> list[dict[str, str]]:
    """Sort several URLs, preserving order and keeping duplicates."""
    return [{"url": url, "category": classify_url(url)} for url in urls]
