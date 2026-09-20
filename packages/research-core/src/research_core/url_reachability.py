"""Whether a cited source URL currently resolves.

D5: nothing in this package has ever checked. A citation a synthesis names as
the reason for "high" confidence can be a 404 -- returned verbatim by a
backend, never invented -- and it travels unmarked through `sources`, `render
--format bibliography`, and every downstream fact-check verdict that rests on
it. This module is the check that was missing.

**Reachability is not support.** A 200 response proves the page exists; it
says nothing about whether the page still says what a citation claims. This
module answers only the first question, and its callers must not blur the two.

This DOES reach a network, which is why every caller wires it as an explicit
opt-in (see `research_core.api.sources`'s `verify` parameter) rather than
running it on every `sources` call. No model, no credential -- so it is
"deterministic" in the sense this project uses that word everywhere else, but
it is not free and not instant, and a caller that did not ask for it should
never pay for it.

Degrades gracefully with no network: every failure is caught and reported as
`reachable: None` with an `error`, never raised. "The page does not exist" and
"we could not check" are different findings, and only the first should ever be
allowed to influence a caller's confidence in anything.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

DEFAULT_TIMEOUT_S = 5.0

_USER_AGENT = "research-core-url-reachability-check/1"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _probe(url: str, *, timeout: float) -> tuple[bool | None, int | None, str | None]:
    """One URL, one attempt at HEAD, falling back to GET when HEAD is refused.

    Some hosts reject HEAD outright (405) or bot-block automated clients (401,
    403, 429) while a browser would get a real answer -- neither is proof the
    page is gone, so both are reported as their real status code rather than
    folded into "unreachable". A GET response body is never read; only the
    status line is inspected, so the retry costs headers, not bytes.
    """
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, method=method, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                status = getattr(response, "status", None) or response.getcode()
                return (200 <= status < 400, status, None)
        except urllib.error.HTTPError as exc:
            if method == "HEAD" and exc.code in (405, 501):
                continue  # this host does not answer HEAD; try GET before giving up
            return (200 <= exc.code < 400, exc.code, None)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", None)
            return (None, None, str(reason) if reason else str(exc))
    return (None, None, "no response to HEAD or GET")


def verify_source_urls(
    sources: list[dict[str, Any]], *, timeout: float = DEFAULT_TIMEOUT_S
) -> list[dict[str, Any]]:
    """Check every source's URL. One entry back per source, in order, never raises.

    Each result: `id`, `url`, `reachable` (True/False/None), `status_code`
    (when a real HTTP response was received, error or not), `error` (when the
    network itself failed rather than answering), `checked_at`.
    """
    results: list[dict[str, Any]] = []
    for source in sources:
        url = source.get("url")
        checked_at = _now()
        if not url:
            results.append(
                {
                    "id": source.get("id"),
                    "url": url,
                    "reachable": None,
                    "status_code": None,
                    "error": "this source has no url to check",
                    "checked_at": checked_at,
                }
            )
            continue
        reachable, status_code, error = _probe(url, timeout=timeout)
        results.append(
            {
                "id": source.get("id"),
                "url": url,
                "reachable": reachable,
                "status_code": status_code,
                "error": error,
                "checked_at": checked_at,
            }
        )
    return results
