"""
capital_allocation.py — Free replacement for Daloopa's /capital-allocation command
====================================================================================
Generates a capital allocation deep-dive HTML report using yFinance + SEC EDGAR.

Usage:
    python recipes/capital_allocation.py AAPL
    python recipes/capital_allocation.py MSFT

Output:
    reports/<TICKER>_capital_allocation.html
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from free_client import discover_companies, get_company_fundamentals, get_recent_filings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _latest(series: dict):
    if not series: return None
    return series[sorted(series.keys(), reverse=True)[0]]

def _sorted_dates(series: dict, n: int = 8) -> list:
    return sorted(series.keys(), reverse=True)[:n]

def _fmt_large(val, currency="USD"):
    if val is None: return "—"
    try:
        val = int(val)
        sym = "$"
        sign = "-" if val < 0 else ""
        val = abs(val)
        if val >= 1e12: return f"{sign}{sym}{val/1e12:.2f}T"
        if val >= 1e9:  return f"{sign}{sym}{val/1e9:.2f}B"
        if val >= 1e6:  return f"{sign}{sym}{val/1e6:.2f}M"
        return f"{sign}{sym}{val:,}"
    except: return "—"

def _fmt_pct(val):
    if val is None: return "—"
    try: return f"{float(val)*100:.1f}%"
    except: return "—"

def _fmt_ratio(val, decimals=1):
    if val is None: return "—"
    try: return f"{float(val):.{decimals}f}x"
    except: return "—"

def _pct_of(num, denom):
    """num / denom as a % string."""
    try:
        n, d = int(num), int(denom)
        if d == 0: return "—"
        return f"{(n/d)*100:.1f}%"
    except: return "—"

def _yoy_growth(series: dict, date: str) -> str:
    """YoY growth for a specific date vs same date one year prior."""
    dates = sorted(series.keys(), reverse=True)
    try:
        idx = dates.index(date)
        # Find a date ~4 quarters earlier
        if idx + 4 < len(dates):
            prior = series[dates[idx + 4]]
            current = series[date]
            if prior and prior != 0:
                g = (current - prior) / abs(prior) * 100
                arrow = "▲" if g >= 0 else "▼"
                return f"{arrow}{abs(g):.1f}%"
    except: pass
    return "—"

# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------

def build_data(ticker: str) -> dict:
    print(f"  Fetching company info...")
    company = discover_companies(ticker)

    print(f"  Fetching quarterly data (8 quarters)...")
    data_q = get_company_fundamentals(ticker, period="quarterly")

    print(f"  Fetching annual data...")
    data_a = get_company_fundamentals(ticker, period="annual")

    print(f"  Fetching SEC filings...")
    filings_10k = get_recent_filings(ticker, "10-K", limit=2)
    filings_10q = get_recent_filings(ticker, "10-Q", limit=4)

    mkt = data_q.get("market_data", {})
    inc = data_q.get("income_statement", {})
    cf  = data_q.get("cash_flow", {})
    bs  = data_q.get("balance_sheet", {})

    # Get 8 quarters from revenue (most complete series)
    revenue_series = inc.get("revenue", {})
    dates = _sorted_dates(revenue_series, 8)

    # --- FCF Yield (annualised trailing 4Q) ---
    fcf_series = cf.get("free_cash_flow", {})
    last4_dates = dates[:4]
    trailing_fcf = sum(fcf_series.get(d, 0) or 0 for d in last4_dates)
    mkt_cap = mkt.get("market_cap")
    fcf_yield = (trailing_fcf / mkt_cap) if mkt_cap and trailing_fcf else None

    # --- Shareholder yield (trailing 4Q) ---
    tsr_series = cf.get("total_shareholder_return", {})
    trailing_tsr = sum(tsr_series.get(d, 0) or 0 for d in last4_dates)
    shareholder_yield = (trailing_tsr / mkt_cap) if mkt_cap and trailing_tsr else None

    # --- Net Debt ---
    cash_latest = _latest(bs.get("cash", {}))
    stinv_latest = _latest(bs.get("short_term_investments", {}))
    debt_latest  = _latest(bs.get("total_debt", {}))
    net_debt = (debt_latest or 0) - (cash_latest or 0) - (stinv_latest or 0) if debt_latest else None

    # --- Net Debt / EBITDA ---
    ebitda_series = inc.get("ebitda", {})
    # Try from annual for more complete EBITDA
    ebitda_a = data_a.get("income_statement", {}).get("ebitda", {})
    ebitda_latest = _latest(ebitda_a) or _latest(ebitda_series)
    nd_ebitda = (net_debt / ebitda_latest) if net_debt and ebitda_latest and ebitda_latest != 0 else None

    return {
        "ticker":     ticker.upper(),
        "name":       company.get("name", ticker.upper()),
        "sector":     company.get("sector", ""),
        "industry":   company.get("industry", ""),
        "as_of":      datetime.now().strftime("%B %d, %Y"),
        "dates":      dates,

        # Snapshot
        "price":            mkt.get("price"),
        "market_cap":       mkt_cap,
        "shares_outstanding": mkt.get("shares_outstanding"),
        "payout_ratio":     mkt.get("payout_ratio"),
        "dividend_rate":    mkt.get("dividend_rate"),
        "fcf_yield":        fcf_yield,
        "shareholder_yield":shareholder_yield,
        "net_debt":         net_debt,
        "nd_ebitda":        nd_ebitda,
        "trailing_fcf":     trailing_fcf,
        "trailing_tsr":     trailing_tsr,

        # Time series (quarterly)
        "revenue":          inc.get("revenue", {}),
        "operating_income": inc.get("operating_income", {}),
        "ebitda":           ebitda_series,
        "rd_expense":       inc.get("rd_expense", {}),
        "interest_expense": inc.get("interest_expense", {}),
        "ocf":              cf.get("operating_cash_flow", {}),
        "capex":            cf.get("capex", {}),
        "fcf":              fcf_series,
        "buybacks":         cf.get("share_repurchases", {}),
        "dividends":        cf.get("dividends_paid", {}),
        "tsr":              tsr_series,
        "cash":             bs.get("cash", {}),
        "total_debt":       bs.get("total_debt", {}),

        # SEC filings
        "filings_10k": filings_10k,
        "filings_10q": filings_10q,
    }

# ---------------------------------------------------------------------------
# Table builders
# ---------------------------------------------------------------------------

def _table_row(label, series, dates, fmt_fn=_fmt_large, cls=""):
    cells = "".join(f'<td>{fmt_fn(series.get(d))}</td>' for d in dates)
    return f'<tr class="{cls}"><td class="metric-label">{label}</td>{cells}</tr>'

def _pct_row(label, num_series, denom_series, dates):
    cells = "".join(
        f'<td>{_pct_of(num_series.get(d), denom_series.get(d))}</td>'
        for d in dates
    )
    return f'<tr><td class="metric-label">{label}</td>{cells}</tr>'

def _header_row(dates):
    cells = "".join(f'<th>{d[:7]}</th>' for d in dates)
    return f'<tr><th class="metric-label">Metric</th>{cells}</tr>'

# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def generate_html(d: dict) -> str:
    dates = d["dates"]
    quarter_cols = len(dates)

    # Snapshot table
    snapshot_rows = f"""
        <tr><td>Price</td><td>${d['price']:,.2f}</td></tr>
        <tr><td>Market Cap</td><td>{_fmt_large(d['market_cap'])}</td></tr>
        <tr><td>Trailing 4Q FCF</td><td>{_fmt_large(d['trailing_fcf'])}</td></tr>
        <tr><td>FCF Yield</td><td>{_fmt_pct(d['fcf_yield'])}</td></tr>
        <tr><td>Shareholder Yield (4Q)</td><td>{_fmt_pct(d['shareholder_yield'])}</td></tr>
        <tr><td>Net Debt</td><td>{_fmt_large(d['net_debt'])}</td></tr>
        <tr><td>Net Debt / EBITDA</td><td>{_fmt_ratio(d['nd_ebitda'])}</td></tr>
        <tr><td>Dividend Rate (Annual)</td><td>${d['dividend_rate']:.2f}</td></tr>
        <tr><td>Payout Ratio</td><td>{_fmt_pct(d['payout_ratio'])}</td></tr>
        <tr><td>Shares Outstanding</td><td>{_fmt_large(d['shares_outstanding'])}</td></tr>
    """ if d.get("price") else "<tr><td colspan='2'>Market data unavailable</td></tr>"

    # Cash Flow table
    cf_header = _header_row(dates)
    cf_body = (
        _table_row("Operating Cash Flow", d["ocf"], dates) +
        _table_row("Capital Expenditures", d["capex"], dates) +
        _table_row("Free Cash Flow", d["fcf"], dates, cls="highlight") +
        _pct_row("FCF Margin %", d["fcf"], d["revenue"], dates) +
        _pct_row("CapEx % Revenue", d["capex"], d["revenue"], dates) +
        _table_row("D&A", {}, dates)  # placeholder — add if available
    )

    # Shareholder returns table
    sr_header = _header_row(dates)
    sr_body = (
        _table_row("Share Repurchases", d["buybacks"], dates) +
        _table_row("Dividends Paid", d["dividends"], dates) +
        _table_row("Total Shareholder Return", d["tsr"], dates, cls="highlight") +
        _pct_row("TSR % FCF", d["tsr"], d["fcf"], dates)
    )

    # Leverage table
    lev_header = _header_row(dates)
    lev_body = (
        _table_row("Cash & Equivalents", d["cash"], dates) +
        _table_row("Total Debt", d["total_debt"], dates) +
        _table_row("EBITDA", d["ebitda"], dates)
    )

    # Reinvestment table
    ri_header = _header_row(dates)
    ri_body = (
        _table_row("R&D Expense", d["rd_expense"], dates) +
        _pct_row("R&D % Revenue", d["rd_expense"], d["revenue"], dates) +
        _table_row("CapEx", d["capex"], dates) +
        _pct_row("CapEx % Revenue", d["capex"], d["revenue"], dates) +
        _table_row("Revenue", d["revenue"], dates)
    )

    # SEC filing links
    def _filing_links(filings):
        if not filings: return "<p>No filings found</p>"
        links = "".join(
            f'<a href="{f["url"]}" target="_blank" class="filing-link">'
            f'{f["form"]} — {f["date"]}</a>'
            for f in filings
        )
        return links

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{d['ticker']} — Capital Allocation</title>
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --ink: #0f1117; --ink-light: #4a4f5e; --ink-faint: #8a8fa0;
      --paper: #f8f7f4; --paper-2: #eeecea; --accent: #1a4fd6;
      --green: #0d7a4e; --red: #c0392b; --gold: #c5a55a;
      --border: #d8d5d0;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'DM Sans', sans-serif; background: var(--paper); color: var(--ink); font-size: 13px; }}
    .page {{ max-width: 1200px; margin: 0 auto; padding: 32px 40px 56px; }}
    .header {{ border-bottom: 2px solid var(--ink); padding-bottom: 16px; margin-bottom: 28px; }}
    .title {{ font-family: 'DM Serif Display', serif; font-size: 32px; letter-spacing: -0.02em; }}
    .subtitle {{ font-family: 'DM Mono', monospace; font-size: 10px; color: var(--ink-faint); letter-spacing: 0.08em; text-transform: uppercase; margin-top: 4px; }}
    h2 {{ font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink-faint); margin: 28px 0 12px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }}
    .data-table {{ width: 100%; border-collapse: collapse; display: block; overflow-x: auto; }}
    .data-table th, .data-table td {{ padding: 7px 12px; text-align: right; white-space: nowrap; font-family: 'DM Mono', monospace; font-size: 11.5px; border-bottom: 1px solid var(--border); }}
    .data-table th {{ background: var(--paper-2); font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-light); }}
    .data-table td.metric-label {{ text-align: left; color: var(--ink-light); font-family: 'DM Sans', sans-serif; font-size: 12px; min-width: 220px; }}
    tr.highlight td {{ background: #fffbea; font-weight: 600; }}
    .snapshot-table {{ width: 340px; border-collapse: collapse; }}
    .snapshot-table td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); font-size: 13px; }}
    .snapshot-table td:first-child {{ color: var(--ink-light); width: 55%; }}
    .snapshot-table td:last-child {{ font-family: 'DM Mono', monospace; text-align: right; font-weight: 500; }}
    .filing-link {{ display: inline-block; margin: 4px 8px 4px 0; font-family: 'DM Mono', monospace; font-size: 10px; color: var(--accent); text-decoration: none; padding: 4px 10px; border: 1px solid var(--accent); border-radius: 4px; }}
    .filing-link:hover {{ background: var(--accent); color: white; }}
    .footer {{ margin-top: 40px; padding-top: 12px; border-top: 1px solid var(--border); font-family: 'DM Mono', monospace; font-size: 9.5px; color: var(--ink-faint); }}
    .verdict {{ background: white; border: 1px solid var(--border); border-left: 4px solid var(--gold); border-radius: 4px; padding: 16px 20px; margin: 16px 0; font-size: 13px; line-height: 1.65; color: var(--ink-light); }}
  </style>
</head>
<body>
<div class="page">

  <div class="header">
    <div class="title">{d['name']} ({d['ticker']}) — Capital Allocation</div>
    <div class="subtitle">{d['sector']} · {d['industry']} · As of {d['as_of']}</div>
  </div>

  <h2>Current Snapshot</h2>
  <table class="snapshot-table">
    <tbody>{snapshot_rows}</tbody>
  </table>

  <h2>Cash Flow & Free Cash Flow (Quarterly)</h2>
  <table class="data-table">
    <thead>{cf_header}</thead>
    <tbody>{cf_body}</tbody>
  </table>

  <h2>Share Repurchases & Dividends (Quarterly)</h2>
  <table class="data-table">
    <thead>{sr_header}</thead>
    <tbody>{sr_body}</tbody>
  </table>

  <h2>Leverage & Balance Sheet (Quarterly)</h2>
  <table class="data-table">
    <thead>{lev_header}</thead>
    <tbody>{lev_body}</tbody>
  </table>

  <h2>Reinvestment Assessment (R&D + CapEx)</h2>
  <table class="data-table">
    <thead>{ri_header}</thead>
    <tbody>{ri_body}</tbody>
  </table>
  <div class="verdict">
    ⚠️ <strong>Reinvestment verdict:</strong> Review R&D % Revenue and CapEx % Revenue trends above.
    If both are declining while TSR is at record highs, the company may be funding returns
    by underinvesting in long-term competitiveness.
  </div>

  <h2>SEC Filings — Capital Allocation Context</h2>
  <p style="font-size:11px; color: var(--ink-faint); margin-bottom:10px;">
    Search these filings for: "repurchase program", "dividend policy", "capital allocation", "authorization"
  </p>
  {_filing_links(d['filings_10k'] + d['filings_10q'])}

  <div class="footer">
    Data: yFinance / SEC EDGAR · Generated {d['as_of']} · Not investment advice.
  </div>

</div>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(ticker: str):
    print(f"\n📊 Building capital allocation report for {ticker.upper()}...")
    d = build_data(ticker)
    html = generate_html(d)

    out_dir  = Path("reports")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{ticker.upper()}_capital_allocation.html"
    out_path.write_text(html, encoding="utf-8")

    print(f"\n✅ Report saved → {out_path}")
    print(f"   Open in browser: file://{out_path.resolve()}")

    # Summary
    print(f"\n📋 Summary:")
    print(f"   Trailing FCF:        {_fmt_large(d['trailing_fcf'])}")
    print(f"   FCF Yield:           {_fmt_pct(d['fcf_yield'])}")
    print(f"   Shareholder Yield:   {_fmt_pct(d['shareholder_yield'])}")
    print(f"   Net Debt / EBITDA:   {_fmt_ratio(d['nd_ebitda'])}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python recipes/capital_allocation.py TICKER")
        sys.exit(1)
    run(sys.argv[1])
