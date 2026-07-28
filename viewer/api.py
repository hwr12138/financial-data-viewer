"""HTTP access to the fundamentals API (SPEC §3, §4).

Caching is the load-bearing decision here. Streamlit re-runs the whole script on every
widget interaction, so an uncached call would issue a fresh request per click. `cache_data`
is keyed on arguments and shared across sessions in the process, which means two viewers
looking at the same ticker cost one API call — provided the ticker is normalized to
uppercase *before* it arrives, which happens in `app.read_ticker`.

Exceptions are deliberately not cached: `cache_data` stores nothing when a function raises,
so a transient 502 does not stick around for an hour.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from viewer.errors import (
    TIMEOUT_MESSAGE,
    UNREACHABLE_MESSAGE,
    ApiError,
    DataIntegrityError,
    message_for_status,
)

# SPEC §3: the first request for an uncached ticker blocks while the API ingests and parses
# filings from SEC EDGAR. Anything shorter cuts off requests that are working correctly.
TIMEOUT_SECONDS = 90.0

_ANNUAL_TTL = 3600
_HEALTH_TTL = 3600
_COMPANY_TTL = 3600
_CONCEPTS_TTL = 86400


def _secret(name: str) -> str:
    """Read a secret, failing with copy that says what to do about it.

    A missing secret is a configuration problem, not something a viewer can retry, so it
    surfaces the same way an auth failure does.
    """
    try:
        configured = name in st.secrets
    except StreamlitSecretNotFoundError as exc:
        # Raised when there is no secrets file at all, as opposed to one missing a key.
        raise ApiError(
            "No secrets are configured. Copy .streamlit/secrets.toml.example to "
            ".streamlit/secrets.toml and fill it in, or set the values in the Community "
            "Cloud app settings."
        ) from exc

    if not configured:
        raise ApiError(f"{name} is not configured in Streamlit secrets.")

    value = st.secrets[name]
    if not isinstance(value, str) or not value.strip():
        raise ApiError(f"{name} in Streamlit secrets is empty or not a string.")
    return value.strip()


def _get(path: str) -> dict[str, object]:
    """One GET against the API, with every failure mapped to SPEC §7 copy."""
    base_url = _secret("API_BASE_URL")
    api_key = _secret("API_KEY")

    try:
        with httpx.Client(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
        ) as client:
            response = client.get(path)
    except httpx.TimeoutException as exc:
        # Subclass of HTTPError, so this must be caught first.
        raise ApiError(TIMEOUT_MESSAGE) from exc
    except httpx.HTTPError as exc:
        raise ApiError(UNREACHABLE_MESSAGE) from exc

    if response.status_code != httpx.codes.OK:
        raise ApiError(message_for_status(response.status_code, _problem_body(response)))

    try:
        payload = response.json()
    except ValueError as exc:
        raise DataIntegrityError(
            f"{path}: the API returned a {response.status_code} that is not valid JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise DataIntegrityError(f"{path}: expected a JSON object, got {type(payload).__name__}.")
    return payload


def _problem_body(response: httpx.Response) -> object:
    """The RFC 7807 body, or None when the error response is not JSON at all.

    A proxy in front of the API can return an HTML error page under the same status code, so
    this cannot assume it will parse.
    """
    try:
        return response.json()
    except ValueError:
        return None


@st.cache_data(ttl=_ANNUAL_TTL, show_spinner=False)
def fetch_annual(ticker: str) -> dict[str, object]:
    return _get(f"/companies/{quote(ticker, safe='')}/annual")


@st.cache_data(ttl=_HEALTH_TTL, show_spinner=False)
def fetch_health(ticker: str) -> dict[str, object]:
    return _get(f"/companies/{quote(ticker, safe='')}/health")


@st.cache_data(ttl=_COMPANY_TTL, show_spinner=False)
def fetch_company(ticker: str) -> dict[str, object]:
    """Fetched for the registrant name only — `/annual` does not carry one.

    SPEC §3 rules out calling this *for coverage*, which `/annual` already provides. The
    company name in the §5 header exists on no other endpoint.
    """
    return _get(f"/companies/{quote(ticker, safe='')}")


@st.cache_data(ttl=_CONCEPTS_TTL, show_spinner=False)
def fetch_concepts() -> dict[str, object]:
    return _get("/concepts")


# -- spinner copy ----------------------------------------------------------------------
#
# SPEC §7 distinguishes a warm load from a cold one, but Streamlit exposes no "is this
# cached?" predicate. This set tracks what has been fetched in this process — the same scope
# `cache_data` uses — and is cleared alongside the cache. If it is ever out of step (a TTL
# expiring between renders, say) the only consequence is spinner wording, and a warm hit
# renders too fast for the text to be read anyway.
_fetched_in_process: set[str] = set()


def is_warm(ticker: str) -> bool:
    return ticker in _fetched_in_process


def mark_warm(ticker: str) -> None:
    _fetched_in_process.add(ticker)


def clear_ticker(ticker: str) -> None:
    """Drop every cached response for one ticker (SPEC §4's "Refresh data" control).

    All three endpoints go together. Refreshing the numbers while leaving a stale health
    report above them would put an out-of-date quality verdict over fresh data.
    """
    fetch_annual.clear(ticker)
    fetch_health.clear(ticker)
    fetch_company.clear(ticker)
    _fetched_in_process.discard(ticker)
