"""Error types and the SPEC §7 status-to-message table.

Two error classes, because they have two different blast radii:

* `ApiError` — the call itself failed. Nothing can be drawn, so the page stops.
* `DataIntegrityError` — data arrived but is malformed or impossible (SPEC §7.1). Raised
  during a statement build, it takes down that section and leaves the others standing.

Neither is ever raised for an *absent* concept. Absence is a normal fact about a company and
renders as an em dash. Turning absence into an error is as much a bug as the reverse.
"""

from __future__ import annotations

from collections.abc import Mapping


class ViewerError(Exception):
    """Base for every failure this app raises deliberately."""


class ApiError(ViewerError):
    """A request to the fundamentals API failed. The message is viewer-facing copy."""


class DataIntegrityError(ViewerError):
    """A value was present but malformed or impossible (SPEC §7.1).

    The message names the ticker and the offending field, because the person reading it is
    the person who has to fix it upstream.
    """


TIMEOUT_MESSAGE = "Request timed out. The company may be large — try again."

UNREACHABLE_MESSAGE = "Could not reach the fundamentals API. Try again shortly."

# SPEC §7. The viewer never sees a raw API error object; these strings are the whole
# contract. 502 and 504 share copy because the distinction between "EDGAR errored" and
# "EDGAR was slow" is not actionable for someone looking at a balance sheet.
_STATUS_MESSAGES: Mapping[int, str] = {
    401: "API authentication failed.",
    403: "API authentication failed.",
    404: "Ticker not found. Check the symbol and try again.",
    422: (
        "This company has no XBRL data available — likely a foreign filer or delisted before 2009."
    ),
    429: "Too many requests just now. Wait a moment and try again.",
    502: "SEC EDGAR is unavailable right now. Try again shortly.",
    504: "SEC EDGAR is unavailable right now. Try again shortly.",
}

# 401/403 are a configuration problem on our side. Telling the viewer to retry would send
# them round a loop that cannot terminate (SPEC §7).
_NO_RETRY_STATUSES = frozenset({401, 403})


def message_for_status(status: int, problem: object) -> str:
    """Viewer-facing copy for an HTTP status, optionally enriched by the problem+json body.

    The table always wins. `detail` from the API is appended as context when it is usable,
    never substituted for the table's copy — an upstream wording change must not be able to
    alter what a viewer is told to do about it.
    """
    if status in _STATUS_MESSAGES:
        message = _STATUS_MESSAGES[status]
    else:
        message = f"Something went wrong talking to the fundamentals API (status {status})."

    detail = problem_detail(problem)
    if detail:
        return f"{message}\n\n{detail}"
    return message


def problem_detail(problem: object) -> str:
    """Pull `detail` (falling back to `title`) out of an RFC 7807 body.

    Defensive access is correct *here* and nowhere else: this is the unhappy path, and the
    body may not have come from our API at all — a proxy or load balancer in front of it can
    return an HTML error page under the same status code.
    """
    if not isinstance(problem, Mapping):
        return ""

    for key in ("detail", "title"):
        if key in problem:
            value = problem[key]
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def is_retryable(status: int) -> bool:
    """False for the statuses where advising a retry would be misleading."""
    return status not in _NO_RETRY_STATUSES
