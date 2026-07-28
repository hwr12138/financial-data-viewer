# Financial Statement Viewer — Build Spec

## 0. How to use this document

This is a complete specification for a companion app to an existing, deployed API.
Architecture decisions are **already made** — do not re-litigate them or propose alternative
stacks. If something here is genuinely contradictory or impossible, stop and ask rather than
improvising.

Start in Plan Mode. Read this file in full, then produce a build plan before writing code.
Work in the order given in §10.

**The upstream API is finished and requires no changes.** Do not propose modifications to it.

---

## 1. Goal

A read-only Streamlit app that displays annual financial statements for a single US public
company at a time, sourced from a private EDGAR fundamentals API.

Personal use. Three or four viewers. A handful of sessions per week.

The user types an exact ticker. There is no search, autocomplete, or company browser.

---

## 2. Fixed decisions

| Decision | Choice |
|---|---|
| Framework | Streamlit |
| Hosting | Streamlit Community Cloud, **private app** |
| Auth | Community Cloud viewer allowlist (email) |
| Repo | Private GitHub repo |
| Data source | Existing fundamentals API over HTTPS |
| Credential | Static API key in `X-API-Key`, from `st.secrets` |
| HTTP client | `httpx` |
| Caching | `@st.cache_data`, TTL 1 hour |
| Scope | Display only — no export, no calculations, no comparison |

### Community Cloud constraints to design within

- ~1 GB memory ceiling. Cached API responses are small (a few hundred KB of JSON each), so
  even 100 cached companies is tens of MB. Do not load anything large into memory.
- App sleeps after ~12 hours without traffic; the next visitor sees a wake-up page. This is
  expected, not a bug to solve.
- One private app per account. Do not design anything that needs a second app.
- No custom domain. The app lives on a `*.streamlit.app` URL.
- Cache clears on sleep and on redeploy. That is fine — the upstream API is the real cache.

---

## 3. Upstream API contract

Base URL and key come from `st.secrets`. Every request sends `X-API-Key`.

### Endpoints used

```
GET /companies/{ticker}/annual        primary data + coverage
GET /companies/{ticker}/health        validation results for the quality badge
GET /concepts                         concept metadata (labels, descriptions)
```

`/companies/{ticker}` is redundant here — `/annual` already carries the coverage block.
Do not call both.

### Response shape

```json
{
  "ticker": "AAPL",
  "cik": 320193,
  "currency": "USD",
  "coverage": {
    "earliest_fiscal_year": 2009,
    "latest_fiscal_year": 2024,
    "years_available": 16
  },
  "years": [
    {
      "fiscal_year": 2024,
      "period_end": "2024-09-28",
      "accession": "0000320193-24-000123",
      "filed": "2024-11-01",
      "concepts": {
        "revenue": {
          "value": 391035000000.0,
          "unit": "USD",
          "source_tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
          "derivation": "direct"
        }
      }
    }
  ]
}
```

### Critical semantics

**A missing concept is omitted, not zero.** The API never zero-fills. Render absent values
as an em dash `—`. Rendering them as `0` would be a data-integrity bug, not a cosmetic one.

**Concepts vary by year.** A company can report `revenue` in 2015 and not 2016, or resolve
it from a different `source_tag`. Never assume a concept present in one year exists in all.

**Coverage is not 30 years.** Realistic depth is ~2009–present and varies per company.
Display actual coverage prominently rather than letting a short series look like an error.

### Cold fetches

The API ingests from SEC EDGAR on demand. The first request for an uncached ticker blocks
for several seconds while it fetches and parses. Set the `httpx` timeout to **90 seconds**
and show an honest spinner (§7).

---

## 4. Caching — the load-bearing decision

Streamlit re-runs the entire script on every widget interaction. Without caching, each click
issues a fresh API call, which will trip the upstream rate limit with a single active user.

Wrap every API call:

```python
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_annual(ticker: str) -> dict: ...

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_health(ticker: str) -> dict: ...

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_concepts() -> dict: ...
```

`show_spinner=False` because §7 defines custom spinner copy.

`st.cache_data` is keyed on arguments and shared across all sessions in the process, so two
viewers looking at the same ticker cost one API call. Normalize the ticker to uppercase
**before** it reaches the cached function, or `aapl` and `AAPL` become separate cache
entries and separate API calls.

