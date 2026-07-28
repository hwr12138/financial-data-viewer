"""Financial Statement Viewer — Streamlit entrypoint (SPEC §5).

Single page, one company at a time, exact ticker entry. Display only: every number here
passes through from the API unmodified except for unit scaling and formatting.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Financial Statements", layout="wide")


def read_ticker() -> str:
    """The ticker as typed, normalized once, here.

    Uppercasing happens before the value reaches any cached function so that `aapl` and
    `AAPL` share one cache entry and one API call (SPEC §4).
    """
    raw = st.text_input("Ticker", placeholder="AAPL", key="ticker_input")
    return raw.strip().upper()


def main() -> None:
    st.title("Financial Statements")

    input_column, refresh_column = st.columns([4, 1], vertical_alignment="bottom")
    with input_column:
        ticker = read_ticker()
    with refresh_column:
        st.button("Refresh", width="stretch")

    if not ticker:
        st.info("Enter a ticker to begin.")
        return

    st.write(f"Ticker: {ticker}")
    st.write(f"API base URL configured: {'API_BASE_URL' in st.secrets}")
    st.write(f"API key configured: {'API_KEY' in st.secrets}")


main()
