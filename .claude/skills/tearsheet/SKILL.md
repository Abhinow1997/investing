---
name: tearsheet
description: Quick one-page company overview and snapshot
argument-hint: TICKER
---

Generate a concise company tearsheet for the company specified by the user: $ARGUMENTS

This should be a quick, one-page overview — the kind of snapshot an analyst pulls up before a meeting.

**Before starting, read `../data-access.md` for data access methods and `../design-system.md` for formatting conventions.**

To generate this tearsheet, run:
```bash
python recipes/tearsheet.py $ARGUMENTS
```

If you need to extend or customise the output beyond what the script produces, follow the manual steps below using `recipes/free_client.py` directly.

---

## 1. Company Lookup

```python
from recipes.free_client import discover_companies

company = discover_companies("TICKER")
# Use: company["name"], company["sector"], company["industry"],
#      company["exchange"], company["description"], company["website"]
```

Note the ticker, full company name, sector, and exchange.

---

## 2. Key Financials

Pull the last 4 quarters PLUS the year-ago quarter for each (8 quarters total) to enable YoY for every recent period:

```python
from recipes.free_client import get_company_fundamentals

# Quarterly for recent trend
data_q = get_company_fundamentals("TICKER", period="quarterly")

# Annual for full-year context
data_a = get_company_fundamentals("TICKER", period="annual")
```

Extract from `data_q["income_statement"]`, `data_q["balance_sheet"]`, `data_q["cash_flow"]`:

- Revenue
- Gross Profit
- Operating Income
- EBITDA — if not in `data_q["income_statement"]["ebitda"]`, compute as Operating Income + D&A and label **"EBITDA (calc.)"**
- Net Income
- Diluted EPS — use `data_q["market_data"]["eps_ttm"]` as a proxy if not in income statement
- Operating Cash Flow
- CapEx (from `cash_flow["capex"]` — note: yFinance returns this as negative)
- Free Cash Flow — use `cash_flow["free_cash_flow"]`; if absent, compute as Operating Cash Flow − |CapEx| and label **"FCF (calc.)"**

For any derived/computed metric, mark it with **(calc.)** so the reader knows it is not directly sourced.

**Data shape reminder** — all series are `{date_string: integer_value}` dicts. Sort keys descending to get most-recent-first:
```python
revenue = data_q["income_statement"]["revenue"]
dates = sorted(revenue.keys(), reverse=True)   # most recent first
last_4 = dates[:4]                              # latest 4 quarters
```

---

## 3. Key Operating KPIs

This section is strictly for **business-driver metrics** — the operational numbers that move revenue and earnings. Do NOT include financial statement items (D&A, share count, buybacks, dividends) here — those belong in the financials or capital return sections.

Think about what drives valuation for this specific business model:

- **SaaS / cloud**: ARR, net revenue retention, RPO/cRPO, customers above $100K, cloud gross margin
- **Consumer tech**: DAU/MAU, ARPU, engagement metrics, installed base, paid subscribers
- **E-commerce / marketplace**: GMV, take rate, active buyers/sellers, order frequency
- **Retail**: same-store sales, store count, average ticket, transactions
- **Telecom / media**: subscribers, churn, ARPU, content spend
- **Hardware**: units shipped, ASP, attach rate, installed base, products vs services gross margin split
- **Financial services**: AUM, NIM, loan growth, credit quality metrics
- **Pharma / biotech**: pipeline stage, patient starts, scripts, market share
- **Industrials / energy**: backlog, book-to-bill, utilisation, production volumes

Search SEC filings for these KPIs using `get_recent_filings()` and the EDGAR full-text search:
```
https://efts.sec.gov/LATEST/search-index?q="YOUR KEYWORD"&forms=10-K,10-Q
```
Search broadly — companies often disclose more KPIs than expected. For example, for Apple: installed base of active devices, products gross margin vs services gross margin, paid subscriptions.

**If the company discloses few operational KPIs**, acknowledge the disclosure gap explicitly rather than padding the section with financial metrics. A note like "Apple does not disclose unit volumes or ASPs; segment revenue is the finest granularity available" is more useful than fake KPIs.

---

## 3b. Capital Return

Pull share count, share repurchases, and dividends paid for the same periods as financials. Keep this as a separate section — it shows how the company returns cash to shareholders.

Sources:
- Share repurchases → `data_q["cash_flow"]` (look for buyback-related keys)
- Dividends paid → `data_q["cash_flow"]`
- Shares outstanding → `data_q["market_data"]["market_cap"]` ÷ `data_q["market_data"]["price"]` as a proxy

---

## 4. Compute Key Ratios

Show trend over the last 4 quarters with YoY change **for each quarter**:

```python
# Example: Gross Margin %
gross_profit = data_q["income_statement"]["gross_profit"]
revenue      = data_q["income_statement"]["revenue"]

for date in sorted(revenue.keys(), reverse=True)[:4]:
    margin = gross_profit.get(date, 0) / revenue[date] * 100
```

Ratios to compute:
- Gross Margin %
- Operating Margin %
- EBITDA Margin %
- Net Margin %
- Revenue Growth YoY %
- EPS Growth YoY %