Provide a small "Refresh data" control that calls `fetch_annual.clear()` for the current
ticker, for when the upstream cache has been refreshed with a newer filing.

---

## 5. Layout

Single page. No multipage navigation.

```
┌────────────────────────────────────────────────┐
│  Ticker input  [AAPL          ]  [Refresh]     │
├────────────────────────────────────────────────┤
│  Apple Inc.  ·  CIK 320193                     │
│  FY2009–FY2024 (16 years)  ·  ✓ Checks passed  │
├────────────────────────────────────────────────┤
│  Income Statement                              │
│    [table: concepts × years]                   │
│    ▸ Sources                                   │
│                                                │
│  Balance Sheet                                 │
│    [table]                                     │
│    ▸ Sources                                   │
│                                                │
│  Cash Flow                                     │
│    [table]                                     │
│    ▸ Sources                                   │
└────────────────────────────────────────────────┘
```

Ticker input: `st.text_input`, uppercased on read, stripped of whitespace. Empty input shows
a neutral prompt, not an error.

Coverage line always visible. Health badge from `/health`: green check if all validations
passed, amber warning with an expander listing failures otherwise. Do not hide failures —
the point of the badge is to stop someone building a model on bad data.

---

## 6. Table rendering

Build a `pandas` DataFrame per statement, then `st.dataframe(df, use_container_width=True)`.
Set the concept label as the DataFrame **index** — Streamlit renders the index as a frozen
first column, which is what makes 16 year-columns usable on horizontal scroll.

**Rows** = concepts, in the fixed order below. **Columns** = fiscal years, most recent
leftmost.

Omit a concept row entirely if it has no values in any displayed year. Do not render an
all-dashes row.

### Row order

**Income Statement**
`revenue`, `cost_of_revenue`, `gross_profit`, `rnd_expense`, `sga_expense`,
`operating_income`, `interest_expense`, `pretax_income`, `income_tax_expense`, `net_income`,
`eps_basic`, `eps_diluted`, `shares_basic`, `shares_diluted`

**Balance Sheet**
`cash_and_equivalents`, `short_term_investments`, `accounts_receivable`, `inventory`,
`total_current_assets`, `ppe_net`, `goodwill`, `total_assets`, `accounts_payable`,
`total_current_liabilities`, `short_term_debt`, `long_term_debt`, `total_liabilities`,
`total_equity`

**Cash Flow**
`cfo`, `depreciation_amortization`, `stock_based_compensation`, `cfi`, `capex`, `cff`,
`dividends_paid`, `share_repurchases`

This ordering is presentation logic and lives in the app, in a single module-level constant.
It is not fetched from `/concepts`.

**Drift guard.** Because the ordering lists live here and the concept definitions live in the
API, a concept added upstream will be absent from the viewer with no error. After building
the DataFrames, compare the concepts present in the API response against the union of the
three ordering lists, and render any unmapped names in an `st.warning`: *"Present in the API
but not displayed: operating_lease_liabilities."* A warning, not a caption — a figure the
company reported and the app silently dropped is exactly the class of failure §7.1 exists to
prevent.

Human-readable labels come from `/concepts` where available, with a hardcoded fallback map
so the app still renders if that endpoint changes.

### Formatting

| Unit | Format |
|---|---|
| `USD` | Millions, thousands separators, no decimals — `391,035` |
| `USD/shares` | Dollars, 2 decimals — `6.08` |
| `shares` | Millions, no decimals — `15,409` |
| Missing | `—` |

- Negative values in parentheses, accounting convention: `(1,234)`.
- Header on each statement states the unit: *"USD in millions, except per-share amounts."*
- Never mix units within a row. Unit comes from the API per value. If a concept returns an
  unexpected unit for any year, **raise** — do not render `—` and move on. A dash means "not
  reported"; using it for "reported but wrong" destroys the distinction §7.1 depends on.

### Provenance

Below each statement, an `st.expander("Sources")` containing a table of
`concept | fiscal year | source_tag | filing`, where `filing` is a link to SEC EDGAR.

URL construction — the accession appears twice, in two different forms:

