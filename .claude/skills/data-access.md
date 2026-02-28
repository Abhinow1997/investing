# Data Access Reference (Free Stack)

All skills that need financial data should follow this reference.
This project runs in **free-stack mode** — no Daloopa API key or MCP server required.
Read `design-system.md` for formatting, analytical density, and styling conventions.

---

## Section 1: Free Client — Primary Data Source

All financial data comes from `recipes/free_client.py`, which uses **yFinance + SEC EDGAR**.
This replaces all Daloopa MCP tools and recipe scripts.

### Import Pattern (use in every skill)
```python
from recipes.free_client import (
    discover_companies,          # company info, sector, description
    discover_company_series,     # list available metrics
    get_company_fundamentals,    # income statement, balance sheet, cash flow, valuation
    get_recent_filings,          # latest SEC filings (10-K, 10-Q, 8-K)
)
```

### Tool Reference

| Daloopa (Old) | Free Stack (New) | Data Source |
|---|---|---|
| `discover_companies(keywords=["TICKER"])` | `discover_companies("TICKER")` | yFinance + SEC EDGAR |
| `discover_company_series(company_id, ...)` | `discover_company_series("TICKER")` | yFinance |
| `get_company_fundamentals(company_id, ...)` | `get_company_fundamentals("TICKER", period="annual")` | yFinance + SEC EDGAR XBRL |
| `search_documents(keywords, company_ids)` | `get_recent_filings("TICKER", "10-K")` | SEC EDGAR |

### Usage Examples

```python
# 1. Company info
company = discover_companies("AAPL")
# Returns: name, sector, industry, exchange, market_cap, description, website

# 2. Available metrics
series = discover_company_series("AAPL")
# Returns: income_statement, balance_sheet, cash_flow, valuation_metrics

# 3. Financial data
data = get_company_fundamentals("AAPL", period="annual")
# Returns:
#   data["income_statement"]  → revenue, gross_profit, operating_income, net_income, ebitda
#   data["balance_sheet"]     → total_assets, total_liabilities, total_equity, cash, total_debt
#   data["cash_flow"]         → operating_cash_flow, capex, free_cash_flow
#   data["market_data"]       → price, market_cap, pe_ratio, ev_ebitda, ps_ratio, beta, ...

# Quarterly data (for earnings analysis)
data_q = get_company_fundamentals("AAPL", period="quarterly")

# 4. SEC filings
filings = get_recent_filings("AAPL", "10-K", limit=3)
filings_q = get_recent_filings("AAPL", "10-Q", limit=4)
# Returns: ticker, cik, form, date, accession, url
```

### Data Shape — financials are returned as `{date: value}` dicts
```python
data["income_statement"]["revenue"]
# → {"2024-09-28": 391035000000, "2023-09-30": 383285000000, ...}

# Helper pattern to get latest value:
dates = sorted(data["income_statement"]["revenue"].keys(), reverse=True)
latest_revenue = data["income_statement"]["revenue"][dates[0]]
```

### Decision Tree — what to do if data is missing

```
free_client returns None or empty?
    → Try period="quarterly" instead of "annual"
    → Try discover_company_series() to check what's available
    → Fall back to infra/market_data.py for market data (see Section 2)
    → Note "data not available" in output, do not guess
```

---

## Section 2: Market Data

Market data (price, multiples, historical prices) is available directly from
`get_company_fundamentals()` via the `market_data` key. No separate script needed for basic use.

For richer market data or historical OHLCV, use the infra fallback scripts:

| Data Need | Source |
|---|---|
| Current price, market cap, beta | `data["market_data"]` from `get_company_fundamentals()` |
| Trading multiples (P/E, EV/EBITDA, P/S, P/B) | `data["market_data"]` from `get_company_fundamentals()` |
| Historical OHLCV prices | `python infra/market_data.py history TICKER --period 2y` |
| Peer multiples (side-by-side) | Loop `get_company_fundamentals()` across peer tickers |
| Risk-free rate (for WACC/DCF) | `python infra/market_data.py risk-free-rate` (uses FRED if key set, else 4.5% default) |

**Market data key reference** (from `get_company_fundamentals()`):
```python
mkt = data["market_data"]
mkt["price"]          # current stock price
mkt["market_cap"]     # market capitalization
mkt["pe_ratio"]       # trailing P/E
mkt["forward_pe"]     # forward P/E
mkt["ev_ebitda"]      # EV/EBITDA
mkt["ev_revenue"]     # EV/Revenue
mkt["ps_ratio"]       # Price/Sales
mkt["pb_ratio"]       # Price/Book
mkt["beta"]           # market beta
mkt["dividend_yield"] # dividend yield (decimal, e.g. 0.005 = 0.5%)
mkt["52w_high"]       # 52-week high
mkt["52w_low"]        # 52-week low
mkt["eps_ttm"]        # trailing EPS
mkt["eps_forward"]    # forward EPS
```

