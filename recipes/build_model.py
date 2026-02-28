"""
build_model.py — Free replacement for Daloopa's /build-model command
=====================================================================
Builds a multi-tab Excel financial model using yFinance + SEC EDGAR.
Orchestrates: free_client → projection_engine → excel_builder

Usage:
    python recipes/build_model.py AAPL
    python recipes/build_model.py MSFT --quarters 12
    python recipes/build_model.py NVDA --peers AMD INTC QCOM AVGO

Output:
    reports/<TICKER>_model.xlsx
    reports/.tmp/<TICKER>_model_context.json   (debug / reuse)
    reports/.tmp/<TICKER>_projection_input.json

Pipeline:
    Phase 1 — Company + market data        → free_client.discover_companies()
    Phase 2 — Historical financials (16Q)  → free_client.build_model_context()
    Phase 3 — Peer multiples               → infra/market_data.py peers
    Phase 4 — Projections                  → infra/projection_engine.py
    Phase 5 — DCF                          → computed inline
    Phase 6 — Build Excel                  → infra/excel_builder.py
"""

import sys
import json
import subprocess
import statistics
from pathlib import Path
from datetime import datetime

# Add recipes/ to path
sys.path.insert(0, str(Path(__file__).parent))
from free_client import build_model_context, get_recent_filings

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

INFRA_DIR = Path(__file__).parent.parent / "infra"
TMP_DIR   = Path("reports") / ".tmp"


def _run(cmd: list[str]) -> dict | list | None:
    """Run a subprocess, parse stdout as JSON, return result."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f"  ⚠️  Command failed: {' '.join(cmd)}")
            print(f"     stderr: {result.stderr[:300]}")
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        print(f"  ⚠️  {e}")
        return None


# ---------------------------------------------------------------------------
# Phase 3 — Peer multiples
# ---------------------------------------------------------------------------

def fetch_peer_multiples(peers: list[str]) -> list[dict]:
    """Fetch trading multiples for peer tickers via market_data.py."""
    if not peers:
        return []
    print(f"  Fetching peer multiples: {peers}...")
    script = INFRA_DIR / "market_data.py"
    result = _run([sys.executable, str(script), "peers"] + peers)
    if result and isinstance(result, list):
        return result
    return []


# ---------------------------------------------------------------------------
# Phase 4 — Projections
# ---------------------------------------------------------------------------

def run_projections(projection_input: dict, ticker: str) -> dict | None:
    """Run projection_engine.py and return projections dict."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    input_path  = TMP_DIR / f"{ticker}_projection_input.json"
    output_path = TMP_DIR / f"{ticker}_projections.json"

    # Write input
    input_path.write_text(json.dumps(projection_input, indent=2))

    print(f"  Running projection engine ({projection_input['projection_quarters']}Q forward)...")
    script = INFRA_DIR / "projection_engine.py"
    result = subprocess.run(
        [sys.executable, str(script),
         "--context", str(input_path),
         "--output", str(output_path)],
        capture_output=True, text=True, timeout=30
    )

    if result.returncode != 0:
        print(f"  ⚠️  projection_engine failed: {result.stderr[:300]}")
        return None

    try:
        with open(output_path) as f:
            return json.load(f)
    except Exception as e:
        print(f"  ⚠️  Could not read projection output: {e}")
        return None


# ---------------------------------------------------------------------------
# Phase 5 — DCF
# ---------------------------------------------------------------------------

