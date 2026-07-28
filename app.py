"""Financial Statement Viewer — Streamlit entrypoint (SPEC §5).

Single page, one company at a time, exact ticker entry. Display only: every number here
passes through from the API unmodified except for unit scaling and display formatting.

The error handling below has two layers on purpose (SPEC §7.1). A failed request stops the
page, because there is nothing to draw. A figure that is present but impossible stops only
the section it appears in, so the remaining statements stay available to diagnose it. What
neither layer ever does is turn a concept a company did not report into an error, or an
error into a quietly missing row.
"""

from __future__ import annotations

from collections.abc import Mapping

import streamlit as st

from viewer import api, presentation
from viewer.errors import ApiError, DataIntegrityError, ViewerError
from viewer.models import (
    Annual,
    Health,
    parse_annual,
    parse_company,
    parse_concept_units,
    parse_health,
)

st.set_page_config(page_title="Financial Statements", layout="wide")

# SPEC §7. Naming the cause is the entire job here: a bare spinner sitting for thirty
# seconds reads as broken, where an explained one reads as slow.
COLD_SPINNER = "Fetching from SEC EDGAR — first load for a new company takes a few seconds."
WARM_SPINNER = "Loading…"


def read_ticker() -> str:
    """The ticker as typed, normalized once, here.

    Uppercasing happens before the value reaches any cached function so that `aapl` and
    `AAPL` share one cache entry and one API call (SPEC §4).
    """
    raw = st.text_input("Ticker", placeholder="AAPL", key="ticker_input")
    return raw.strip().upper()


def load_units() -> Mapping[str, str]:
    """Expected units per concept, from `/concepts` where possible.

    SPEC §6 wants the app to keep rendering if this endpoint changes shape, so a failure
    here falls back to the local map rather than stopping the page. The fallback preserves
    the unit check rather than disabling it — degrading to "no checking" would quietly
    remove a guard, which is the opposite of what §7.1 asks for.
    """
    try:
        return parse_concept_units(api.fetch_concepts())
    except ViewerError as exc:
        st.caption(f"Concept metadata unavailable ({exc}); using built-in unit definitions.")
        return presentation.FALLBACK_UNITS


def coverage_line(annual: Annual) -> str:
    """What the API actually holds, so a short series does not read as an error (SPEC §3)."""
    coverage = annual.coverage
    if coverage.earliest_fiscal_year is None or coverage.latest_fiscal_year is None:
        return "No annual data held."

    years = coverage.years_available
    plural = "year" if years == 1 else "years"
    return f"FY{coverage.earliest_fiscal_year}–FY{coverage.latest_fiscal_year} ({years} {plural})"


def render_header(name: str, annual: Annual, health: Health) -> None:
    st.subheader(f"{name} · CIK {annual.cik}")

    line = coverage_line(annual)
    if health.ok:
        st.caption(f"{line}  ·  ✓ Checks passed")
    else:
        # No inline badge when checks failed — the banner below says it far louder.
        st.caption(line)


def render_health(health: Health) -> None:
    """A red, already-expanded banner when any validation failed (SPEC §7.1).

    This supersedes §5's amber badge. The point of surfacing these is to stop someone
    building a model on bad data, and a collapsed expander does not stop anybody. The
    statements still render below so the failure can be diagnosed.
    """
    if health.ok:
        return

    count = len(health.findings)
    subject = "check" if count == 1 else "checks"
    lines = [
        f"**{count} data quality {subject} failed for this company.** "
        "Figures below are shown as the API returned them — read these before using them."
    ]

    for finding in health.findings:
        when = f"FY{finding.fiscal_year}" if finding.fiscal_year is not None else "all years"
        lines.append(f"- **{finding.check}** · {when} — {finding.message}")
        if finding.observed:
            observed = ", ".join(
                f"{key} = {presentation.format_observed(value)}"
                for key, value in sorted(finding.observed.items())
            )
            lines.append(f"  - Observed: {observed}")

    st.error("\n".join(lines))


def render_drift_warning(annual: Annual) -> None:
    """Concepts the API returned that no row order displays (SPEC §6).

    Rendered above the statements rather than below them. A figure the company reported and
    this app silently dropped is exactly the failure §7.1 exists to prevent, and a warning
    sitting under three long tables is very close to silent.
    """
    undisplayed = presentation.undisplayed_concepts(annual.concept_names())
    if undisplayed:
        st.warning(f"Present in the API but not displayed: {', '.join(undisplayed)}.")


def render_sources(statement: presentation.Statement, annual: Annual) -> None:
    with st.expander("Sources"):
        try:
            sources = presentation.build_sources_frame(statement, annual.years, annual.cik)
        except DataIntegrityError as exc:
            st.error(f"Filing links could not be built: {exc}")
            return

        st.dataframe(
            sources,
            width="stretch",
            hide_index=True,
            column_config={"Filing": st.column_config.LinkColumn("Filing", display_text="EDGAR")},
        )


def render_statement(
    statement: presentation.Statement,
    annual: Annual,
    units: Mapping[str, str],
) -> None:
    st.subheader(statement.title)
    st.caption(presentation.UNIT_NOTE)
    if statement.note:
        st.caption(statement.note)

    try:
        frame = presentation.build_statement_frame(statement, annual.years, units)
    except DataIntegrityError as exc:
        # Section-scoped on purpose: the other statements remain available to diagnose it.
        st.error(f"{statement.title} was not rendered — {exc}")
        return

    if frame.empty:
        st.info(f"No {statement.title.lower()} concepts were reported in any covered year.")
        return

    st.dataframe(frame, width="stretch")
    render_sources(statement, annual)


def render_company(ticker: str) -> None:
    spinner = WARM_SPINNER if api.is_warm(ticker) else COLD_SPINNER

    with st.spinner(spinner):
        annual = parse_annual(api.fetch_annual(ticker), ticker)
        health = parse_health(api.fetch_health(ticker), ticker)
        name = load_company_name(ticker)
        units = load_units()

    api.mark_warm(ticker)

    render_header(name, annual, health)
    render_health(health)
    render_drift_warning(annual)

    if not annual.years:
        st.info(f"The API holds no annual figures for {ticker}.")
        return

    for statement in presentation.STATEMENTS:
        st.divider()
        render_statement(statement, annual, units)


def load_company_name(ticker: str) -> str:
    """The registrant name for the header.

    `/annual` carries no name, so this is the one thing `/companies/{ticker}` is called for;
    coverage still comes from `/annual` as SPEC §3 requires. A failure here degrades to the
    ticker rather than stopping the page: no figure depends on it, and killing a page of
    correct numbers over a cosmetic lookup would be the wrong trade.
    """
    try:
        return parse_company(api.fetch_company(ticker), ticker).name
    except ViewerError:
        st.caption("Company name unavailable — showing the ticker instead.")
        return ticker


def main() -> None:
    st.title("Financial Statements")

    input_column, refresh_column = st.columns([4, 1], vertical_alignment="bottom")
    with input_column:
        ticker = read_ticker()
    with refresh_column:
        refresh = st.button(
            "Refresh",
            width="stretch",
            help="Re-fetch this company, for when the API has a newer filing.",
        )

    if not ticker:
        st.info("Enter a ticker to begin.")
        return

    if refresh:
        api.clear_ticker(ticker)

    try:
        render_company(ticker)
    except ApiError as exc:
        st.error(str(exc))
    except DataIntegrityError as exc:
        st.error(f"The API returned data this viewer will not display: {exc}")


main()