```
https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{accession_with_dashes}-index.htm
```

`0000320193-24-000123` → path segment `000032019324000123`, filename prefix keeps the
dashes. Getting this wrong produces a 404, so unit-test the builder.

This is why the app exists rather than a spreadsheet: every figure traces to a filing.

---

## 7. States and errors

Every state below needs explicit handling. Silent failure or a raw traceback is the failure
mode to avoid.

| Condition | Display |
|---|---|
| No ticker entered | Neutral prompt: "Enter a ticker to begin." |
| Loading, cached | `st.spinner("Loading…")` |
| Loading, cold | `st.spinner("Fetching from SEC EDGAR — first load for a new company takes a few seconds.")` |
| `404` | "Ticker not found. Check the symbol and try again." |
| `422` | "This company has no XBRL data available — likely a foreign filer or delisted before 2009." |
| `429` | "Too many requests just now. Wait a moment and try again." |
| `502` / `504` | "SEC EDGAR is unavailable right now. Try again shortly." |
| `401` / `403` | "API authentication failed." (Config problem — do not tell the viewer to retry.) |
| Timeout | "Request timed out. The company may be large — try again." |
| Any other error | Generic message + the status code. Never surface a stack trace. |

The API returns RFC 7807 `problem+json`. Parse `title`/`detail` when present, but always
fall back to the table above — never render a raw API error object to the viewer.

The cold-fetch spinner copy matters. A bare spinner for 30 seconds reads as broken; naming
the cause does not.

### 7.1 Fail loudly

Data accuracy outranks a smooth experience. Where they conflict, the app stops and says why.
Someone who sees an error investigates; someone who sees a plausible wrong number puts it in
a model.

**The distinction that carries the whole section.** Three situations look alike and must not
be treated alike:

| Situation | Meaning | Behaviour |
|---|---|---|
| Concept absent for a year | The company didn't report it | Render `—`. Normal, not an error. |
| Value present but malformed | Bug upstream or in transit | Raise. Error on page, section doesn't draw. |
| Value present but impossible | e.g. `revenue` with unit `shares` | Raise. Error on page, section doesn't draw. |

A software company with no `inventory` line is not a failure. **Never turn absence into an
error, and never turn an error into absence.** Both directions are bugs.

**Banned constructs.** Each of these converts a failure into a plausible number:

```python
data.get("value", 0)       # missing becomes zero
value or 0                 # None and 0.0 collapse together
df.fillna(0)               # every gap becomes zero
except Exception: pass     # everything becomes nothing
float(value or "nan")      # nan renders as "nan" or 0 downstream
```

None of these appear in the codebase. Configure `ruff` to flag bare `except`.

**Validate at the boundary, then trust.** Parse each API response into dataclasses on
receipt. If a required key is missing or a type is wrong, raise *there*, naming the ticker
and the offending field. Downstream code then assumes well-formed data and needs no
defensive `.get()` calls — scattered defensive access is precisely how silent failures
spread through a codebase.

**Format to strings before pandas sees anything.** Build DataFrames from pre-formatted
strings, not floats. pandas coerces gaps to `NaN`, renders them as `nan`, and lets any
accidental numeric operation produce a wrong figure silently. An all-string DataFrame can do
neither. The app performs no arithmetic, so nothing is given up.

**Loud means on the page, not in the log.** Nobody reads Community Cloud logs. Every failure
here renders via `st.error()` and prevents that section from drawing. Set
`client.showErrorDetails = true` in `.streamlit/config.toml` so uncaught exceptions surface
their traceback — this is a private tool and you are the audience.

**Health failures are a banner, not a badge.** If `/health` reports any failed validation,
render a red `st.error` above the statements listing each failure explicitly and already
expanded. Tables still render below so the data can be diagnosed, but the warning is
unmissable. This supersedes the amber-badge description in §5.

**Where loudness is impossible, make the failure impossible instead.** Two cases:

- *EDGAR URLs* cannot self-verify without a network call. So regex-validate the accession
  (`^\d{10}-\d{2}-\d{6}$`) and raise on mismatch, and pin the template with the §8 unit test.