def compute_dcf(projection_output: dict, dcf_inputs: dict,
                market_data: dict) -> dict:
    """
    Compute DCF from projected FCF values.
    Returns a dict compatible with excel_builder's dcf section.
    """
    if not projection_output:
        return {}

    projections = projection_output.get("projections", {})
    fcf_list    = projections.get("fcf", [])
    periods     = projections.get("periods", [])

    wacc           = dcf_inputs.get("wacc", 0.10)
    terminal_growth = dcf_inputs.get("terminal_growth", 0.025)
    rf              = dcf_inputs.get("risk_free_rate", 0.045)
    erp             = dcf_inputs.get("equity_risk_premium", 0.055)

    if not fcf_list:
        return {
            "wacc": wacc,
            "terminal_growth": terminal_growth,
            "risk_free_rate": rf,
            "equity_risk_premium": erp,
        }

    # Annualise quarterly FCFs (sum every 4 quarters)
    annual_fcf = []
    for i in range(0, len(fcf_list), 4):
        chunk = fcf_list[i:i+4]
        if len(chunk) == 4:
            annual_fcf.append(sum(v for v in chunk if v))

    if not annual_fcf:
        annual_fcf = [sum(v for v in fcf_list if v)]

    # PV of projected FCFs
    pv_fcf = sum(
        fcf / (1 + wacc) ** (t + 1)
        for t, fcf in enumerate(annual_fcf)
        if fcf
    )

    # Terminal value (Gordon Growth)
    last_fcf = annual_fcf[-1] if annual_fcf else 0
    terminal_value = last_fcf * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_terminal    = terminal_value / (1 + wacc) ** len(annual_fcf)

    enterprise_value = pv_fcf + pv_terminal

    # Implied share price
    mkt_cap = market_data.get("market_cap")
    price   = market_data.get("price")
    shares  = market_data.get("shares_outstanding")
    if not shares and mkt_cap and price and price > 0:
        shares = mkt_cap / price

    implied_price = (enterprise_value / shares) if shares else None

    # Sensitivity matrix: WACC ± 150bps × terminal growth ± 50bps
    wacc_range   = [round(wacc + (i - 3) * 0.005, 3) for i in range(7)]   # 7 WACC values
    growth_range = [round(terminal_growth + (j - 2) * 0.005, 3) for j in range(6)]  # 6 growth values

    sens_prices = []
    for w in wacc_range:
        row = []
        for g in growth_range:
            if w <= g:
                row.append(None)
                continue
            tv  = last_fcf * (1 + g) / (w - g)
            pvt = tv / (1 + w) ** len(annual_fcf)
            pv  = sum(fcf / (1 + w) ** (t + 1) for t, fcf in enumerate(annual_fcf) if fcf)
            ev  = pv + pvt
            sp  = round(ev / shares, 2) if shares else None
            row.append(sp)
        sens_prices.append(row)

    return {
        "wacc":              wacc,
        "terminal_growth":   terminal_growth,
        "risk_free_rate":    rf,
        "equity_risk_premium": erp,
        "projected_fcf":     annual_fcf,
        "terminal_value":    round(terminal_value),
        "enterprise_value":  round(enterprise_value),
        "implied_share_price": round(implied_price, 2) if implied_price else None,
        "sensitivity": {
            "wacc_values":   [round(w * 100, 2) for w in wacc_range],
            "growth_values": [round(g * 100, 2) for g in growth_range],
            "prices":        sens_prices,
        },
    }


# ---------------------------------------------------------------------------
# Projection output → excel_builder format
# ---------------------------------------------------------------------------