---

## Section 3: Macro Data (FRED — Optional)

For DCF/WACC calculations requiring the risk-free rate or inflation data.

**Setup:** Add `FRED_API_KEY` to your `.env` file.
Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html

When `FRED_API_KEY` is set, `get_company_fundamentals()` automatically appends a `macro` key:
```python
data["macro"]["risk_free_rate_10y"]   # 10Y Treasury yield
data["macro"]["federal_funds_rate"]   # Fed Funds Rate
data["macro"]["cpi_inflation"]        # CPI index level
```

If `FRED_API_KEY` is not set, use these defaults and note the limitation:
- Risk-free rate: **4.5%**
- Inflation: **2.5%**

---

## Section 4: SEC Filings & Document Search

For qualitative analysis (guidance language, risk factors, MD&A):

```python
# Get recent filings with direct SEC URLs
filings = get_recent_filings("AAPL", "10-K", limit=3)
# Each filing: {"ticker", "cik", "form", "date", "accession", "url"}

# Supported form types
get_recent_filings("AAPL", "10-K")    # Annual reports
get_recent_filings("AAPL", "10-Q")    # Quarterly reports
get_recent_filings("AAPL", "8-K")     # Current reports (earnings releases)
get_recent_filings("AAPL", "DEF 14A") # Proxy statements
```

For full-text keyword search within filings, use the EDGAR full-text search UI:
```
https://efts.sec.gov/LATEST/search-index?q="YOUR KEYWORD"&forms=10-K,10-Q
```

---

## Section 5: Citation Requirements

Since data comes from yFinance and SEC EDGAR (not Daloopa), citation format has changed.

**For financial figures:**
```
$75.2B (Source: yFinance / SEC EDGAR)
```

**For SEC filing references:**
```
[AAPL 10-K (2024-11-01)](https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/)
```
The `url` field from `get_recent_filings()` gives you this link directly.

**Rules:**
- Always note data source (yFinance or SEC EDGAR) for key figures
- Computed values (margins, growth rates) — note the underlying inputs used
- If data is unavailable, write "N/A" — never estimate or fabricate figures
- No Daloopa citation links (`daloopa.com/src/...`) — remove these from all outputs

---

## Section 6: Infrastructure Tools

Same as original — these scripts are unchanged and work with the free stack.

### Skill Commands → Recipe Scripts

| Slash Command | Script to Run |
|---|---|
| `/tearsheet TICKER` | `python recipes/tearsheet.py TICKER` |
| `/comps TICKER` | `python recipes/comps.py TICKER` *(coming soon)* |
| `/dcf TICKER` | `python recipes/dcf.py TICKER` *(coming soon)* |
| `/earnings TICKER` | `python recipes/earnings.py TICKER` *(coming soon)* |

### Charts
```bash
python infra/chart_generator.py {chart_type} --data '{json}' --output path.png
```
Available: `time-series`, `waterfall`, `football-field`, `pie`, `scenario-bar`, `dcf-sensitivity`

### Projections
```bash
python infra/projection_engine.py --context input.json --output projections.json
```

### HTML Report Output
Building block skills generate styled HTML saved to `reports/{TICKER}_{skill}.html`.

### Word / Excel / PDF Rendering
```bash
python infra/docx_renderer.py --template templates/research_note.docx --context context.json --output output.docx
python infra/excel_builder.py --context context.json --output output.xlsx
python infra/comp_builder.py --context context.json --output output.xlsx
python infra/pdf_renderer.py --context context.json --output output.pdf
```

---

## Section 7: Troubleshooting

| Problem | Fix |
|---|---|
| `ValueError: cannot convert NaN to int` | Use `_safe_int()` helper from `free_client.py` |
| `404 Error on SEC EDGAR` | Check `SEC_USER_AGENT` is set in `.env` |
| `yFinance returns empty data` | Ticker may be delisted — try alternate ticker format |
| `FRED data missing` | Set `FRED_API_KEY` in `.env` or use 4.5% default |
| `get_recent_filings returns []` | CIK lookup failed — check ticker spelling |
| `KeyError on market_data fields` | Some fields are None for non-US stocks — use `.get()` |