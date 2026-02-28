---
name: build-model
description: Build a multi-tab Excel financial model
argument-hint: TICKER
---

Build a comprehensive Excel financial model (.xlsx) for the company specified by the user: $ARGUMENTS

**Before starting, read `../data-access.md` for data access methods and `../design-system.md` for formatting conventions.**

---

## Quick Run

```bash
# Basic — 8 quarters projected, no peers
venv\Scripts\python.exe recipes\build_model.py AAPL

# With peers and custom projection horizon
venv\Scripts\python.exe recipes\build_model.py AAPL --peers MSFT GOOG AMZN META --quarters 12
```

Output:
- `reports/{TICKER}_model.xlsx` — the Excel model
- `reports/.tmp/{TICKER}_model_context.json` — full context (debug / reuse)

If you need to customise or extend beyond what the script produces, follow the manual phases below.

---

## Phase 1 — Company Setup

```python
from recipes.free_client import discover_companies, get_company_fundamentals

company = discover_companies("TICKER")
# company["name"], company["sector"], company["industry"], company["exchange"]

data_q = get_company_fundamentals("TICKER", period="quarterly")
mkt = data_q["market_data"]
# price, market_cap, shares_outstanding, beta, pe_ratio, ev_ebitda, ...
```

---

## Phase 2 — Historical Data Pull

Use `build_model_context()` — this is the single adapter that handles all format
conversions and produces context compatible with both `projection_engine.py` and
`excel_builder.py`:

```python
from recipes.free_client import build_model_context

ctx = build_model_context("TICKER", n_projection_quarters=8)
```

**What `build_model_context()` returns:**

| Key | Contents | Format |
|---|---|---|
| `ctx["company"]` | name, ticker, exchange, currency | dict |
| `ctx["market_data"]` | price, market_cap, beta, multiples | dict |
| `ctx["periods"]` | quarter labels oldest-first | `["2022Q1", ..., "2024Q4"]` |
| `ctx["income_statement"]` | Revenue, Gross Profit, COGS, R&D, SG&A, Op Income, Net Income, EBITDA, D&A, EPS | `{"Revenue": {"2024Q3": 94930000000}}` |
| `ctx["balance_sheet"]` | Cash, Investments, Total Assets/Liabilities/Equity, Total Debt | same |
| `ctx["cash_flow"]` | OCF, CapEx, FCF, D&A, Buybacks, Dividends | same |
| `ctx["projection_input"]` | historical as lists, ready for `projection_engine.py` | dict |
| `ctx["dcf_inputs"]` | WACC, terminal growth, risk-free rate, beta | dict |

**Period format:** All keys use `"YYYY QN"` quarter labels (e.g. `"2024Q3"`),
converted automatically from yFinance ISO dates.

**Target: 8-16 quarters of historical data** — yFinance typically provides 4 annual
or 4 quarterly periods. For more history, note the limitation in the model.

---

## Phase 3 — Peer Multiples

```bash
python infra/market_data.py peers MSFT GOOG AMZN META NVDA
```

Output is a JSON list of peer multiples. Feed into the `comps` section of the
excel_builder context:

```python
comps = {"peers": peer_multiples_list}
```

Each peer dict contains: `ticker, trailing_pe, ev_ebitda, price_to_sales, price_to_book`.

If no peers are specified, skip the Comps tab — do not guess peers.

---

## Phase 4 — Projections

Write `ctx["projection_input"]` to a temp JSON file and run:

```bash
python infra/projection_engine.py \
    --context reports/.tmp/{TICKER}_projection_input.json \
    --output  reports/.tmp/{TICKER}_projections.json
```

**What projection_engine.py needs** (already in `ctx["projection_input"]`):
```json
{
  "ticker": "AAPL",
  "projection_quarters": 8,
  "long_term_growth": 0.03,
  "decay_factor": 0.85,
  "historical": {
    "periods": ["2022Q4", "2023Q1", ...],
    "revenue": [list of values oldest-first],
    "cost_of_revenue": [...],
    "operating_expenses": [...],
    "net_income": [...],
    "capex": [...],
    "depreciation": [...],
    "shares_outstanding": [...]
  },
  "guidance": {}
}
```

**Convert projection output to excel_builder format:**
```python
proj = projection_output["projections"]
periods = proj["periods"]   # ["2025Q1", ..., "2026Q4"]

projections_dict = {
    "Revenue":          dict(zip(periods, proj["revenue"])),
    "Gross Profit":     dict(zip(periods, proj["gross_profit"])),
    "Operating Income": dict(zip(periods, proj["operating_income"])),
    "Net Income":       dict(zip(periods, proj["net_income"])),
    "Free Cash Flow":   dict(zip(periods, proj["fcf"])),
    "EPS":              dict(zip(periods, proj["eps"])),
}
```

