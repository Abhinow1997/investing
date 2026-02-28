---
name: comps
description: Trading comparables — peer multiples and implied valuation
argument-hint: TICKER [PEER1 PEER2 ...]
---

Generate a trading comparables report for the company specified by the user: $ARGUMENTS

The first argument is the **subject ticker**. Any additional tickers are treated as the **peer set**.

**Before starting, read `../data-access.md` for data access methods and `../design-system.md` for formatting conventions.**

---

## Quick Run

```bash
# Auto-discover peers from built-in sector map
venv\Scripts\python.exe recipes/comps.py AAPL

# Provide your own peer set (recommended for precision)
venv\Scripts\python.exe recipes/comps.py AAPL MSFT GOOG AMZN META
```

Output saved to: `reports/{TICKER}_comps.html`

If you need to extend or customise beyond what the script produces, follow the manual steps below.

---

## 1. Parse Arguments

Split `$ARGUMENTS` on whitespace:
- First token → subject ticker
- Remaining tokens → peer tickers (optional)

If no peers provided, the script auto-discovers them using a built-in sector/industry peer map.
If the sector is not in the map, instruct the user to pass peers manually:
```
No peers found for sector 'X'. Pass them explicitly:
python recipes/comps.py TICKER PEER1 PEER2 ...
```

---

## 2. Fetch Subject Company Info

```python
from recipes.free_client import discover_companies, get_company_fundamentals

subject_info = discover_companies("TICKER")
# Use: name, sector, industry, exchange, description

subject_data = get_company_fundamentals("TICKER", period="annual")
# Use for implied valuation: revenue, ebitda, fcf, eps, shares outstanding
```

---

## 3. Peer Discovery (if no peers passed)

Use the built-in `SECTOR_PEERS` map in `recipes/comps.py`.
Resolution order:
1. Match on `industry` (more specific)
2. Fall back to `sector` (broader)
3. Cap at 6 peers for table readability

If the company's industry/sector is not in the map, tell the user and stop — do not guess peers.

---

## 4. Fetch All Peer Data

Loop `get_company_fundamentals()` across subject + all peers:

```python
for ticker in [subject] + peers:
    data = get_company_fundamentals(ticker, period="annual")
    mkt  = data["market_data"]
    inc  = data["income_statement"]
    cf   = data["cash_flow"]
```

Extract for each company:

**Valuation multiples** (from `market_data`):
- Price, Market Cap
- P/E Trailing, P/E Forward
- EV/EBITDA, EV/Revenue
- P/Sales, P/Book

**Financials** (from `income_statement` + `cash_flow`):
- Revenue (LTM) + YoY growth
- EBITDA (LTM)
- Free Cash Flow (LTM)
- Gross Margin %, Net Margin %

**Per share**:
- EPS (TTM), EPS (Forward)
- Beta, Dividend Yield

Use `_latest()` helper to get the most recent annual value from each `{date: value}` series:
```python
dates = sorted(series.keys(), reverse=True)
latest_val = series[dates[0]]
```

---

## 5. Implied Valuation (Football Field Lite)

Use **peer median multiples** applied to the subject's own financials to derive implied value ranges.

```python
import statistics

peer_ev_ebitda = [p["ev_ebitda_raw"] for p in peers if p["ev_ebitda_raw"]]
median_ev_ebitda = statistics.median(peer_ev_ebitda)
implied_mkt_cap = subject_ebitda * median_ev_ebitda
```

Run this for each available multiple:
- EV/Revenue → implied market cap
- EV/EBITDA  → implied market cap
- P/Sales    → implied market cap
- P/E        → implied price per share

Present as a simple table:

| Method | Peer Median Multiple | Implied Value |
|---|---|---|
| EV / Revenue | 8.2x | $2.4T market cap |
| EV / EBITDA  | 24.1x | $2.9T market cap |
| P / Sales    | 7.9x | $2.3T market cap |
| P / E        | 28.4x | $198 / share |

Note clearly: *"Peer median multiples applied to subject's own financials. For context only — not a price target."*

---

## 6. Generate HTML Report

Save to `reports/{TICKER}_comps.html` following `../design-system.md`.

**Report structure:**

```html
<h1>{Company Name} ({TICKER}) — Trading Comparables</h1>
<p>★ = Subject company · LTM = Last Twelve Months · As of {date}</p>
<p>Data: yFinance / SEC EDGAR</p>

<h2>Valuation & Financials</h2>
<table>
  <!-- Columns = companies (subject highlighted), Rows = metrics -->
  <!-- Subject column: yellow background + star prefix ★ -->
  <!-- Section dividers between valuation / financials / per-share blocks -->
  <!-- Revenue growth: green ▲ or red ▼ -->
</table>

<h2>Implied Valuation (Peer Median Multiples → {TICKER})</h2>
<table>
  <!-- Method | Peer Median Multiple | Implied Value -->
</table>
```

**Table conventions (from design-system.md):**
- Columns = companies (subject always first, highlighted)
- Rows = metrics (grouped: Valuation / Financials / Per Share)
- All numbers right-aligned, monospace font
- Missing data → "—" never blank or "N/A"
- Subject column: distinct background color so it stands out at a glance

---

## 7. Handle Missing Data Gracefully

If a peer fetch fails (delisted, OTC, API error):
- Skip that peer row with a warning
- Continue with remaining peers
- Note in report footer: "Data unavailable for: TICKER"

If no multiples available for a peer (e.g. negative earnings → no P/E):
- Show "—" in that cell
- Do not exclude the peer from the table

---

## 8. Citation Format

```html
<!-- Financial figures -->
$391.0B <span class="source">(yFinance / SEC EDGAR, FY2024)</span>

<!-- No filing links needed for comps — all data from yFinance market_data -->
```

---

## 9. Tell the User

After saving, output:
1. Path to the saved HTML file
2. A 2–3 sentence summary:
   - How does the subject trade vs peers on the key multiples?
   - Is it a premium or discount — and does that seem justified given relative growth and margins?
   - What is the single most interesting observation from this comp set?