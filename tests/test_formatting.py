"""The value formatter (SPEC §8).

The cases that matter most are the ones that distinguish "not reported" from "reported as
zero". Collapsing those two is the data-integrity bug §7.1 is written to prevent, and it is
invisible on the page — `0` looks like a number somebody filed.
"""

from __future__ import annotations

import pytest

from viewer.errors import DataIntegrityError
from viewer.presentation import MISSING, SHARES, USD, USD_PER_SHARE, check_unit, format_value


class TestUsd:
    def test_scales_to_millions_with_separators_and_no_decimals(self):
        # Apple FY2023 revenue, as filed.
        assert format_value(383_285_000_000.0, USD) == "383,285"

    def test_negative_uses_accounting_parentheses(self):
        assert format_value(-1_234_000_000.0, USD) == "(1,234)"

    def test_rounds_to_the_nearest_million(self):
        assert format_value(1_500_000.0, USD) == "2"
        assert format_value(1_400_000.0, USD) == "1"


class TestPerShare:
    def test_dollars_to_two_decimals_unscaled(self):
        assert format_value(6.13, USD_PER_SHARE) == "6.13"

    def test_negative_eps_in_parentheses(self):
        assert format_value(-0.25, USD_PER_SHARE) == "(0.25)"

    def test_pads_to_two_decimals(self):
        assert format_value(6.0, USD_PER_SHARE) == "6.00"


class TestShares:
    def test_share_counts_scale_to_millions(self):
        # Apple FY2023 weighted average diluted shares, as filed.
        assert format_value(15_812_547_000.0, SHARES) == "15,813"


class TestMissingIsNotZero:
    """SPEC §7.1: never turn absence into a number, or a number into absence."""

    def test_none_renders_as_an_em_dash(self):
        assert format_value(None, USD) == MISSING

    def test_none_never_renders_as_zero_or_nan(self):
        for unit in (USD, USD_PER_SHARE, SHARES):
            rendered = format_value(None, unit)
            assert rendered not in {"0", "0.00", "nan", "NaN", "None", ""}

    def test_reported_zero_renders_as_zero_not_a_dash(self):
        """A company that reported 0 said something. It must not look like silence."""
        assert format_value(0.0, USD) == "0"
        assert format_value(0.0, USD_PER_SHARE) == "0.00"
        assert format_value(0.0, USD) != MISSING

    def test_small_negative_does_not_render_as_minus_zero(self):
        """Formatting the signed value directly would give "-0" here."""
        assert format_value(-400_000.0, USD) == "(0)"


class TestUnitChecking:
    def test_unexpected_unit_raises_rather_than_dashing(self):
        """`revenue` in `shares` is reported-but-wrong, which is not what a dash means."""
        with pytest.raises(DataIntegrityError, match="revenue"):
            check_unit("revenue", 2023, actual=SHARES, expected=USD)

    def test_matching_unit_passes_quietly(self):
        assert check_unit("revenue", 2023, actual=USD, expected=USD) is None

    def test_unknown_unit_raises_instead_of_formatting(self):
        with pytest.raises(DataIntegrityError):
            format_value(1_000_000.0, "widgets")

    def test_unknown_unit_raises_even_when_it_looks_close(self):
        for unit in ("usd", "USD/share", "Shares", ""):
            with pytest.raises(DataIntegrityError):
                format_value(1_000_000.0, unit)
