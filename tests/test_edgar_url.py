"""The filing URL builder (SPEC §8).

This is tested because it cannot fail loudly in production. A wrong URL returns an EDGAR 404
page, not an error, so the app would go on linking every figure to nothing and nobody would
find out. The known-good case below was confirmed against the live archive.
"""

from __future__ import annotations

import pytest

from viewer.edgar import filing_url
from viewer.errors import DataIntegrityError


def test_known_good_case_from_spec():
    """The accession appears twice, in two different forms — the whole point of the test."""
    assert filing_url(cik=320193, accession="0000320193-24-000123") == (
        "https://www.sec.gov/Archives/edgar/data/320193"
        "/000032019324000123/0000320193-24-000123-index.htm"
    )


def test_directory_segment_strips_dashes_and_filename_keeps_them():
    url = filing_url(cik=320193, accession="0000320193-24-000123")
    directory, filename = url.rsplit("/", 2)[1:]

    assert directory == "000032019324000123"
    assert "-" not in directory
    assert filename == "0000320193-24-000123-index.htm"


def test_low_cik_is_not_zero_padded_in_the_path():
    """CIKs are integers here but appear zero-padded in other EDGAR contexts.

    Padding the path segment produces a 404, so the two forms must not be confused.
    """
    url = filing_url(cik=1750, accession="0000001750-24-000012")

    assert "/data/1750/" in url
    assert "/data/0000001750/" not in url


def test_accession_leading_zeros_survive():
    """The accession's own zero padding is significant and must not be trimmed."""
    url = filing_url(cik=1750, accession="0000001750-24-000012")

    assert url.endswith("/000000175024000012/0000001750-24-000012-index.htm")


@pytest.mark.parametrize(
    "accession",
    [
        "0000320193-24-00012",  # sequence too short
        "000032019-24-000123",  # CIK block too short
        "0000320193-2024-000123",  # year block too long
        "000032019324000123",  # dashes stripped entirely
        "0000320193/24/000123",  # wrong separator
        "",
        "0000320193-24-000123\n",  # trailing newline: `$` would have allowed this
    ],
)
def test_malformed_accession_raises(accession: str):
    """Better a visible error than a link that quietly 404s (SPEC §7.1)."""
    with pytest.raises(DataIntegrityError):
        filing_url(cik=320193, accession=accession)
