# Data Access Reference

All skills that need financial data should follow this reference.
Read `design-system.md` for formatting, analytical density, and styling conventions.

---

## Section 1: Primary Data Source

All financial data comes from `recipes/free_client.py`, which wraps
**yFinance** (market data + financials) and **SEC EDGAR** (filings + XBRL).
No API keys required for core functionality.

### Import Pattern
```python
from recipes.free_client import (
    discover_companies,       # company info: name, sector, description, exchange
    discover_company_series,  # list all available metrics for a company
    get_company_fundamentals, # income statement, balance sheet, cash flow, valuation
    get_recent_filings,       # SEC filings: 10-K, 10-Q, 8-K, DEF 14A
)
```

### Function Reference

| Operation | Function | Data Source |
|---|---|---|
| Look up company by ticker | `discover_companies("TICKER")` | yFinance + SEC EDGAR |
| List available metrics | `discover_company_series("TICKER")` | yFinance |
| Pull financial statements | `get_company_fundamentals("TICKER", period="annual")` | yFinance + SEC EDGAR XBRL |
| Get SEC filings | `get_recent_filings("TICKER", "10-K", limit=3)` | SEC EDGAR |

### Usage Examples

```python
# 1. Company overview
company = discover_companies("AAPL")
# Returns: name, sector, industry, exchange, market_cap, description, website, country

# 2. Check what metrics are available
series = discover_company_series("AAPL")
# Returns: available_series (income_statement, balance_sheet, cash_flow, valuation_metrics)
#          data_available (booleans per section)
#          periods_available (annual: 4 years, quarterly: 4 quarters)

# 3. Annual financial data
data = get_company_fundamentals("AAPL", period="annual")
# data["income_statement"] → revenue, gross_profit, operating_income, net_income, ebitda
# data["balance_sheet"]    → total_assets, total_liabilities, total_equity, cash, total_debt
# data["cash_flow"]        → operating_cash_flow, capex, free_cash_flow
# data["market_data"]      → price, market_cap, pe_ratio, ev_ebitda, ps_ratio, beta, ...

# 4. Quarterly financial data (for earnings analysis)
data_q = get_company_fundamentals("AAPL", period="quarterly")

# 5. SEC filings with direct URLs
filings = get_recent_filings("AAPL", "10-K", limit=3)
# Each item: {"ticker", "cik", "form", "date", "accession", "url"}
```

### Data Shape

All financial series are returned as `{date_string: integer_value}` dicts:

```python
data["income_statement"]["revenue"]
# → {"2024-09-28": 391035000000, "2023-09-30": 383285000000, ...}

# Get the most recent value:
dates = sorted(data["income_statement"]["revenue"].keys(), reverse=True)
latest = data["income_statement"]["revenue"][dates[0]]

# Get YoY growth:
current = data["income_statement"]["revenue"][dates[0]]
prior   = data["income_statement"]["revenue"][dates[1]]
growth  = (current - prior) / abs(prior)
```

### What to do if data is missing

```
get_company_fundamentals() returns empty section?
    → Try period="quarterly" instead of "annual"
    → Call discover_company_series() to verify what is available
    → Fall back to infra/market_data.py for market-side data (see Section 2)
    → Write "N/A" in output — never estimate or fabricate figures
```

---

## Section 2: Market Data

Basic market data (price, multiples, beta) is included in `get_company_fundamentals()`
under the `market_data` key — no separate call needed.

For historical OHLCV or peer comparisons, use the infra scripts:

| Data Need | How to Get It |
|---|---|
| Price, market cap, beta | `data["market_data"]` from `get_company_fundamentals()` |
| Valuation multiples (P/E, EV/EBITDA, P/S, P/B) | `data["market_data"]` from `get_company_fundamentals()` |
| Historical OHLCV (1–5 years) | `python infra/market_data.py history TICKER --period 2y` |
| Peer multiples side-by-side | Loop `get_company_fundamentals()` across each peer ticker |
| Risk-free rate (DCF/WACC) | `python infra/market_data.py risk-free-rate` |

**Full `market_data` key reference:**
```python
mkt = data["market_data"]
mkt["price"]          # current stock price
mkt["market_cap"]     # market capitalization (integer)
mkt["pe_ratio"]       # trailing twelve-month P/E
mkt["forward_pe"]     # forward P/E
mkt["ev_ebitda"]      # EV / EBITDA
mkt["ev_revenue"]     # EV / Revenue
mkt["ps_ratio"]       # Price / Sales (TTM)
mkt["pb_ratio"]       # Price / Book
mkt["beta"]           # market beta
mkt["dividend_yield"] # decimal (e.g. 0.005 = 0.5%)
mkt["52w_high"]       # 52-week high
mkt["52w_low"]        # 52-week low
mkt["eps_ttm"]        # trailing EPS
mkt["eps_forward"]    # forward EPS estimate
```

---

## Section 3: Macro Data (Optional — for DCF/WACC)

Add `FRED_API_KEY` to `.env` to enable live macro data.
Free key available at: https://fred.stlouisfed.org/docs/api/api_key.html

