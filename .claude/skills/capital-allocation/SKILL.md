---
name: capital-allocation
description: Deep dive into capital deployment, buybacks, dividends, and shareholder yield
argument-hint: TICKER
---

Perform a deep dive into capital allocation for the company specified by the user: $ARGUMENTS

**Before starting, read `../data-access.md` for data access methods and `../design-system.md` for formatting conventions.**

---

## Quick Run

```bash
venv\Scripts\python.exe recipes\capital_allocation.py AAPL
```

Output saved to: `reports/{TICKER}_capital_allocation.html`

If you need to extend or customise beyond what the script produces, follow the manual steps below.

---

## 1. Company Lookup

```python
from recipes.free_client import discover_companies

company = discover_companies("TICKER")
# Use: name, sector, industry, exchange
```

---

## 2. Market Data

```python
from recipes.free_client import get_company_fundamentals

data_q = get_company_fundamentals("TICKER", period="quarterly")
mkt = data_q["market_data"]

price             = mkt["price"]
market_cap        = mkt["market_cap"]
shares_outstanding = mkt["shares_outstanding"]
dividend_rate     = mkt["dividend_rate"]     # annual $/share
payout_ratio      = mkt["payout_ratio"]      # decimal
```

If `market_cap` is None, note that yield calculations cannot be computed and proceed with available data.

---

## 3. Capital Allocation Data

Pull **8 quarters** of quarterly data:

```python
data_q = get_company_fundamentals("TICKER", period="quarterly")

cf  = data_q["cash_flow"]
bs  = data_q["balance_sheet"]
inc = data_q["income_statement"]
```

### Cash Flow (from `cf`)
| Key | What it is |
|---|---|
| `cf["operating_cash_flow"]` | Operating Cash Flow |
| `cf["capex"]` | Capital Expenditures (negative value) |
| `cf["free_cash_flow"]` | FCF — auto-computed if not reported directly |
| `cf["share_repurchases"]` | Share buyback $ (negative = cash out) |
| `cf["dividends_paid"]` | Dividends paid (negative = cash out) |
| `cf["total_shareholder_return"]` | Abs(buybacks) + Abs(dividends) — auto-computed |
| `cf["da"]` | Depreciation & Amortization |

### Balance Sheet (from `bs`)
| Key | What it is |
|---|---|
| `bs["cash"]` | Cash & equivalents |
| `bs["short_term_investments"]` | Marketable securities / short-term investments |
| `bs["total_debt"]` | Total debt (short + long term) |
| `bs["total_equity"]` | Stockholders equity |

### Income Statement (from `inc`)
| Key | What it is |
|---|---|
| `inc["revenue"]` | Revenue |
| `inc["operating_income"]` | Operating Income |
| `inc["ebitda"]` | EBITDA (if reported) |
| `inc["rd_expense"]` | R&D Expense |
| `inc["interest_expense"]` | Interest Expense |

**Data shape reminder** — all series are `{date_string: integer_value}` dicts:
```python
dates = sorted(cf["free_cash_flow"].keys(), reverse=True)[:8]
```

---

## 4. Compute Capital Allocation Metrics

For each of the 8 quarters:

### Shareholder Returns
```python
# FCF Yield (annualised — multiply quarterly by 4)
fcf_yield = (fcf_q * 4) / market_cap

# Shareholder Yield
shareholder_yield = tsr_q * 4 / market_cap

# FCF Payout Ratio
fcf_payout = tsr_q / fcf_q
```

### FCF Deployment
- FCF Margin = FCF / Revenue
- CapEx % Revenue = |CapEx| / Revenue
- CapEx % OCF = |CapEx| / OCF

### Leverage
```python
# Net Debt
net_debt = total_debt - cash - short_term_investments

# Net Debt / EBITDA — use annual EBITDA for stability
net_debt_ebitda = net_debt / ebitda_annual

# Interest Coverage
interest_coverage = operating_income / abs(interest_expense)
```

### Share Count Dynamics
```python
# Implied shares from market cap / price
shares = market_cap / price

# QoQ / YoY change
qoq_change = (shares_now - shares_prior_q) / shares_prior_q
yoy_change = (shares_now - shares_prior_yr) / shares_prior_yr
```

---

## 5. Qualitative Research — SEC Filings

```python
from recipes.free_client import get_recent_filings

filings_10k = get_recent_filings("TICKER", "10-K", limit=2)
filings_10q = get_recent_filings("TICKER", "10-Q", limit=4)
```