def projections_to_excel_format(projection_output: dict) -> tuple[list, dict, dict]:
    """
    Convert projection_engine output to excel_builder projected_periods + projections.

    Returns:
        projected_periods: list of quarter labels
        projections: {metric_name: {period: value}} for excel_builder
        assumptions: projection_assumptions dict for excel_builder Projections tab
    """
    if not projection_output:
        return [], {}, {}

    proj    = projection_output.get("projections", {})
    periods = proj.get("periods", [])
    methods = projection_output.get("assumptions", {}).get("methods", {})

    # Map projection_engine keys → excel_builder Title Case names
    key_map = {
        "revenue":           "Revenue",
        "gross_profit":      "Gross Profit",
        "operating_income":  "Operating Income",
        "net_income":        "Net Income",
        "capex":             "Capital Expenditures",
        "depreciation":      "D&A",
        "eps":               "EPS",
        "fcf":               "Free Cash Flow",
    }

    projections_dict = {}
    for eng_key, excel_key in key_map.items():
        values = proj.get(eng_key)
        if values and periods:
            projections_dict[excel_key] = dict(zip(periods, values))

    # Margin series as pct (0-1 range for excel_builder number_format "0.0%")
    for eng_key, excel_key in [("gross_margin", "Gross Margin %"),
                                ("operating_margin", "Operating Margin %"),
                                ("net_margin", "Net Margin %")]:
        values = proj.get(eng_key)
        if values and periods:
            projections_dict[excel_key] = dict(zip(periods, values))

    # projection_assumptions dict (time-varying as {period: value})
    tax_rates    = proj.get("tax_rate", [])
    rev_growth   = projection_output.get("assumptions", {}).get("methods", {})
    shares_list  = proj.get("shares_outstanding", [])
    rev_list     = proj.get("revenue", [])
    capex_list   = proj.get("capex", [])

    capex_pct = {}
    if rev_list and capex_list and periods:
        for p, r, c in zip(periods, rev_list, capex_list):
            if r and r != 0 and c:
                capex_pct[p] = abs(c) / r

    assumptions = {
        "tax_rate":           tax_rates[0] if tax_rates else 0.16,
        "capex_pct_revenue":  capex_pct if capex_pct else 0.05,
        "buyback_rate_qoq":   -0.002,   # placeholder — analyst edits in yellow cell
    }

    return periods, projections_dict, assumptions


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run(ticker: str, extra_peers: list[str] = None,
        n_quarters: int = 8):

    ticker = ticker.upper()
    print(f"\n📊 Building model for {ticker}...")
    print(f"   Projection horizon: {n_quarters}Q | Output: reports/{ticker}_model.xlsx\n")

    # ── Phase 1+2: Historical data ──────────────────────────────────────────
    print("Phase 1+2 — Fetching historical financials...")
    ctx = build_model_context(ticker, n_projection_quarters=n_quarters)

    # ── Phase 3: Peers ──────────────────────────────────────────────────────
    print("\nPhase 3 — Peer multiples...")
    peers = extra_peers or []
    peer_multiples = fetch_peer_multiples(peers) if peers else []

    # ── Phase 4: Projections ────────────────────────────────────────────────
    print("\nPhase 4 — Forward projections...")
    proj_output = run_projections(ctx["projection_input"], ticker)

    projected_periods, projections_dict, proj_assumptions = (
        projections_to_excel_format(proj_output)
    )

    # ── Phase 5: DCF ────────────────────────────────────────────────────────
    print("\nPhase 5 — DCF valuation...")
    dcf = compute_dcf(proj_output, ctx["dcf_inputs"], ctx["market_data"])
    if dcf.get("implied_share_price"):
        current = ctx["market_data"].get("price", 0)
        implied = dcf["implied_share_price"]
        updown  = ((implied - current) / current * 100) if current else 0
        print(f"   DCF implied: ${implied:,.2f}  |  Current: ${current:,.2f}  |  {updown:+.1f}%")

    # ── Phase 6: Assemble context JSON ─────────────────────────────────────
    print("\nPhase 6 — Assembling Excel context...")
    excel_ctx = {
        "company":     ctx["company"],
        "market_data": ctx["market_data"],
        "periods":     ctx["periods"],
        "projected_periods": projected_periods,

        "income_statement": ctx["income_statement"],
        "balance_sheet":    ctx["balance_sheet"],
        "cash_flow":        ctx["cash_flow"],

        "projections":             projections_dict,
        "projection_assumptions":  proj_assumptions,

        "dcf":   dcf,
        "comps": {"peers": peer_multiples} if peer_multiples else None,
    }

    # Remove None sections
    excel_ctx = {k: v for k, v in excel_ctx.items() if v is not None}

    # Save context JSON
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    ctx_path = TMP_DIR / f"{ticker}_model_context.json"
    ctx_path.write_text(json.dumps(excel_ctx, indent=2, default=str))
    print(f"   Context JSON → {ctx_path}")

    # ── Phase 6: Run excel_builder ──────────────────────────────────────────
    out_dir  = Path("reports")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{ticker}_model.xlsx"

    script = INFRA_DIR / "excel_builder.py"
    print(f"   Running excel_builder...")
    result = subprocess.run(
        [sys.executable, str(script),
         "--context", str(ctx_path),
         "--output",  str(out_path)],
        capture_output=True, text=True, timeout=60
    )

    if result.returncode != 0:
        print(f"\n❌ excel_builder failed:")
        print(f"   {result.stderr[:500]}")
        print(f"   Context JSON saved for debugging: {ctx_path}")
        return

    # ── Summary ─────────────────────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"✅ Model saved → {out_path}")
    print(f"   Context JSON → {ctx_path}")
    print(f"\n📋 Model Summary:")
    print(f"   Periods:           {len(ctx['periods'])} quarters historical")
    print(f"   Projected:         {len(projected_periods)} quarters forward")

    rev = ctx["income_statement"].get("Revenue", {})
    if rev:
        latest_period = sorted(rev.keys())[-1]
        latest_rev = rev[latest_period]
        if latest_rev and latest_rev >= 1e9:
            print(f"   Latest Revenue:    ${latest_rev/1e9:.2f}B ({latest_period})")

    if dcf.get("implied_share_price"):
        print(f"   DCF Implied Price: ${dcf['implied_share_price']:,.2f}")
    if peer_multiples:
        print(f"   Peers included:    {[p['ticker'] for p in peer_multiples]}")

    print(f"\n💡 Yellow cells in the Projections tab are editable inputs.")
    print(f"   Segments and KPIs require manual addition from SEC filings.")

    # SEC filing links
    filings = get_recent_filings(ticker, "10-K", limit=1)
    if filings:
        print(f"\n📄 Latest 10-K: {filings[0]['url']}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Build multi-tab Excel financial model using free data sources."
    )
    parser.add_argument("ticker", help="Stock ticker symbol")
    parser.add_argument(
        "--peers", nargs="*", default=[],
        help="Peer tickers for comps tab (e.g. --peers MSFT GOOG AMZN)"
    )
    parser.add_argument(
        "--quarters", type=int, default=8,
        help="Number of quarters to project forward (default: 8)"
    )
    args = parser.parse_args()

    run(args.ticker, extra_peers=args.peers, n_quarters=args.quarters)