- *Scale errors* — a figure off by 1000× — are invisible to this app by construction. It has
  no independent basis for judging magnitude. This is exactly what the upstream `/health`
  year-over-year bounds check exists to catch, which is why surfacing health failures
  loudly is load-bearing rather than decorative.

---

## 8. Config and secrets

```toml
# .streamlit/secrets.toml  — LOCAL ONLY, must be gitignored
API_BASE_URL = "https://api.example.com"
API_KEY = "..."
```

Read via `st.secrets["API_KEY"]`. On Community Cloud these are entered in the app settings
UI, not committed.

Ship a `.streamlit/secrets.toml.example` with placeholder values.

`.gitignore` must include `.streamlit/secrets.toml` **before the first commit.** A key
committed once is a key that has to be rotated on the API server.

`requirements.txt` at repo root with pinned versions — Community Cloud installs from it
verbatim. Keep it minimal: `streamlit`, `httpx`, `pandas`.

Test dependencies go in a separate `requirements-dev.txt` (`pytest`, `ruff`) — **not** in
`requirements.txt`, which would install them into the app container for no reason.

### Tests

There is no broad test suite here; the app is a thin viewer and the data logic lives
upstream. Two things do need covering, in `tests/`:

- **`test_edgar_url.py`** — the filing URL builder. The accession number appears twice in
  two different forms, and a wrong guess returns a 404 rather than an error, so this fails
  silently in production. Assert against a known-good case:
  `cik=320193, accession="0000320193-24-000123"` →
  `https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/0000320193-24-000123-index.htm`
  Include a leading-zero case, since CIKs are stored as integers but appear zero-padded in
  some contexts.
- **`test_formatting.py`** — the value formatter. Cover each unit from §6, negative values
  in parentheses, and `None` rendering as `—` rather than `0` or `nan`.

Both are pure functions with no network or Streamlit dependency. Keep them that way.

---

## 9. Deployment

1. Private GitHub repo. Streamlit requires the `repo` OAuth scope for private repos and
   creates a read-only deploy key; GitHub notifies repo admins when it does.
2. Deploy from the Community Cloud dashboard — repo, branch, entrypoint file.
3. Set app visibility to **private** and add viewer emails to the allowlist.
4. Enter secrets in app settings.
5. Confirm a fresh browser session prompts for login and a non-allowlisted address is denied.

Community Cloud initializes apps from the repo root regardless of where the entrypoint sits,
so keep `requirements.txt` and `.streamlit/` at the root.

---

## 10. Build order

1. **Skeleton** — repo, `requirements.txt`, `.gitignore` with secrets excluded, ticker input
   rendering. Check: runs locally, secrets load.
2. **API client** — `httpx` with `X-API-Key`, 90s timeout, cached wrappers, ticker
   normalization. Check: returns data for a known ticker; second call makes no HTTP request.
3. **Error handling** — every row of §7, driven by a fake client. Check: each state renders
   its message, no tracebacks.
4. **One statement** — income statement DataFrame, formatting, missing-value dashes. Check:
   Apple FY2023 revenue and net income match the 10-K.
5. **Three statements** — balance sheet and cash flow, shared rendering function.
6. **Coverage and health** — banner and badge, failure expander.
7. **Provenance** — sources expanders, EDGAR URL builder with a unit test.
8. **Deploy** — private app, allowlist, secrets, access verification.

---

## 11. Out of scope

Do not build, and do not suggest building:

- Ticker search, autocomplete, or company browser. Exact ticker entry only.
- CSV/Excel export.
- DCF, WACC, ratios, growth rates, or any derived calculation.
- Multi-company comparison.
- Charts or sparklines. *(Obvious phase 2. Not now.)*
- Quarterly data.
- Any market data — prices, betas, yields, spreads.
- Local persistence, database, or user accounts beyond the Community Cloud allowlist.
- Any change to the upstream API.

---

## 12. Standing constraints

- Type hints throughout.
- `ruff` for lint and format.
- Presentation logic — row order, labels, formatting — in one module, not scattered.
- No secret in the repo, ever.
- Every network call has an explicit timeout.
- The app is a viewer. Numbers pass through unmodified from the API except for unit scaling
  and display formatting. **No derived values, no interpolation, no filling gaps.** If a
  figure looks wrong, the bug belongs upstream and gets fixed there.