Use EDGAR full-text search for capital allocation language:
```
https://efts.sec.gov/LATEST/search-index?q="repurchase program"&forms=10-K,10-Q
https://efts.sec.gov/LATEST/search-index?q="dividend policy"&forms=10-K,10-Q
https://efts.sec.gov/LATEST/search-index?q="capital allocation"&forms=10-K,10-Q
https://efts.sec.gov/LATEST/search-index?q="acquisition"&forms=10-K,10-Q
```

Extract:
- Board-authorized buyback programs (remaining authorization amount)
- Dividend policy (growth commitment, payout ratio targets)
- M&A philosophy (bolt-on vs transformational)
- Management's stated capital allocation priorities
- Any changes in capital allocation strategy
- Direct quotes — cite filing URL: `filing["url"]`

---

## 6. Historical Analysis & Value Judgment

Analyse the 8-quarter trend:

- Is buyback activity accelerating or decelerating?
- Is the company buying back more shares when price is lower (disciplined) or higher?
- Dividend growth rate and sustainability
- FCF payout ratio trend — if >100%, company is funding returns with debt or cash drawdowns — **flag this**
- Shift between CapEx, buybacks, dividends, and debt repayment over time

**Honestly assess whether capital allocation is creating or destroying value:**
- Buying back stock at all-time-high prices with deteriorating fundamentals → value destruction, call it
- Under-investing in CapEx or R&D to fund buybacks → flag risk to long-term competitiveness
- FCF payout ratio >100% → flag as unsustainable
- Compare implied buyback return (inverse of P/E at purchase price) to organic reinvestment alternatives

---

## 6.5. Reinvestment Assessment

Check whether the company is adequately reinvesting or funding returns at the expense of long-term growth.

Pull from `inc["rd_expense"]` and `cf["capex"]` across 8 quarters:
- R&D as % of Revenue trend — declining while buybacks rise is a red flag
- CapEx as % of Revenue — is infrastructure investment keeping pace with business needs?

Use EDGAR keyword search for growth KPIs relevant to the sector (subscribers, ARR, GMV, units, etc.):
```
https://efts.sec.gov/LATEST/search-index?q="active subscribers"&forms=10-K,10-Q
```

**Net verdict:** Is this company creating long-term value (reinvesting at high ROIC, buying back cheap, growing dividends sustainably) or extracting value (underinvesting to fund buybacks at premium valuations)?

---

## 7. Report Structure

Save to `reports/{TICKER}_capital_allocation.html` following `../design-system.md`.

```html
<h1>{Company Name} ({TICKER}) — Capital Allocation Analysis</h1>
<p>Generated: {date} | Data: yFinance / SEC EDGAR</p>

<h2>Current Snapshot</h2>
<table>
  <!-- Single-column snapshot: Market Cap, FCF, FCF Yield, Shareholder Yield, Net Debt/EBITDA -->
</table>

<h2>Cash Flow & FCF (8 Quarters)</h2>
<table>
  <!-- OCF, CapEx, FCF, FCF Margin %, CapEx % Revenue -->
</table>

<h2>Share Repurchases & Dividends (8 Quarters)</h2>
<table>
  <!-- Buyback $, Dividends $, Total Shareholder Return, TSR % FCF -->
</table>

<h2>Leverage & Balance Sheet (8 Quarters)</h2>
<table>
  <!-- Cash, Short-term Investments, Total Debt, Net Debt, Net Debt/EBITDA -->
</table>

<h2>Capital Allocation Framework</h2>
<!-- Management's stated priorities from SEC filings with direct links -->

<h2>Reinvestment Assessment</h2>
<table>
  <!-- R&D, R&D % Rev, CapEx, CapEx % Rev -->
</table>
<!-- Value creation vs extraction verdict -->

<h2>Buyback Discipline Analysis</h2>
<!-- Buyback timing vs price, share count trend, authorization remaining -->

<h2>M&A Activity</h2>
<!-- Acquisitions from filings, deal sizes, strategic rationale -->

<h2>Key Observations</h2>
<ul>
  <!-- 3-5 bullets on capital allocation quality, trends, implications -->
</ul>
```

**Citation format:**
```html
<!-- Financial figures -->
$23.5B <span class="source">(yFinance / SEC EDGAR, Q3 2024)</span>

<!-- Filing links -->
<a href="{filing['url']}" target="_blank">AAPL 10-Q — Jul 2024</a>
```

---

## 8. Tell the User

After saving:
1. Path to the HTML report
2. Key capital allocation headline: *"{TICKER} returned ${X}B to shareholders over the last year, a X.X% shareholder yield, with buybacks [accelerating/decelerating]"*
3. Single biggest risk or concern from the analysis