When `FRED_API_KEY` is present, `get_company_fundamentals()` appends a `macro` key:
```python
data["macro"]["risk_free_rate_10y"]  # 10Y Treasury yield (%)
data["macro"]["federal_funds_rate"]  # Fed Funds Rate (%)
data["macro"]["cpi_inflation"]       # CPI index level
data["macro"]["sp500"]               # S&P 500 index level
```

If `FRED_API_KEY` is not set, use these defaults and note them in output:
- Risk-free rate: **4.5%**
- Inflation: **2.5%**

---

## Section 4: SEC Filings

For qualitative analysis — MD&A, risk factors, guidance language, footnotes:

```python
# Supported form types
get_recent_filings("AAPL", "10-K",    limit=3)  # Annual report
get_recent_filings("AAPL", "10-Q",    limit=4)  # Quarterly report
get_recent_filings("AAPL", "8-K",     limit=5)  # Earnings releases / current reports
get_recent_filings("AAPL", "DEF 14A", limit=1)  # Proxy statement

# Each result contains a direct SEC URL — use it for citation
filing["url"]  # → https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/
```

For keyword search across filings (guidance, risk factors, specific topics):
```
https://efts.sec.gov/LATEST/search-index?q="YOUR KEYWORD"&forms=10-K,10-Q
```

---

## Section 5: Citation Format

Every financial figure in output must be attributed to its source.

**For financial statement figures:**
```
$391.0B revenue (Source: SEC EDGAR / yFinance, FY2024)
```

**For SEC filing references — always link directly:**
```markdown
[AAPL 10-K — Nov 2024](https://www.sec.gov/Archives/edgar/data/320193/...)
```
The `url` from `get_recent_filings()` provides this link automatically.

**Rules:**
- Always state the source (yFinance or SEC EDGAR) and the period for key figures
- Computed values (margins, growth rates) — cite the underlying inputs used
- If a figure is unavailable, write **N/A** — never guess or interpolate
- All filing links must point to `sec.gov` — no third-party aggregators

---

## Section 6: Skill Commands → Recipe Scripts

When executing a slash command, run the corresponding recipe script directly.
All output is saved to the `reports/` directory.

| Slash Command | Script | Output |
|---|---|---|
| `/tearsheet TICKER` | `python recipes/tearsheet.py TICKER` | `reports/TICKER_tearsheet.html` |
| `/comps TICKER` | `python recipes/comps.py TICKER` | `reports/TICKER_comps.html` |
| `/dcf TICKER` | `python recipes/dcf.py TICKER` | `reports/TICKER_dcf.html` |
| `/earnings TICKER` | `python recipes/earnings.py TICKER` | `reports/TICKER_earnings.html` |
| `/capital-allocation TICKER` | `python recipes/capital_allocation.py TICKER` | `reports/TICKER_capital_allocation.html` |
| `/inflection TICKER` | `python recipes/inflection.py TICKER` | `reports/TICKER_inflection.html` |
| `/comp-sheet TICKER` | `python recipes/comp_sheet.py TICKER` | `reports/TICKER_comp_sheet.xlsx` |
| `/research-note TICKER` | `python recipes/research_note.py TICKER` | `reports/TICKER_research_note.docx` |
| `/build-model TICKER` | `python recipes/build_model.py TICKER` | `reports/TICKER_model.xlsx` |

---

## Section 7: Infrastructure Tools

These scripts are available for all skills to use:

### Charts
```bash
python infra/chart_generator.py {chart_type} --data '{json}' --output path.png
```
Available types: `time-series`, `waterfall`, `football-field`, `pie`, `scenario-bar`, `dcf-sensitivity`

### Projections
```bash
python infra/projection_engine.py --context input.json --output projections.json
```

### Word / Excel / PDF Rendering
```bash
python infra/docx_renderer.py --template templates/research_note.docx --context context.json --output output.docx
python infra/excel_builder.py  --context context.json --output output.xlsx
python infra/comp_builder.py   --context context.json --output output.xlsx
python infra/pdf_renderer.py   --context context.json --output output.pdf
python infra/deck_renderer.py  --context context.json --output output.pdf
```

### Context Diffs (for /update)
```bash
python infra/report_differ.py --old old.json --new new.json --output diff.json
```

---

## Section 8: Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `ValueError: cannot convert NaN to integer` | yFinance returns NaN for missing fields | Use `_safe_int()` from `free_client.py` |
| `HTTPError: 404 on SEC EDGAR` | Bad endpoint path | Check `SEC_USER_AGENT` is set in `.env` |
| `get_recent_filings` returns `[]` | CIK lookup failed | Verify ticker spelling; ETFs have no CIK |
| `market_data` fields are `None` | Non-US or OTC stock | Use `.get()` with a default; note N/A in output |
| `financials` DataFrame empty | Delisted or very small company | Note data unavailable; skip that section |
| FRED data not loading | Key not found in environment | Run `python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(os.getenv('FRED_API_KEY'))"` |