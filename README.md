# Financial Statement Viewer

A read-only Streamlit app that displays annual financial statements for one US public
company at a time, sourced from a private EDGAR fundamentals API.

Type an exact ticker. There is no search, autocomplete, or company browser. The app does no
arithmetic: figures pass through from the API unmodified except for unit scaling and display
formatting. Every figure links back to the SEC filing it came from.

## Running locally

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
```

Copy the secrets template and fill in the real values:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

`.streamlit/secrets.toml` is gitignored and must stay that way. A key committed once is a
key that has to be rotated on the API server.

```bash
.venv/bin/streamlit run app.py
```

## Tests and lint

Both test files are pure functions — no network, no Streamlit — and cover the two things
that fail silently in production: the filing URL builder (a wrong URL returns a 404 page
rather than an error) and the value formatter (rendering a missing figure as `0` looks like
data).

```bash
.venv/bin/python -m pytest
```

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

`ruff` enforces `E722` (no bare `except`) per SPEC §7.1, and `ANN` for the type hints §12
requires.

## Deploying to Streamlit Community Cloud

1. Push to a **private** GitHub repo. Streamlit needs the `repo` OAuth scope for private
   repos and creates a read-only deploy key; GitHub notifies repo admins when it does.
2. Deploy from the Community Cloud dashboard — repo, branch, entrypoint `app.py`.
3. Set app visibility to **private** and add viewer emails to the allowlist.
4. Enter `API_BASE_URL` and `API_KEY` in the app's settings UI. They are never committed.
5. Confirm in a fresh browser session that login is required and a non-allowlisted address
   is denied.

`requirements.txt` and `.streamlit/` sit at the repo root because Community Cloud
initializes from the root regardless of where the entrypoint lives.

The app sleeps after ~12 hours without traffic and the next visitor sees a wake-up page.
That is expected. Cache clears on sleep and on redeploy, which is fine — the upstream API is
the real cache.

## Notes on the API contract

Two details of the deployed API differ from what SPEC §3 and §6 assume, and the code
resolves them like this:

- **The company name is not in `/annual`.** That response carries `ticker`, `cik`,
  `currency`, `coverage` and `years` only. `name` exists solely on `/companies/{ticker}`, so
  the app calls it for the name alone. Coverage still comes from `/annual`, which is what
  §3's "do not call both" is about.
- **`/concepts` carries no display label.** Its `description` is a full paragraph, so
  `LABELS` in `viewer/presentation.py` is the label source rather than the fallback §6
  anticipated. `/concepts` is still fetched, because its `unit` field is the authority for
  the §6 check that raises when a concept arrives in a unit it cannot legitimately have.

Provenance uses the **per-concept** accession, not the year block's. A single 10-K can
restate the income statement three years back and the balance sheet only two, so concepts
within one fiscal year legitimately trace to different filings.

### Why capex is not shown negative

`capex`, `dividends_paid` and `share_repurchases` are cash outflows, but the API serves them
**positive**, because the underlying XBRL facts are payments and are filed positive. The
filing's own statement shows them in parentheses via a negated presentation label.

The viewer does not negate them, and the Cash Flow section carries a caption saying so. The
alternative — flipping signs for display — was considered and rejected:

- The API's convention is load-bearing upstream. It is pinned by dedicated tests, stated in
  the OpenAPI description consumers read, and `cfo - capex` is the documented way to reach
  free cash flow. Flipping it there would turn that subtraction into an addition silently.
- Negating `capex` but not `cost_of_revenue` or `income_tax_expense`, which are equally
  positive magnitudes of things that reduce a total, would be arbitrary. Negating all of
  them would mean the viewer re-derives the statement's sign conventions, which SPEC §12
  rules out.
- A wrong entry in a negation table produces a plausible wrong number that the app has no
  way to detect — the same blind spot §7.1 describes for scale errors.

`POSITIVE_OUTFLOWS` in `viewer/presentation.py` names the affected concepts, and the caption
is generated from it so the wording cannot drift from the rows it describes.

## Layout

```
app.py                  Streamlit entrypoint — layout, state, section wiring
viewer/api.py           httpx client, X-API-Key, 90s timeout, cached wrappers
viewer/models.py        dataclasses + boundary parsing; raises on malformed data
viewer/presentation.py  row order, labels, units, formatting (SPEC §12: one module)
viewer/edgar.py         accession validation + filing URL builder
viewer/errors.py        error types + the SPEC §7 status-to-message table
```

`presentation.py` and `edgar.py` deliberately import neither Streamlit nor httpx, which is
what keeps the tests pure.
