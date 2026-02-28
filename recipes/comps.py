"""
comps.py — Free replacement for Daloopa's /comps command
=========================================================
Generates a trading comparables HTML report using yFinance + SEC EDGAR.

Usage:
    # Auto-discover peers from built-in sector map
    python recipes/comps.py AAPL

    # Provide your own peer set
    python recipes/comps.py AAPL MSFT GOOG AMZN META

Output:
    reports/<TICKER>_comps.html

Peer discovery logic:
    1. If extra tickers are passed as arguments → use those
    2. Otherwise → look up sector/industry from yFinance and
       pull from the built-in SECTOR_PEERS map
    3. If sector not in map → report lists subject only and
       instructs analyst to pass peers manually
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from free_client import discover_companies, get_company_fundamentals

# ---------------------------------------------------------------------------
# Built-in sector peer map
# Covers the most common sectors analysts comp against.
# Pass your own tickers on the CLI to override for any company.
# ---------------------------------------------------------------------------

SECTOR_PEERS = {
    # Technology
    "Consumer Electronics":         ["AAPL", "SONY", "SMSN", "HPQ", "DELL"],
    "Software—Infrastructure":      ["MSFT", "ORCL", "IBM", "CSCO", "VMW"],
    "Software—Application":         ["CRM", "NOW", "WDAY", "ADBE", "INTU"],
    "Semiconductors":               ["NVDA", "AMD", "INTC", "QCOM", "AVGO"],
    "Internet Content & Information":["GOOGL", "META", "SNAP", "PINS", "TWTR"],
    # E-commerce / Consumer
    "Internet Retail":              ["AMZN", "BABA", "JD", "EBAY", "ETSY"],
    "Specialty Retail":             ["HD", "LOW", "TGT", "WMT", "COST"],
    # Financials
    "Banks—Diversified":            ["JPM", "BAC", "WFC", "C", "GS"],
    "Asset Management":             ["BLK", "SCHW", "MS", "BX", "KKR"],
    "Insurance—Diversified":        ["BRK-B", "MET", "PRU", "AFL", "TRV"],
    # Healthcare
    "Drug Manufacturers—General":   ["JNJ", "PFE", "MRK", "ABBV", "LLY"],
    "Medical Devices":              ["MDT", "ABT", "SYK", "EW", "ZBH"],
    "Health Information Services":  ["UNH", "CVS", "CI", "HUM", "CNC"],
    # Industrials
    "Aerospace & Defense":          ["BA", "LMT", "RTX", "NOC", "GD"],
    "Industrial Conglomerates":     ["GE", "HON", "MMM", "EMR", "ETN"],
    # Energy
    "Oil & Gas Integrated":         ["XOM", "CVX", "BP", "SHEL", "TTE"],
    "Oil & Gas E&P":                ["COP", "EOG", "PXD", "DVN", "MRO"],
    # Communication
    "Telecom Services":             ["T", "VZ", "TMUS", "CMCSA", "CHTR"],
    "Entertainment":                ["DIS", "NFLX", "WBD", "PARA", "FOXA"],
    # Real Estate
    "REIT—Diversified":             ["AMT", "PLD", "CCI", "EQIX", "SPG"],
}


def _find_peers(subject_ticker: str, company_info: dict) -> list[str]:
    """
    Return a list of peer tickers for the subject company.
    Excludes the subject itself from the peer list.
    """
    industry = company_info.get("industry", "")
    sector   = company_info.get("sector", "")

    # Try industry first (more specific), then sector
    for key in [industry, sector]:
        if key in SECTOR_PEERS:
            peers = [t for t in SECTOR_PEERS[key] if t != subject_ticker.upper()]
            return peers[:6]  # cap at 6 peers for table width

    return []


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt(val, kind="number"):
    if val is None:
        return "—"
    try:
        if kind == "price":
            return f"${val:,.2f}"
        if kind == "large":
            if abs(val) >= 1e12: return f"${val/1e12:.1f}T"
            if abs(val) >= 1e9:  return f"${val/1e9:.1f}B"
            if abs(val) >= 1e6:  return f"${val/1e6:.1f}M"
            return f"${val:,.0f}"
        if kind == "multiple":
            return f"{val:.1f}x"
        if kind == "pct":
            return f"{val*100:.1f}%" if abs(val) < 100 else f"{val:.1f}%"
        if kind == "growth":
            arrow = "▲" if val >= 0 else "▼"
            return f"{arrow} {abs(val)*100:.1f}%"
    except (TypeError, ValueError):
        return "—"
    return str(val)


def _latest(series: dict):
    if not series:
        return None
    key = sorted(series.keys(), reverse=True)[0]
    return series[key]


def _yoy_growth(series: dict):
    if not series or len(series) < 2:
        return None
    dates = sorted(series.keys(), reverse=True)
    cur, pri = series[dates[0]], series[dates[1]]
    if not pri or pri == 0:
        return None
    return (cur - pri) / abs(pri)


def _gross_margin(data: dict):
    rev = _latest(data.get("income_statement", {}).get("revenue", {}))
    gp  = _latest(data.get("income_statement", {}).get("gross_profit", {}))
    if not rev or not gp or rev == 0:
        return None
    return gp / rev


def _net_margin(data: dict):
    rev = _latest(data.get("income_statement", {}).get("revenue", {}))
    ni  = _latest(data.get("income_statement", {}).get("net_income", {}))
    if not rev or not ni or rev == 0:
        return None
    return ni / rev


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------

def build_comps_data(subject: str, peers: list[str]) -> dict:
    """Fetch fundamentals for subject + all peers."""
    all_tickers = [subject.upper()] + [p.upper() for p in peers]
    rows = []

    for ticker in all_tickers:
        print(f"  Fetching {ticker}...")
        try:
            info  = discover_companies(ticker)
            data  = get_company_fundamentals(ticker, period="annual")
            mkt   = data.get("market_data", {})
            inc   = data.get("income_statement", {})
            cf    = data.get("cash_flow", {})

            rows.append({
                "ticker":       ticker,
                "name":         info.get("name", ticker),
                "is_subject":   ticker == subject.upper(),

                # Market
                "price":        _fmt(mkt.get("price"),      "price"),
                "market_cap":   _fmt(mkt.get("market_cap"), "large"),
                "market_cap_raw": mkt.get("market_cap"),

                # Valuation multiples
                "pe_trailing":  _fmt(mkt.get("pe_ratio"),   "multiple"),
                "pe_forward":   _fmt(mkt.get("forward_pe"), "multiple"),
                "ev_ebitda":    _fmt(mkt.get("ev_ebitda"),  "multiple"),
                "ev_revenue":   _fmt(mkt.get("ev_revenue"), "multiple"),
                "ps_ratio":     _fmt(mkt.get("ps_ratio"),   "multiple"),
                "pb_ratio":     _fmt(mkt.get("pb_ratio"),   "multiple"),

                # Financials
                "revenue":      _fmt(_latest(inc.get("revenue", {})),    "large"),
                "revenue_growth": _fmt(_yoy_growth(inc.get("revenue", {})), "growth"),
                "ebitda":       _fmt(_latest(inc.get("ebitda", {})),     "large"),
                "fcf":          _fmt(_latest(cf.get("free_cash_flow", {})), "large"),

                # Margins
                "gross_margin": _fmt(_gross_margin(data), "pct"),
                "net_margin":   _fmt(_net_margin(data),   "pct"),

                # Other
                "beta":         _fmt(mkt.get("beta"), "number") if mkt.get("beta") else "—",
                "dividend_yield": _fmt(mkt.get("dividend_yield"), "pct") if mkt.get("dividend_yield") else "—",
                "eps_ttm":      _fmt(mkt.get("eps_ttm"),     "price"),
                "eps_forward":  _fmt(mkt.get("eps_forward"), "price"),
            })
        except Exception as e:
            print(f"  ⚠️  Could not fetch {ticker}: {e}")
            rows.append({"ticker": ticker, "name": ticker, "is_subject": ticker == subject.upper(), "error": True})

    return rows


# ---------------------------------------------------------------------------
# Implied valuation (football field lite)
# Uses peer median multiples applied to subject's own financials
# ---------------------------------------------------------------------------

def implied_valuation(rows: list[dict], subject_data: dict) -> list[dict]:
    """
    Compute implied market cap ranges using peer median multiples
    applied to subject's actual financials.
    """
    import statistics

    peers = [r for r in rows if not r.get("is_subject") and not r.get("error")]
    subject = next((r for r in rows if r.get("is_subject")), None)
    if not subject or not peers:
        return []

    def _parse_multiple(s):
        try:
            return float(s.replace("x","").replace("—","").strip())
        except:
            return None

    def _parse_large(s):
        try:
            s = s.replace("$","").strip()
            if "T" in s: return float(s.replace("T","")) * 1e12
            if "B" in s: return float(s.replace("B","")) * 1e9
            if "M" in s: return float(s.replace("M","")) * 1e6
            return float(s.replace(",",""))
        except:
            return None

    inc  = subject_data.get("income_statement", {})
    cf   = subject_data.get("cash_flow", {})
    mkt  = subject_data.get("market_data", {})

    subj_revenue = _latest(inc.get("revenue", {}))
    subj_ebitda  = _latest(inc.get("ebitda", {}))
    subj_fcf     = _latest(cf.get("free_cash_flow", {}))
    subj_eps     = mkt.get("eps_ttm")
    subj_shares  = (mkt.get("market_cap") / mkt.get("price")) if mkt.get("market_cap") and mkt.get("price") else None

    results = []

    def _implied(metric_name, metric_val, multiple_key, label, unit="market_cap"):
        vals = [_parse_multiple(p.get(multiple_key, "")) for p in peers]
        vals = [v for v in vals if v and v > 0]
        if not vals or not metric_val:
            return
        med = statistics.median(vals)
        implied = metric_val * med
        if unit == "price" and subj_shares:
            implied_price = implied / subj_shares
            results.append({
                "method": label,
                "peer_median_multiple": f"{med:.1f}x",
                "implied_value": f"${implied_price:,.2f} / share",
            })
        else:
            results.append({
                "method": label,
                "peer_median_multiple": f"{med:.1f}x",
                "implied_value": f"${implied/1e9:.1f}B market cap",
            })

    _implied("revenue",  subj_revenue, "ev_revenue", "EV / Revenue → implied mkt cap")
    _implied("ebitda",   subj_ebitda,  "ev_ebitda",  "EV / EBITDA → implied mkt cap")
    _implied("ps_ratio", subj_revenue, "ps_ratio",   "P / Sales → implied mkt cap")
    _implied("eps",
             subj_eps * subj_shares if subj_eps and subj_shares else None,
             "pe_trailing", "P / E (trailing) → implied mkt cap")

    return results


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

METRICS = [
    ("price",         "Price"),
    ("market_cap",    "Market Cap"),
    ("pe_trailing",   "P/E (Trailing)"),
    ("pe_forward",    "P/E (Forward)"),
    ("ev_ebitda",     "EV / EBITDA"),
    ("ev_revenue",    "EV / Revenue"),
    ("ps_ratio",      "P / Sales"),
    ("pb_ratio",      "P / Book"),
    ("revenue",       "Revenue (LTM)"),
    ("revenue_growth","Revenue Growth"),
    ("ebitda",        "EBITDA (LTM)"),
    ("fcf",           "Free Cash Flow"),
    ("gross_margin",  "Gross Margin"),
    ("net_margin",    "Net Margin"),
    ("eps_ttm",       "EPS (TTM)"),
    ("eps_forward",   "EPS (Forward)"),
    ("beta",          "Beta"),
    ("dividend_yield","Dividend Yield"),
]

SECTION_BREAKS = {
    "revenue": "── Financials ──",
    "eps_ttm": "── Per Share & Other ──",
}


def generate_html(rows: list[dict], implied: list[dict], subject_ticker: str, as_of: str) -> str:
    subject = next((r for r in rows if r.get("is_subject")), rows[0])
    subject_name = subject.get("name", subject_ticker)

    # Table header
    header_cells = "".join(
        f'<th class="{"subject-col" if r.get("is_subject") else ""}">'
        f'{"★ " if r.get("is_subject") else ""}{r["ticker"]}</th>'
        for r in rows if not r.get("error")
    )

    # Table body rows
    body_rows = ""
    for key, label in METRICS:
        if key in SECTION_BREAKS:
            body_rows += f'<tr class="section-break"><td colspan="{len(rows)+1}">{SECTION_BREAKS[key]}</td></tr>'
        cells = ""
        for r in rows:
            if r.get("error"):
                continue
            val = r.get(key, "—")
            cls = "subject-col" if r.get("is_subject") else ""
            # Highlight growth direction
            if key == "revenue_growth" and val != "—":
                cls += " green" if "▲" in val else " red"
            cells += f'<td class="{cls}">{val}</td>'
        body_rows += f"<tr><td class='metric-label'>{label}</td>{cells}</tr>"

    # Implied valuation table
    implied_rows = ""
    for imp in implied:
        implied_rows += f"""
        <tr>
            <td>{imp['method']}</td>
            <td>{imp['peer_median_multiple']}</td>
            <td class="implied-val">{imp['implied_value']}</td>
        </tr>"""

    implied_section = f"""
    <h2>Implied Valuation (Peer Median Multiples → {subject_ticker})</h2>
    <p class="note">Peer median multiples applied to {subject_ticker}'s own financials. For context only — not a price target.</p>
    <table class="comps-table">
        <thead><tr><th>Method</th><th>Peer Median Multiple</th><th>Implied Value</th></tr></thead>
        <tbody>{implied_rows}</tbody>
    </table>""" if implied_rows else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject_ticker} — Trading Comps</title>
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --ink: #0f1117;
      --ink-light: #4a4f5e;
      --ink-faint: #8a8fa0;
      --paper: #f8f7f4;
      --paper-2: #eeecea;
      --accent: #1a4fd6;
      --accent-bg: #e8edfc;
      --subject-bg: #fffbea;
      --subject-border: #f0c040;
      --green: #0d7a4e;
      --red: #c0392b;
      --border: #d8d5d0;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'DM Sans', sans-serif; background: var(--paper); color: var(--ink); font-size: 13px; }}
    .page {{ max-width: 1200px; margin: 0 auto; padding: 32px 40px 56px; }}

    /* Header */
    .header {{ border-bottom: 2px solid var(--ink); padding-bottom: 16px; margin-bottom: 24px; }}
    .title {{ font-family: 'DM Serif Display', serif; font-size: 32px; letter-spacing: -0.02em; }}
    .subtitle {{ font-family: 'DM Mono', monospace; font-size: 10px; color: var(--ink-faint); letter-spacing: 0.08em; text-transform: uppercase; margin-top: 4px; }}

    /* Section */
    h2 {{ font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase;
          color: var(--ink-faint); margin: 28px 0 12px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }}
    .note {{ font-size: 11px; color: var(--ink-faint); font-style: italic; margin-bottom: 12px; margin-top: -8px; }}

    /* Comps table */
    .comps-table {{ width: 100%; border-collapse: collapse; overflow-x: auto; display: block; }}
    .comps-table th, .comps-table td {{
      padding: 7px 12px;
      text-align: right;
      white-space: nowrap;
      font-family: 'DM Mono', monospace;
      font-size: 11.5px;
      border-bottom: 1px solid var(--border);
    }}
    .comps-table th {{
      background: var(--paper-2);
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--ink-light);
      position: sticky;
      top: 0;
    }}
    .comps-table td.metric-label {{
      text-align: left;
      color: var(--ink-light);
      font-family: 'DM Sans', sans-serif;
      font-size: 12px;
      width: 180px;
    }}

    /* Subject column highlight */
    .subject-col {{
      background: var(--subject-bg);
      border-left: 2px solid var(--subject-border);
      border-right: 2px solid var(--subject-border);
      font-weight: 600;
    }}
    th.subject-col {{ background: #fff8d6; }}

    /* Section break rows */
    .section-break td {{
      background: var(--paper-2);
      font-family: 'DM Mono', monospace;
      font-size: 9px;
      letter-spacing: 0.1em;
      color: var(--ink-faint);
      text-transform: uppercase;
      text-align: left;
      padding: 5px 12px;
    }}

    /* Color */
    td.green {{ color: var(--green); }}
    td.red   {{ color: var(--red); }}
    td.implied-val {{ color: var(--accent); font-weight: 600; }}

    /* Footer */
    .footer {{ margin-top: 40px; padding-top: 12px; border-top: 1px solid var(--border);
               font-family: 'DM Mono', monospace; font-size: 9.5px; color: var(--ink-faint); }}
  </style>
</head>
<body>
<div class="page">

  <div class="header">
    <div class="title">{subject_name} ({subject_ticker}) — Trading Comparables</div>
    <div class="subtitle">★ = Subject company &nbsp;·&nbsp; LTM = Last Twelve Months &nbsp;·&nbsp; As of {as_of}</div>
  </div>

  <h2>Valuation & Financials</h2>
  <table class="comps-table">
    <thead>
      <tr>
        <th style="text-align:left">Metric</th>
        {header_cells}
      </tr>
    </thead>
    <tbody>
      {body_rows}
    </tbody>
  </table>

  {implied_section}

  <div class="footer">
    Data: yFinance / SEC EDGAR &nbsp;·&nbsp; Generated {as_of} &nbsp;·&nbsp;
    Multiples based on latest available annual filings. Not investment advice.
  </div>

</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(subject: str, extra_peers: list[str] = None):
    print(f"\n📊 Building comps for {subject.upper()}...")

    # Step 1 — subject company info
    print("  Fetching subject company info...")
    subject_info = discover_companies(subject)
    subject_data = get_company_fundamentals(subject, period="annual")

    # Step 2 — peer discovery
    if extra_peers:
        peers = [p.upper() for p in extra_peers if p.upper() != subject.upper()]
        print(f"  Using provided peers: {peers}")
    else:
        peers = _find_peers(subject, subject_info)
        if peers:
            print(f"  Auto-discovered peers ({subject_info.get('industry', 'unknown')}): {peers}")
        else:
            print(f"  ⚠️  No peers found for sector '{subject_info.get('sector')}' / industry '{subject_info.get('industry')}'.")
            print(f"     Pass peers manually: python recipes/comps.py {subject.upper()} TICKER1 TICKER2 ...")
            peers = []

    # Step 3 — fetch all data
    rows = build_comps_data(subject, peers)

    # Step 4 — implied valuation
    imp = implied_valuation(rows, subject_data)

    # Step 5 — generate HTML
    as_of = datetime.now().strftime("%B %d, %Y")
    html  = generate_html(rows, imp, subject.upper(), as_of)

    # Step 6 — save
    out_dir  = Path("reports")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{subject.upper()}_comps.html"
    out_path.write_text(html, encoding="utf-8")

    print(f"\n✅ Comps saved → {out_path}")
    print(f"   Open in browser: file://{out_path.resolve()}")
    return str(out_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python recipes/comps.py AAPL                        # auto peers")
        print("  python recipes/comps.py AAPL MSFT GOOG AMZN META   # manual peers")
        sys.exit(1)

    subject_ticker = sys.argv[1]
    manual_peers   = sys.argv[2:] if len(sys.argv) > 2 else None
    run(subject_ticker, manual_peers)