---

## Phase 5 — DCF

Compute from projected FCF values:

```python
# Annualise quarterly FCFs
annual_fcf = [sum(proj_fcf[i:i+4]) for i in range(0, len(proj_fcf), 4)]

wacc = ctx["dcf_inputs"]["wacc"]
g    = ctx["dcf_inputs"]["terminal_growth"]

# PV of projected FCFs
pv_fcf = sum(fcf / (1+wacc)**(t+1) for t, fcf in enumerate(annual_fcf))

# Terminal value (Gordon Growth)
terminal_value = annual_fcf[-1] * (1+g) / (wacc - g)
pv_terminal    = terminal_value / (1+wacc)**len(annual_fcf)

enterprise_value  = pv_fcf + pv_terminal
implied_price     = enterprise_value / shares_outstanding
```

Build a 7×6 sensitivity matrix: WACC ± 150bps × terminal growth ± 50bps.

**WACC components** (from `ctx["dcf_inputs"]`):
- Risk-free rate: from FRED (`FRED_API_KEY` in `.env`) or default 4.5%
- Beta: from yFinance `market_data["beta"]`
- ERP: 5.5% (standard)
- Cost of debt: `interest_expense / total_debt` from historicals

---

## Phase 6 — Build Excel Model

Assemble the full context JSON and run `excel_builder.py`:

```python
excel_ctx = {
    "company":     ctx["company"],
    "market_data": ctx["market_data"],
    "periods":     ctx["periods"],              # historical quarter labels
    "projected_periods": projected_periods,     # projected quarter labels

    "income_statement": ctx["income_statement"],
    "balance_sheet":    ctx["balance_sheet"],
    "cash_flow":        ctx["cash_flow"],

    "projections":            projections_dict,   # from Phase 4
    "projection_assumptions": {
        "revenue_growth":    {period: value, ...},  # decimal
        "gross_margin":      {period: value, ...},
        "op_margin":         {period: value, ...},
        "capex_pct_revenue": {period: value, ...},
        "tax_rate":          0.16,
        "buyback_rate_qoq":  -0.002,
    },

    "dcf":   dcf_dict,     # from Phase 5
    "comps": {"peers": peer_multiples_list},  # from Phase 3 (optional)
}

# Save context
import json
ctx_path = "reports/.tmp/{TICKER}_model_context.json"
with open(ctx_path, "w") as f:
    json.dump(excel_ctx, f, indent=2)
```

```bash
python infra/excel_builder.py \
    --context reports/.tmp/{TICKER}_model_context.json \
    --output  reports/{TICKER}_model.xlsx
```

**Tabs built by excel_builder** (each tab only created if data is present):

| Tab | Trigger key | Contents |
|---|---|---|
| Summary | `company` or `market_data` | Company info + key stats |
| Income Statement | `income_statement` | IS with margin % rows + YoY growth |
| Balance Sheet | `balance_sheet` | BS with computed totals |
| Cash Flow | `cash_flow` | CF with FCF margin |
| Segments | `segments` | Revenue by segment (if available) |
| KPIs | `kpis` | Operating KPIs (if available) |
| Guidance | `guidance` | Guidance vs actuals (if available) |
| DCF | `dcf` | Assumptions + sensitivity table |
| Comps | `comps` | Peer multiples + median/mean |
| Projections | `projections` | Yellow input cells + projected financials |

---

## What's Not Available from Free Sources

These sections from the original skill require data not in yFinance or SEC EDGAR
in structured form. Note these gaps in the model:

| Section | Status | Workaround |
|---|---|---|
| **Segments** | ❌ Not structured | Fetch 10-K from SEC EDGAR and manually extract segment table |
| **KPIs** | ❌ Company-specific | Search EDGAR full-text: `https://efts.sec.gov/LATEST/search-index?q="YOUR KPI"&forms=10-K,10-Q` |
| **Guidance** | ❌ Not structured | Pull 8-K filings via `get_recent_filings("TICKER", "8-K")` and extract manually |
| **Consensus estimates** | ❌ Paid data | Note "N/A — consensus not available" |

---

## Citation Format

```html
<!-- Financial figures -->
$391.0B (Source: yFinance / SEC EDGAR, FY2024)

<!-- SEC filing links -->
<a href="{filing['url']}" target="_blank">AAPL 10-K — Nov 2024</a>
```

---

## Tell the User

After saving:
1. Path to `.xlsx` model and context JSON
2. Tabs built and what data populated each
3. Key model outputs: latest revenue, projected revenue growth, DCF implied price vs current price
4. Gaps: which tabs are empty and why (segments, KPIs, guidance)
5. Remind user: **yellow cells in the Projections tab are editable inputs**
