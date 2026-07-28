"""SEC EDGAR filing links (SPEC §6).

This is the app's reason for existing: every figure traces back to a filing. It is also the
one piece of logic that cannot check its own work — a wrong URL returns a 404 page rather
than an error, so nothing here would notice. Two things stand in for that: the accession is
regex-validated before use, and the template is pinned by `tests/test_edgar_url.py`.

The accession number appears twice in the URL in two different forms — stripped of dashes in
the directory segment, dashes intact in the filename. Getting that backwards is the failure
this module is shaped around.
"""

from __future__ import annotations

import re

from viewer.errors import DataIntegrityError

# 10 digits (the filer's CIK, zero-padded), 2-digit year, 6-digit sequence.
ACCESSION_PATTERN = re.compile(r"\d{10}-\d{2}-\d{6}")

_TEMPLATE = "https://www.sec.gov/Archives/edgar/data/{cik}/{directory}/{accession}-index.htm"


def filing_url(cik: int, accession: str) -> str:
    """The EDGAR filing index page for one accession.

    `cik` goes in unpadded — it is an integer here and EDGAR's archive paths do not pad it —
    while the accession keeps every leading zero it arrived with.
    """
    # fullmatch, not match: `$` would also accept a trailing newline.
    if not ACCESSION_PATTERN.fullmatch(accession):
        raise DataIntegrityError(
            f"Accession {accession!r} is not in the expected NNNNNNNNNN-NN-NNNNNN form, so no "
            "filing link can be built for it."
        )

    return _TEMPLATE.format(cik=cik, directory=accession.replace("-", ""), accession=accession)
