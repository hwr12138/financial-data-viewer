"""Typed views of the API responses, parsed and validated at the boundary (SPEC §7.1).

Every response is turned into frozen dataclasses the moment it arrives. A missing key or a
wrong type raises *here*, naming the ticker and the field, so that everything downstream can
use plain attribute access. Scattered defensive `.get()` calls are how a silent failure
spreads through a codebase; the whole point of parsing once is to earn the right not to
write them.

What is *not* an error: a concept absent from a year. The API omits rather than zero-fills,
and a software company with no `inventory` line is reporting accurately. Absence is carried
as "the key is not in the dict" and rendered as an em dash.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from viewer.errors import DataIntegrityError

EXPECTED_CURRENCY = "USD"


# -- field accessors -------------------------------------------------------------------
#
# `where` is a human-readable path to the value being read. It is the entire value of these
# helpers: "AAPL /annual FY2019 concept 'revenue': field 'unit' should be a string" tells
# you where to look upstream, where "KeyError: 'unit'" does not.


def _field(payload: Mapping[str, object], key: str, where: str) -> object:
    if key not in payload:
        raise DataIntegrityError(f"{where}: required field {key!r} is missing.")
    return payload[key]


def _mapping(payload: Mapping[str, object], key: str, where: str) -> Mapping[str, object]:
    value = _field(payload, key, where)
    if not isinstance(value, Mapping):
        raise DataIntegrityError(
            f"{where}: field {key!r} should be an object, got {type(value).__name__}."
        )
    return value


def _sequence(payload: Mapping[str, object], key: str, where: str) -> Sequence[object]:
    value = _field(payload, key, where)
    if not isinstance(value, list):
        raise DataIntegrityError(
            f"{where}: field {key!r} should be a list, got {type(value).__name__}."
        )
    return value


def _string(payload: Mapping[str, object], key: str, where: str) -> str:
    value = _field(payload, key, where)
    if not isinstance(value, str):
        raise DataIntegrityError(
            f"{where}: field {key!r} should be a string, got {type(value).__name__} ({value!r})."
        )
    return value


def _optional_string(payload: Mapping[str, object], key: str, where: str) -> str | None:
    value = _field(payload, key, where)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DataIntegrityError(
            f"{where}: field {key!r} should be a string or null, got {type(value).__name__}."
        )
    return value


def _integer(payload: Mapping[str, object], key: str, where: str) -> int:
    value = _field(payload, key, where)
    # bool is a subclass of int; `True` arriving where a fiscal year belongs is a defect.
    if isinstance(value, bool) or not isinstance(value, int):
        raise DataIntegrityError(
            f"{where}: field {key!r} should be an integer, got {type(value).__name__} ({value!r})."
        )
    return value


def _optional_integer(payload: Mapping[str, object], key: str, where: str) -> int | None:
    value = _field(payload, key, where)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise DataIntegrityError(
            f"{where}: field {key!r} should be an integer or null, got {type(value).__name__}."
        )
    return value


def _number(payload: Mapping[str, object], key: str, where: str) -> float:
    value = _field(payload, key, where)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DataIntegrityError(
            f"{where}: field {key!r} should be a number, got {type(value).__name__} ({value!r})."
        )
    number = float(value)
    # NaN and infinity are not figures a filing can contain. Letting either through would
    # put "nan" or "inf" on the page where a real number belongs.
    if number != number or number in (float("inf"), float("-inf")):
        raise DataIntegrityError(f"{where}: field {key!r} is not a finite number ({value!r}).")
    return number


def _boolean(payload: Mapping[str, object], key: str, where: str) -> bool:
    value = _field(payload, key, where)
    if not isinstance(value, bool):
        raise DataIntegrityError(
            f"{where}: field {key!r} should be a boolean, got {type(value).__name__} ({value!r})."
        )
    return value


def _as_object(value: object, where: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DataIntegrityError(f"{where}: expected an object, got {type(value).__name__}.")
    return value


# -- annual ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConceptValue:
    """One reported figure, with the provenance that lets it be traced to a filing.

    `accession` here is the per-concept one, which is authoritative: a single 10-K restates
    the income statement three years back but the balance sheet only two, so two concepts in
    the same fiscal year legitimately come from different filings.
    """

    value: float
    unit: str
    source_tag: str
    derivation: str
    accession: str
    filed: str
    period_end: str


@dataclass(frozen=True, slots=True)
class YearBlock:
    fiscal_year: int
    period_end: str
    concepts: Mapping[str, ConceptValue]


@dataclass(frozen=True, slots=True)
class Coverage:
    """What the API actually holds. Never inferred from the length of `years`."""

    earliest_fiscal_year: int | None
    latest_fiscal_year: int | None
    years_available: int


@dataclass(frozen=True, slots=True)
class Annual:
    ticker: str | None
    cik: int
    currency: str
    coverage: Coverage
    years: tuple[YearBlock, ...]

    def concept_names(self) -> frozenset[str]:
        """Every concept name the API returned, across all years.

        Feeds the SPEC §6 drift guard. Concepts vary by year, so this is a union rather than
        a look at any single year.
        """
        names: set[str] = set()
        for year in self.years:
            names.update(year.concepts)
        return frozenset(names)


def parse_annual(payload: object, ticker: str) -> Annual:
    """Validate a `/companies/{ticker}/annual` response into an `Annual`."""
    where = f"{ticker} /annual"
    body = _as_object(payload, where)

    currency = _string(body, "currency", where)
    if currency != EXPECTED_CURRENCY:
        # Every format rule and the "USD in millions" header assume USD. Rendering a
        # non-USD response under a USD heading would misstate the figures.
        raise DataIntegrityError(
            f"{where}: currency is {currency!r}, but this viewer only formats {EXPECTED_CURRENCY}."
        )

    coverage_body = _mapping(body, "coverage", where)
    coverage_where = f"{where} coverage"
    coverage = Coverage(
        earliest_fiscal_year=_optional_integer(
            coverage_body, "earliest_fiscal_year", coverage_where
        ),
        latest_fiscal_year=_optional_integer(coverage_body, "latest_fiscal_year", coverage_where),
        years_available=_integer(coverage_body, "years_available", coverage_where),
    )

    years: list[YearBlock] = []
    for entry in _sequence(body, "years", where):
        year_body = _as_object(entry, f"{where} years[]")
        fiscal_year = _integer(year_body, "fiscal_year", f"{where} years[]")
        year_where = f"{where} FY{fiscal_year}"

        concepts: dict[str, ConceptValue] = {}
        for name, raw in _mapping(year_body, "concepts", year_where).items():
            concept_where = f"{year_where} concept {name!r}"
            concept_body = _as_object(raw, concept_where)
            concepts[name] = ConceptValue(
                value=_number(concept_body, "value", concept_where),
                unit=_string(concept_body, "unit", concept_where),
                source_tag=_string(concept_body, "source_tag", concept_where),
                derivation=_string(concept_body, "derivation", concept_where),
                accession=_string(concept_body, "accession", concept_where),
                filed=_string(concept_body, "filed", concept_where),
                period_end=_string(concept_body, "period_end", concept_where),
            )

        years.append(
            YearBlock(
                fiscal_year=fiscal_year,
                period_end=_string(year_body, "period_end", year_where),
                concepts=concepts,
            )
        )

    return Annual(
        ticker=_optional_string(body, "ticker", where),
        cik=_integer(body, "cik", where),
        currency=currency,
        coverage=coverage,
        years=tuple(years),
    )


# -- company ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Company:
    """Registrant metadata. Fetched only for `name`, which `/annual` does not carry."""

    cik: int
    ticker: str | None
    name: str


def parse_company(payload: object, ticker: str) -> Company:
    where = f"{ticker} /companies"
    body = _as_object(payload, where)
    return Company(
        cik=_integer(body, "cik", where),
        ticker=_optional_string(body, "ticker", where),
        name=_string(body, "name", where),
    )


# -- health ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Finding:
    check: str
    fiscal_year: int | None
    message: str
    observed: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class Health:
    ok: bool
    years_checked: int
    checks_run: tuple[str, ...]
    findings: tuple[Finding, ...]


def parse_health(payload: object, ticker: str) -> Health:
    where = f"{ticker} /health"
    body = _as_object(payload, where)

    checks_run: list[str] = []
    for entry in _sequence(body, "checks_run", where):
        if not isinstance(entry, str):
            raise DataIntegrityError(
                f"{where}: checks_run should contain strings, got {type(entry).__name__}."
            )
        checks_run.append(entry)

    findings: list[Finding] = []
    for entry in _sequence(body, "findings", where):
        finding_where = f"{where} findings[]"
        finding_body = _as_object(entry, finding_where)

        observed_body = _mapping(finding_body, "observed", finding_where)
        observed = {key: _number(observed_body, key, finding_where) for key in observed_body}

        findings.append(
            Finding(
                check=_string(finding_body, "check", finding_where),
                fiscal_year=_optional_integer(finding_body, "fiscal_year", finding_where),
                message=_string(finding_body, "message", finding_where),
                observed=observed,
            )
        )

    return Health(
        ok=_boolean(body, "ok", where),
        years_checked=_integer(body, "years_checked", where),
        checks_run=tuple(checks_run),
        findings=tuple(findings),
    )


# -- concepts --------------------------------------------------------------------------


def parse_concept_units(payload: object) -> dict[str, str]:
    """Validate `/concepts` into concept name -> expected unit.

    The unit is the only field this app consumes. `/concepts` carries no display label —
    its `description` is a paragraph, not a label — so labels come from
    `presentation.LABELS` instead, and the rest of the definition is not read.

    This mapping is the authority for the SPEC §6 unit check: it is what makes "revenue
    arrived denominated in shares" detectable rather than merely odd-looking.
    """
    where = "/concepts"
    body = _as_object(payload, where)

    units: dict[str, str] = {}
    for entry in _sequence(body, "concepts", where):
        entry_body = _as_object(entry, f"{where} concepts[]")
        name = _string(entry_body, "name", f"{where} concepts[]")
        units[name] = _string(entry_body, "unit", f"{where} {name!r}")

    return units