If the company has strong seasonality (retail Q4, back-to-school, etc.), add a brief note so YoY comparisons are read in context.

---

## 5. Recent Developments

Fetch recent SEC filings and scan for qualitative context:

```python
from recipes.free_client import get_recent_filings

filings_10q = get_recent_filings("TICKER", "10-Q", limit=2)
filings_8k  = get_recent_filings("TICKER", "8-K",  limit=3)
# Each filing has a direct SEC URL: filing["url"]
```

Use EDGAR full-text search for specific themes:
```
https://efts.sec.gov/LATEST/search-index?q="outlook"&forms=10-Q
https://efts.sec.gov/LATEST/search-index?q="guidance"&forms=10-Q
https://efts.sec.gov/LATEST/search-index?q="AI"&forms=10-Q
```

Extract:
- Business description / what the company does (2–3 sentences)
- Key recent developments or announcements
- Management's top priorities or strategic focus areas
- Any notable management quotes (cite the filing URL)

Keep this brief — 3–5 bullet points max.

---

## 6. Five Key Tensions

Identify the 5 most critical bull/bear debates for this stock. Each tension is a single line framing both sides. Alternate bullish-leaning and bearish-leaning. Every tension must reference a specific data point from the analysis above.

Format:
```
1. "[Bullish factor] vs [Bearish factor]" — cite the specific metric
2. "[Bearish factor] vs [Bullish factor]" — cite the specific metric
...
```

This goes at the top of the report, right after the Company Overview — it gives the reader the bull/bear framing before diving into data.

---

## 7. News Snapshot

Run 2 web search queries:
1. `"{TICKER} {company_name} news {current_year}"` — recent headlines
2. `"{TICKER} catalysts risks {current_year}"` — forward-looking events

Distill into **3–5 key events** from the last 6 months, reverse chronological:
- Date | One-line headline | Sentiment tag: `Positive / Negative / Mixed / Upcoming`

Keep it tight — this is a tearsheet, not a research note.

---

## 8. What to Watch

Build a **Quantitative Monitors** list — 5 metrics with explicit thresholds:

Format:
```
Metric: current value → bull threshold / bear threshold
```
Example:
```
Gross Margin: 45.2% → above 46% confirms pricing power / below 43% signals cost pressure
```

Choose the 5 metrics that matter most for this company's thesis based on the data pulled above. These should be actionable — an analyst checks these next quarter to know whether the thesis is intact.

---

## 9. Save Report

Save to `reports/{TICKER}_tearsheet.html` using the HTML report template from `../design-system.md`.
Write the full analysis as styled HTML with the design system CSS inlined.

**Report structure:**

```html
<h1>{Company Name} ({TICKER}) — Tearsheet</h1>
<p>Generated: {date} | Data: yFinance / SEC EDGAR</p>

<h2>Company Overview</h2>
{2–3 sentence description from SEC filings or yFinance}

<h2>Five Key Tensions</h2>
{numbered list of 5 bull/bear debates with data citations}

<h2>Key Financials (Last 4 Quarters)</h2>
<table>
  <tr><th>Metric</th><th>Q(oldest)</th><th>Q</th><th>Q</th><th>Q(latest)</th></tr>
  {rows — derived metrics marked (calc.)}
</table>

<h2>Segment / Geographic Breakdown</h2>
{segment revenue table or geographic revenue table, whichever is more relevant}

<h2>Key Operating KPIs</h2>
<table>
  {ONLY business-driver metrics — if few KPIs disclosed, note the gap}
</table>

<h2>Capital Return</h2>
<table>
  {share count, buybacks, dividends}
</table>

<h2>Margins & Growth</h2>
<table>
  <tr><th>Metric</th><th>Q(oldest)</th><th>Q</th><th>Q</th><th>Q(latest)</th></tr>
  <tr><td>Gross Margin %</td>...</tr>
  <tr><td>Operating Margin %</td>...</tr>
  <tr><td>EBITDA Margin %</td>...</tr>
  <tr><td>Net Margin %</td>...</tr>
  <tr><td>Rev Growth YoY</td>...</tr>
  <tr><td>EPS Growth YoY</td>...</tr>
  {note on seasonality if applicable}
</table>

<h2>Recent Developments</h2>
<ul>
  {bullet points — cite SEC filing URLs inline}
</ul>

<h2>News Snapshot</h2>
{3–5 recent events: date | headline | sentiment tag}

<h2>What to Watch</h2>
{5 quantitative monitors with current value and bull/bear thresholds}
```

**Citation format for financial figures:**
```html
$391.0B <span class="source">(SEC EDGAR / yFinance, FY2024)</span>
```

**Citation format for SEC filing links:**
```html
<a href="{filing['url']}" target="_blank">AAPL 10-Q — Aug 2024</a>
```

The `url` field from `get_recent_filings()` provides the direct `sec.gov` link automatically.

---

Tell the user where the HTML report was saved.

Give a 2–3 sentence summary of the company's current state, including an honest assessment: What is the single biggest risk or concern? Does the current valuation seem warranted given the growth trajectory? What would make you cautious about owning this stock?