"""
tearsheet.py — Free replacement for Daloopa's /tearsheet command
=================================================================
Generates a professional one-page HTML company tearsheet using
free_client.py (yFinance + SEC EDGAR) instead of the Daloopa API.

Usage:
    python 
    L
    python recipes/tearsheet.py MSFT
    python recipes/tearsheet.py NVDA

Output:


    reports/<TICKER>_tearsheet.html

Changes from original Daloopa tearsheet skill:
    - Replaced DaloupaClient calls with free_client functions
    - discover_companies()       → company header info
    - get_company_fundamentals() → financials + valuation
    - get_recent_filings()       → latest SEC filing date
    - No API key needed (only optional FRED key for macro)
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

# Add recipes/ to path so we can import free_client
sys.path.insert(0, str(Path(__file__).parent))

from free_client import (
    discover_companies,
    get_company_fundamentals,
    get_recent_filings,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_large(val: int | None, currency: str = "USD") -> str:
    """Format large numbers as $1.23B / $456M / $12K."""
    if val is None:
        return "N/A"
    symbol = "$" if currency == "USD" else currency + " "
    abs_val = abs(val)
    if abs_val >= 1_000_000_000_000:
        return f"{symbol}{val/1_000_000_000_000:.2f}T"
    if abs_val >= 1_000_000_000:
        return f"{symbol}{val/1_000_000_000:.2f}B"
    if abs_val >= 1_000_000:
        return f"{symbol}{val/1_000_000:.2f}M"
    if abs_val >= 1_000:
        return f"{symbol}{val/1_000:.1f}K"
    return f"{symbol}{val:,}"


def _fmt_pct(val: float | None) -> str:
    """Format a ratio as percentage."""
    if val is None:
        return "N/A"
    return f"{val * 100:.1f}%"


def _fmt_ratio(val: float | None, decimals: int = 1) -> str:
    """Format a ratio."""
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}x"


def _fmt_price(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"${val:,.2f}"


def _latest(series: dict) -> int | None:
    """Get the most recent value from a {date: value} dict."""
    if not series:
        return None
    latest_key = sorted(series.keys(), reverse=True)[0]
    return series[latest_key]


def _margin(numerator: dict, denominator: dict) -> str:
    """Compute latest margin between two series."""
    n = _latest(numerator)
    d = _latest(denominator)
    if n is None or d is None or d == 0:
        return "N/A"
    return f"{(n / d) * 100:.1f}%"


def _yoy_growth(series: dict) -> str:
    """Compute YoY growth from a {date: value} dict."""
    if not series or len(series) < 2:
        return "N/A"
    dates = sorted(series.keys(), reverse=True)
    current = series[dates[0]]
    prior = series[dates[1]]
    if prior is None or prior == 0:
        return "N/A"
    growth = ((current - prior) / abs(prior)) * 100
    arrow = "▲" if growth >= 0 else "▼"
    return f"{arrow} {abs(growth):.1f}%"


def _sparkline_data(series: dict, key: str = None) -> list:
    """Return sorted list of values for a sparkline."""
    if not series:
        return []
    dates = sorted(series.keys())
    return [series[d] for d in dates if series[d] is not None]


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------

def build_tearsheet_data(ticker: str) -> dict:
    """Fetch and assemble all data needed for the tearsheet."""
    print(f"  Fetching company info for {ticker}...")
    company = discover_companies(ticker)

    print(f"  Fetching annual fundamentals...")
    fundamentals = get_company_fundamentals(ticker, period="annual")

    print(f"  Fetching latest SEC filings...")
    filings_10k = get_recent_filings(ticker, "10-K", limit=1)
    filings_10q = get_recent_filings(ticker, "10-Q", limit=1)

    # Extract sub-sections
    income = fundamentals.get("income_statement", {})
    balance = fundamentals.get("balance_sheet", {})
    cashflow = fundamentals.get("cash_flow", {})
    market = fundamentals.get("market_data", {})
    currency = fundamentals.get("currency", "USD")

    revenue = income.get("revenue", {})
    gross_profit = income.get("gross_profit", {})
    operating_income = income.get("operating_income", {})
    net_income = income.get("net_income", {})
    ebitda = income.get("ebitda", {})
    fcf = cashflow.get("free_cash_flow", {})
    total_debt = balance.get("total_debt", {})
    cash = balance.get("cash", {})

    # Net debt
    latest_debt = _latest(total_debt)
    latest_cash = _latest(cash)
    net_debt = (latest_debt or 0) - (latest_cash or 0) if latest_debt is not None else None

    return {
        "ticker": ticker.upper(),
        "name": company.get("name", ticker.upper()),
        "sector": company.get("sector", "N/A"),
        "industry": company.get("industry", "N/A"),
        "exchange": company.get("exchange", "N/A"),
        "country": company.get("country", "N/A"),
        "website": company.get("website", "#"),
        "description": company.get("description", ""),
        "currency": currency,
        "as_of": datetime.now().strftime("%B %d, %Y"),

        # Market data
        "price": _fmt_price(market.get("price")),
        "market_cap": _fmt_large(market.get("market_cap"), currency),
        "beta": f"{market.get('beta'):.2f}" if market.get("beta") else "N/A",
        "week_52_high": _fmt_price(market.get("52w_high")),
        "week_52_low": _fmt_price(market.get("52w_low")),
        "dividend_yield": _fmt_pct(market.get("dividend_yield")),

        # Valuation multiples
        "pe_ratio": _fmt_ratio(market.get("pe_ratio")),
        "forward_pe": _fmt_ratio(market.get("forward_pe")),
        "ev_ebitda": _fmt_ratio(market.get("ev_ebitda")),
        "ev_revenue": _fmt_ratio(market.get("ev_revenue")),
        "ps_ratio": _fmt_ratio(market.get("ps_ratio")),
        "pb_ratio": _fmt_ratio(market.get("pb_ratio")),

        # Key financials (latest year)
        "revenue_latest": _fmt_large(_latest(revenue), currency),
        "revenue_growth": _yoy_growth(revenue),
        "gross_margin": _margin(gross_profit, revenue),
        "operating_margin": _margin(operating_income, revenue),
        "net_margin": _margin(net_income, revenue),
        "ebitda_latest": _fmt_large(_latest(ebitda), currency),
        "fcf_latest": _fmt_large(_latest(fcf), currency),
        "net_debt": _fmt_large(net_debt, currency),
        "eps_ttm": _fmt_price(market.get("eps_ttm")),
        "eps_forward": _fmt_price(market.get("eps_forward")),

        # Sparkline raw data (for mini charts)
        "revenue_series": _sparkline_data(revenue),
        "net_income_series": _sparkline_data(net_income),
        "fcf_series": _sparkline_data(fcf),

        # SEC filings
        "latest_10k": filings_10k[0]["date"] if filings_10k else "N/A",
        "latest_10k_url": filings_10k[0]["url"] if filings_10k else "#",
        "latest_10q": filings_10q[0]["date"] if filings_10q else "N/A",
        "latest_10q_url": filings_10q[0]["url"] if filings_10q else "#",
    }


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def generate_html(data: dict) -> str:
    revenue_series = json.dumps(data["revenue_series"])
    net_income_series = json.dumps(data["net_income_series"])
    fcf_series = json.dumps(data["fcf_series"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{data['ticker']} — Tearsheet</title>
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --ink: #0f1117;
      --ink-light: #4a4f5e;
      --ink-faint: #8a8fa0;
      --paper: #f8f7f4;
      --paper-2: #eeecea;
      --accent: #1a4fd6;
      --accent-light: #e8edfc;
      --green: #0d7a4e;
      --green-bg: #e6f4ee;
      --red: #c0392b;
      --red-bg: #fcecea;
      --border: #d8d5d0;
      --rule: 1px solid var(--border);
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: 'DM Sans', sans-serif;
      background: var(--paper);
      color: var(--ink);
      font-size: 13px;
      line-height: 1.5;
    }}

    /* ── Page layout ── */
    .page {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 32px 40px 48px;
    }}

    /* ── Header ── */
    .header {{
      display: grid;
      grid-template-columns: 1fr auto;
      align-items: start;
      gap: 24px;
      padding-bottom: 20px;
      border-bottom: 2px solid var(--ink);
      margin-bottom: 24px;
    }}

    .company-name {{
      font-family: 'DM Serif Display', serif;
      font-size: 38px;
      line-height: 1.1;
      letter-spacing: -0.02em;
      color: var(--ink);
    }}

    .company-sub {{
      margin-top: 6px;
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }}

    .badge {{
      font-family: 'DM Mono', monospace;
      font-size: 10px;
      font-weight: 500;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      padding: 3px 8px;
      border-radius: 3px;
      background: var(--paper-2);
      border: var(--rule);
      color: var(--ink-light);
    }}

    .badge.ticker {{
      background: var(--ink);
      color: var(--paper);
      border-color: var(--ink);
    }}

    .price-block {{
      text-align: right;
    }}

    .price-main {{
      font-family: 'DM Serif Display', serif;
      font-size: 36px;
      letter-spacing: -0.02em;
      color: var(--accent);
    }}

    .price-meta {{
      font-family: 'DM Mono', monospace;
      font-size: 10px;
      color: var(--ink-faint);
      margin-top: 2px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}

    /* ── Description ── */
    .description {{
      font-size: 12.5px;
      color: var(--ink-light);
      line-height: 1.65;
      margin-bottom: 24px;
      max-width: 820px;
      font-style: italic;
      border-left: 3px solid var(--accent);
      padding-left: 14px;
    }}

    /* ── Section labels ── */
    .section-label {{
      font-family: 'DM Mono', monospace;
      font-size: 9.5px;
      font-weight: 500;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--ink-faint);
      margin-bottom: 10px;
      padding-bottom: 5px;
      border-bottom: var(--rule);
    }}

    /* ── KPI grid ── */
    .kpi-strip {{
      display: grid;
      grid-template-columns: repeat(6, 1fr);
      gap: 1px;
      background: var(--border);
      border: var(--rule);
      border-radius: 6px;
      overflow: hidden;
      margin-bottom: 24px;
    }}

    .kpi-cell {{
      background: white;
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      gap: 3px;
    }}

    .kpi-label {{
      font-family: 'DM Mono', monospace;
      font-size: 9px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--ink-faint);
    }}

    .kpi-value {{
      font-family: 'DM Serif Display', serif;
      font-size: 20px;
      color: var(--ink);
      line-height: 1.1;
    }}

    .kpi-sub {{
      font-family: 'DM Mono', monospace;
      font-size: 9.5px;
      color: var(--ink-faint);
    }}

    .kpi-sub.up {{ color: var(--green); }}
    .kpi-sub.down {{ color: var(--red); }}

    /* ── Two-column body ── */
    .body-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
      margin-bottom: 24px;
    }}

    /* ── Tables ── */
    .data-table {{
      width: 100%;
      border-collapse: collapse;
    }}

    .data-table tr {{
      border-bottom: var(--rule);
    }}

    .data-table tr:last-child {{
      border-bottom: none;
    }}

    .data-table td {{
      padding: 7px 4px;
      font-size: 12px;
    }}

    .data-table td:first-child {{
      color: var(--ink-light);
      width: 55%;
    }}

    .data-table td:last-child {{
      font-family: 'DM Mono', monospace;
      font-size: 11.5px;
      text-align: right;
      font-weight: 500;
      color: var(--ink);
    }}

    /* ── Sparkline charts ── */
    .chart-row {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 16px;
      margin-bottom: 24px;
    }}

    .chart-card {{
      background: white;
      border: var(--rule);
      border-radius: 6px;
      padding: 14px 16px;
    }}

    .chart-title {{
      font-family: 'DM Mono', monospace;
      font-size: 9px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--ink-faint);
      margin-bottom: 10px;
    }}

    canvas.sparkline {{
      width: 100%;
      height: 60px;
      display: block;
    }}

    .chart-latest {{
      margin-top: 6px;
      font-family: 'DM Serif Display', serif;
      font-size: 16px;
      color: var(--ink);
    }}

    /* ── Footer ── */
    .footer {{
      margin-top: 32px;
      padding-top: 14px;
      border-top: var(--rule);
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-family: 'DM Mono', monospace;
      font-size: 9.5px;
      color: var(--ink-faint);
      letter-spacing: 0.04em;
    }}

    .footer a {{
      color: var(--accent);
      text-decoration: none;
    }}

    .filing-links {{
      display: flex;
      gap: 16px;
    }}

    .filing-link {{
      display: flex;
      align-items: center;
      gap: 5px;
      font-family: 'DM Mono', monospace;
      font-size: 10px;
      color: var(--accent);
      text-decoration: none;
      padding: 4px 10px;
      border: 1px solid var(--accent-light);
      border-radius: 4px;
      background: var(--accent-light);
    }}

    .section-card {{
      background: white;
      border: var(--rule);
      border-radius: 6px;
      padding: 16px 18px;
    }}
  </style>
</head>
<body>
<div class="page">

  <!-- Header -->
  <div class="header">
    <div>
      <div class="company-name">{data['name']}</div>
      <div class="company-sub">
        <span class="badge ticker">{data['ticker']}</span>
        <span class="badge">{data['exchange']}</span>
        <span class="badge">{data['sector']}</span>
        <span class="badge">{data['industry']}</span>
      </div>
    </div>
    <div class="price-block">
      <div class="price-main">{data['price']}</div>
      <div class="price-meta">As of {data['as_of']}</div>
      <div class="price-meta" style="margin-top:6px">
        52W: {data['week_52_low']} – {data['week_52_high']}
      </div>
    </div>
  </div>

  <!-- Description -->
  {"<div class='description'>" + data['description'][:320] + "...</div>" if data['description'] else ""}

  <!-- KPI Strip -->
  <div class="kpi-strip">
    <div class="kpi-cell">
      <div class="kpi-label">Market Cap</div>
      <div class="kpi-value">{data['market_cap']}</div>
      <div class="kpi-sub">Market Cap</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">Revenue (TTM)</div>
      <div class="kpi-value">{data['revenue_latest']}</div>
      <div class="kpi-sub {'up' if '▲' in data['revenue_growth'] else 'down'}">{data['revenue_growth']} YoY</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">EBITDA</div>
      <div class="kpi-value">{data['ebitda_latest']}</div>
      <div class="kpi-sub">Latest Annual</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">Free Cash Flow</div>
      <div class="kpi-value">{data['fcf_latest']}</div>
      <div class="kpi-sub">Latest Annual</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">Net Debt</div>
      <div class="kpi-value">{data['net_debt']}</div>
      <div class="kpi-sub">Debt minus Cash</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">Beta</div>
      <div class="kpi-value">{data['beta']}</div>
      <div class="kpi-sub">Market sensitivity</div>
    </div>
  </div>

  <!-- Sparkline Charts -->
  <div class="chart-row">
    <div class="chart-card">
      <div class="chart-title">Revenue — Annual Trend</div>
      <canvas class="sparkline" id="rev-chart"></canvas>
      <div class="chart-latest">{data['revenue_latest']}</div>
    </div>
    <div class="chart-card">
      <div class="chart-title">Net Income — Annual Trend</div>
      <canvas class="sparkline" id="ni-chart"></canvas>
      <div class="chart-latest">{data['net_margin']} net margin</div>
    </div>
    <div class="chart-card">
      <div class="chart-title">Free Cash Flow — Annual Trend</div>
      <canvas class="sparkline" id="fcf-chart"></canvas>
      <div class="chart-latest">{data['fcf_latest']}</div>
    </div>
  </div>

  <!-- Body: Valuation + Financials -->
  <div class="body-grid">
    <div class="section-card">
      <div class="section-label">Valuation Multiples</div>
      <table class="data-table">
        <tr><td>P/E (Trailing)</td><td>{data['pe_ratio']}</td></tr>
        <tr><td>P/E (Forward)</td><td>{data['forward_pe']}</td></tr>
        <tr><td>EV / EBITDA</td><td>{data['ev_ebitda']}</td></tr>
        <tr><td>EV / Revenue</td><td>{data['ev_revenue']}</td></tr>
        <tr><td>Price / Sales</td><td>{data['ps_ratio']}</td></tr>
        <tr><td>Price / Book</td><td>{data['pb_ratio']}</td></tr>
        <tr><td>EPS (TTM)</td><td>{data['eps_ttm']}</td></tr>
        <tr><td>EPS (Forward)</td><td>{data['eps_forward']}</td></tr>
        <tr><td>Dividend Yield</td><td>{data['dividend_yield']}</td></tr>
      </table>
    </div>

    <div class="section-card">
      <div class="section-label">Profitability & Margins</div>
      <table class="data-table">
        <tr><td>Revenue (Latest)</td><td>{data['revenue_latest']}</td></tr>
        <tr><td>Revenue Growth (YoY)</td><td>{data['revenue_growth']}</td></tr>
        <tr><td>Gross Margin</td><td>{data['gross_margin']}</td></tr>
        <tr><td>Operating Margin</td><td>{data['operating_margin']}</td></tr>
        <tr><td>Net Margin</td><td>{data['net_margin']}</td></tr>
        <tr><td>EBITDA</td><td>{data['ebitda_latest']}</td></tr>
        <tr><td>Free Cash Flow</td><td>{data['fcf_latest']}</td></tr>
        <tr><td>Net Debt</td><td>{data['net_debt']}</td></tr>
      </table>
    </div>
  </div>

  <!-- SEC Filings -->
  <div class="section-label">Latest SEC Filings</div>
  <div class="filing-links" style="margin-bottom: 32px;">
    <a class="filing-link" href="{data['latest_10k_url']}" target="_blank">
      📄 10-K Annual Report — {data['latest_10k']}
    </a>
    <a class="filing-link" href="{data['latest_10q_url']}" target="_blank">
      📄 10-Q Quarterly Report — {data['latest_10q']}
    </a>
  </div>

  <!-- Footer -->
  <div class="footer">
    <div>
      Data: yFinance · SEC EDGAR · Generated {data['as_of']}
    </div>
    <div>
      {data['ticker']} · {data['exchange']} · {data['country']} ·
      <a href="{data['website']}" target="_blank">{data['website']}</a>
    </div>
  </div>

</div>

<script>
  // Sparkline renderer
  function drawSparkline(canvasId, rawData, color) {{
    const canvas = document.getElementById(canvasId);
    if (!canvas || !rawData || rawData.length < 2) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = 60 * dpr;
    ctx.scale(dpr, dpr);
    const W = rect.width;
    const H = 60;
    const pad = 4;
    const min = Math.min(...rawData);
    const max = Math.max(...rawData);
    const range = max - min || 1;
    const pts = rawData.map((v, i) => ({{
      x: pad + (i / (rawData.length - 1)) * (W - pad * 2),
      y: H - pad - ((v - min) / range) * (H - pad * 2)
    }}));

    // Fill gradient
    const grad = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0, color + '30');
    grad.addColorStop(1, color + '00');
    ctx.beginPath();
    ctx.moveTo(pts[0].x, H);
    pts.forEach(p => ctx.lineTo(p.x, p.y));
    ctx.lineTo(pts[pts.length - 1].x, H);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Line
    ctx.beginPath();
    pts.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.stroke();

    // End dot
    const last = pts[pts.length - 1];
    ctx.beginPath();
    ctx.arc(last.x, last.y, 3.5, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  }}

  window.addEventListener('load', () => {{
    drawSparkline('rev-chart',  {revenue_series},    '#1a4fd6');
    drawSparkline('ni-chart',   {net_income_series}, '#0d7a4e');
    drawSparkline('fcf-chart',  {fcf_series},        '#7c3aed');
  }});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(ticker: str):
    print(f"\n📊 Generating tearsheet for {ticker.upper()}...")

    data = build_tearsheet_data(ticker)
    html = generate_html(data)

    out_dir = Path("reports")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{ticker.upper()}_tearsheet.html"
    out_path.write_text(html, encoding="utf-8")

    print(f"\n✅ Tearsheet saved → {out_path}")
    print(f"   Open in browser: file://{out_path.resolve()}")
    return str(out_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python recipes/tearsheet.py <TICKER>")
        print("Example: python recipes/tearsheet.py AAPL")
        sys.exit(1)
    run(sys.argv[1])
