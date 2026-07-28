"""Presentation logic — row order, labels, units, formatting (SPEC §6, §12).

All of it lives here rather than being scattered through the render code. The row orders in
particular are presentation decisions that belong to the viewer, not to the API: `/concepts`
reports which statement a concept belongs to but says nothing about the order an analyst
expects to read it in.

Two rules from §7.1 shape everything below:

* Formatting produces **strings**, and DataFrames are built from strings only. pandas
  coerces gaps to `NaN`, renders them as `nan`, and lets a stray numeric operation produce a
  wrong figure silently. An all-string frame can do neither, and the app performs no
  arithmetic, so nothing is lost.
* A missing concept becomes `—`. A concept present with an impossible unit **raises**. The
  dash means "the company did not report this"; using it for "reported, but wrong" would
  destroy the only distinction that makes the dash trustworthy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from viewer.edgar import filing_url
from viewer.errors import DataIntegrityError
from viewer.models import YearBlock

# -- units -----------------------------------------------------------------------------

USD = "USD"
USD_PER_SHARE = "USD/shares"
SHARES = "shares"

MISSING = "—"
MILLIONS = 1_000_000

UNIT_NOTE = "USD in millions, except per-share amounts."


# -- row order -------------------------------------------------------------------------
#
# SPEC §6. Fixed, and deliberately not fetched from /concepts.

INCOME_STATEMENT_ROWS: tuple[str, ...] = (
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "rnd_expense",
    "sga_expense",
    "operating_income",
    "interest_expense",
    "pretax_income",
    "income_tax_expense",
    "net_income",
    "eps_basic",
    "eps_diluted",
    "shares_basic",
    "shares_diluted",
)

BALANCE_SHEET_ROWS: tuple[str, ...] = (
    "cash_and_equivalents",
    "short_term_investments",
    "accounts_receivable",
    "inventory",
    "total_current_assets",
    "ppe_net",
    "goodwill",
    "total_assets",
    "accounts_payable",
    "total_current_liabilities",
    "short_term_debt",
    "long_term_debt",
    "total_liabilities",
    "total_equity",
)

CASH_FLOW_ROWS: tuple[str, ...] = (
    "cfo",
    "depreciation_amortization",
    "stock_based_compensation",
    "cfi",
    "capex",
    "cff",
    "dividends_paid",
    "share_repurchases",
)


@dataclass(frozen=True, slots=True)
class Statement:
    title: str
    rows: tuple[str, ...]


STATEMENTS: tuple[Statement, ...] = (
    Statement("Income Statement", INCOME_STATEMENT_ROWS),
    Statement("Balance Sheet", BALANCE_SHEET_ROWS),
    Statement("Cash Flow", CASH_FLOW_ROWS),
)

DISPLAYED_CONCEPTS: frozenset[str] = frozenset(
    concept for statement in STATEMENTS for concept in statement.rows
)


# -- labels ----------------------------------------------------------------------------
#
# `/concepts` carries no display label — its `description` is a full paragraph — so this map
# is the label source rather than the fallback SPEC §6 anticipated. Descriptions from
# `/concepts` are still used, as row help text.

LABELS: Mapping[str, str] = {
    "revenue": "Revenue",
    "cost_of_revenue": "Cost of revenue",
    "gross_profit": "Gross profit",
    "rnd_expense": "Research and development",
    "sga_expense": "Selling, general and administrative",
    "operating_income": "Operating income",
    "interest_expense": "Interest expense",
    "pretax_income": "Pretax income",
    "income_tax_expense": "Income tax expense",
    "net_income": "Net income",
    "eps_basic": "EPS, basic",
    "eps_diluted": "EPS, diluted",
    "shares_basic": "Shares, basic (weighted average)",
    "shares_diluted": "Shares, diluted (weighted average)",
    "cash_and_equivalents": "Cash and equivalents",
    "short_term_investments": "Short-term investments",
    "accounts_receivable": "Accounts receivable",
    "inventory": "Inventory",
    "total_current_assets": "Total current assets",
    "ppe_net": "Property, plant and equipment, net",
    "goodwill": "Goodwill",
    "total_assets": "Total assets",
    "accounts_payable": "Accounts payable",
    "total_current_liabilities": "Total current liabilities",
    "short_term_debt": "Short-term debt",
    "long_term_debt": "Long-term debt",
    "total_liabilities": "Total liabilities",
    "total_equity": "Total equity",
    "cfo": "Cash from operations",
    "depreciation_amortization": "Depreciation and amortization",
    "stock_based_compensation": "Stock-based compensation",
    "cfi": "Cash from investing",
    "capex": "Capital expenditure",
    "cff": "Cash from financing",
    "dividends_paid": "Dividends paid",
    "share_repurchases": "Share repurchases",
}

# Used only if `/concepts` is unreachable or changes shape, so the app still renders and
# still enforces the §6 unit check. Mirrors the API's own concept definitions.
FALLBACK_UNITS: Mapping[str, str] = {
    **{concept: USD for concept in DISPLAYED_CONCEPTS},
    "eps_basic": USD_PER_SHARE,
    "eps_diluted": USD_PER_SHARE,
    "shares_basic": SHARES,
    "shares_diluted": SHARES,
}


def _check_tables() -> None:
    """Fail at import if the tables above disagree with each other.

    A concept without a label would raise later, mid-render. A *duplicated* label is worse:
    two concepts would collapse into one DataFrame row and the page would look fine.
    """
    missing_labels = sorted(DISPLAYED_CONCEPTS - set(LABELS))
    if missing_labels:
        raise ValueError(f"presentation.LABELS is missing: {', '.join(missing_labels)}")

    missing_units = sorted(DISPLAYED_CONCEPTS - set(FALLBACK_UNITS))
    if missing_units:
        raise ValueError(f"presentation.FALLBACK_UNITS is missing: {', '.join(missing_units)}")

    labels = [LABELS[concept] for concept in sorted(DISPLAYED_CONCEPTS)]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise ValueError(f"presentation.LABELS has duplicate labels: {', '.join(duplicates)}")


_check_tables()


# -- formatting ------------------------------------------------------------------------


def format_value(value: float | None, unit: str) -> str:
    """One figure as it appears in a table cell (SPEC §6).

    `None` means the company did not report the concept for that year and renders as an em
    dash. An unrecognized unit raises rather than falling back to a dash, because a dash
    would claim the figure was never reported.
    """
    if value is None:
        return MISSING

    if unit in (USD, SHARES):
        magnitude = f"{abs(value) / MILLIONS:,.0f}"
    elif unit == USD_PER_SHARE:
        magnitude = f"{abs(value):,.2f}"
    else:
        raise DataIntegrityError(
            f"Cannot format a value with unit {unit!r}. Expected one of "
            f"{USD!r}, {USD_PER_SHARE!r} or {SHARES!r}."
        )

    # Sign is applied to the formatted magnitude rather than the raw value: formatting a
    # small negative directly yields "-0", and accounting convention wants parentheses.
    return f"({magnitude})" if value < 0 else magnitude


def check_unit(concept: str, fiscal_year: int, actual: str, expected: str) -> None:
    """Raise when a concept arrives in a unit it cannot legitimately have (SPEC §6, §7.1).

    `revenue` denominated in `shares` is not a gap to paper over with a dash — it is a
    figure that exists and is wrong, and the section must not draw.
    """
    if actual != expected:
        raise DataIntegrityError(
            f"{concept} FY{fiscal_year}: unit is {actual!r}, expected {expected!r}. This value "
            "was reported, so it is not rendered as a dash."
        )


def expected_unit(concept: str, units: Mapping[str, str]) -> str:
    """The unit `concept` must arrive in, preferring `/concepts` over the local fallback."""
    if concept in units:
        return units[concept]
    if concept in FALLBACK_UNITS:
        return FALLBACK_UNITS[concept]
    raise DataIntegrityError(f"No expected unit is known for concept {concept!r}.")


def column_label(fiscal_year: int) -> str:
    return f"FY{fiscal_year}"


def format_observed(value: float) -> str:
    """A raw diagnostic figure from a `/health` finding.

    Deliberately unscaled: `observed` mixes balance-sheet dollars with ratios like a
    year-on-year `change` of 22.0, and putting either through the millions formatter would
    misreport one of them. These are evidence for a human, not table figures.
    """
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:,.4g}"


# -- tables ----------------------------------------------------------------------------


def build_statement_frame(
    statement: Statement,
    years: Sequence[YearBlock],
    units: Mapping[str, str],
) -> pd.DataFrame:
    """Rows are concepts in §6 order, columns are fiscal years, most recent leftmost.

    A concept with no value in any displayed year is dropped entirely rather than drawn as a
    row of dashes. Every cell is a pre-formatted string.
    """
    ordered = sorted(years, key=lambda year: year.fiscal_year, reverse=True)
    columns = [column_label(year.fiscal_year) for year in ordered]

    index: list[str] = []
    cells: list[list[str]] = []

    for concept in statement.rows:
        expected = expected_unit(concept, units)
        row: list[str] = []
        reported_anywhere = False

        for year in ordered:
            if concept in year.concepts:
                value = year.concepts[concept]
                check_unit(concept, year.fiscal_year, value.unit, expected)
                row.append(format_value(value.value, value.unit))
                reported_anywhere = True
            else:
                row.append(MISSING)

        if reported_anywhere:
            index.append(LABELS[concept])
            cells.append(row)

    frame = pd.DataFrame(cells, index=index, columns=columns, dtype="string")
    # The label column is the frozen first column Streamlit renders from the index; it needs
    # no header of its own.
    frame.index.name = ""
    return frame


def build_sources_frame(
    statement: Statement,
    years: Sequence[YearBlock],
    cik: int,
) -> pd.DataFrame:
    """`concept | fiscal year | source_tag | filing` for one statement (SPEC §6).

    The accession comes from the *concept*, not the year block. A single 10-K can restate the
    income statement three years back and the balance sheet only two, so concepts within one
    fiscal year legitimately trace to different filings; the year-level accession would
    mislink a good share of these rows.

    No separate derivation column: the API already folds it into `source_tag`, which reads
    `GrossProfit` when reported directly and `Revenues - CostOfRevenue` when computed.
    """
    ordered = sorted(years, key=lambda year: year.fiscal_year, reverse=True)

    records: list[dict[str, str]] = []
    for concept in statement.rows:
        for year in ordered:
            if concept not in year.concepts:
                continue
            value = year.concepts[concept]
            records.append(
                {
                    "Concept": concept,
                    "Fiscal year": column_label(year.fiscal_year),
                    "Source tag": value.source_tag,
                    "Filing": filing_url(cik, value.accession),
                }
            )

    return pd.DataFrame.from_records(
        records,
        columns=["Concept", "Fiscal year", "Source tag", "Filing"],
    )


def undisplayed_concepts(present: frozenset[str]) -> tuple[str, ...]:
    """Concepts the API returned that no row order displays (SPEC §6 drift guard).

    The orderings live here and the concept definitions live upstream, so a concept added to
    the API would otherwise vanish from the viewer with no error at all.
    """
    return tuple(sorted(present - DISPLAYED_CONCEPTS))
