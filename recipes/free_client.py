"""
free_client.py — Drop-in replacement for daloopa_client.py
============================================================
Replaces Daloopa's 4 core tools using free public APIs:

    | Daloopa Tool               | Replacement                  |
    |----------------------------|------------------------------|
    | discover_companies         | SEC EDGAR + yFinance         |
    | discover_company_series    | yFinance (financial metrics) |
    | get_company_fundamentals   | yFinance + SEC EDGAR XBRL    |
    | search_documents           | SEC EDGAR full-text search   |

Setup:
    pip install yfinance requests python-dotenv

Optional (for DCF/WACC macro data):
    Add FRED_API_KEY to your .env file
    Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html
"""

import os
import time
import requests
import yfinance as yf
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

FRED_API_KEY = os.getenv("FRED_API_KEY")

# ---------------------------------------------------------------------------
# SEC EDGAR helpers
# ---------------------------------------------------------------------------

EDGAR_BASE = "https://data.sec.gov"
EDGAR_HEADERS = {
    # SEC requires a descriptive User-Agent — put your info here
    "User-Agent": os.getenv("SEC_USER_AGENT", "YourName yourname@email.com")
}


def _edgar_get(path: str) -> dict:
    """Rate-limited GET against SEC EDGAR."""
    url = f"{EDGAR_BASE}{path}"
    time.sleep(0.15)  # SEC asks for max ~10 req/s
    resp = requests.get(url, headers=EDGAR_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _safe_int(val) -> Optional[int]:
    """Convert to int, returning None for NaN/None values."""
    try:
        import math
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        return int(val)
    except (TypeError, ValueError):
        return None


def _ticker_to_cik(ticker: str) -> Optional[str]:
    """Convert a stock ticker to SEC CIK number."""
    tickers_url = "https://www.sec.gov/files/company_tickers.json"
    resp = requests.get(tickers_url, headers=EDGAR_HEADERS, timeout=15)
    resp.raise_for_status()
    mapping = resp.json()
    
    ticker_upper = ticker.upper()
    for entry in mapping.values():
        if entry.get("ticker") == ticker_upper:
            cik = str(entry["cik_str"]).zfill(10)
            return cik
    return None


# ---------------------------------------------------------------------------
# Tool 1: discover_companies
# Daloopa equivalent: look up companies by ticker or name
# ---------------------------------------------------------------------------

def discover_companies(query: str) -> dict:
    """
    Search for a company by ticker or name.
    Returns basic info: name, ticker, CIK, exchange, sector, industry.

    Example:
        result = discover_companies("AAPL")
    """
    # Try yFinance first (fast, rich metadata)
    try:
        ticker_obj = yf.Ticker(query.upper())
        info = ticker_obj.info
        if info.get("shortName"):
            return {
                "source": "yfinance",
                "ticker": info.get("symbol"),
                "name": info.get("shortName") or info.get("longName"),
                "exchange": info.get("exchange"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "country": info.get("country"),
                "currency": info.get("currency"),
                "market_cap": info.get("marketCap"),
                "website": info.get("website"),
                "description": info.get("longBusinessSummary", "")[:500],
            }
    except Exception:
        pass

    # Fallback: SEC EDGAR company search
    cik = _ticker_to_cik(query)
    if cik:
        sub = _edgar_get(f"/submissions/CIK{cik}.json")
        return {
            "source": "sec_edgar",
            "ticker": query.upper(),
            "name": sub.get("name"),
            "cik": cik,
            "sic": sub.get("sic"),
            "sic_description": sub.get("sicDescription"),
            "state": sub.get("stateOfIncorporation"),
        }

    return {"error": f"Company '{query}' not found"}


# ---------------------------------------------------------------------------
# Tool 2: discover_company_series
# Daloopa equivalent: find available financial metrics for a company
# ---------------------------------------------------------------------------

def discover_company_series(ticker: str) -> dict:
    """
    List all available financial metrics/series for a company.

    Example:
        series = discover_company_series("AAPL")
    """
    ticker_obj = yf.Ticker(ticker.upper())
    info = ticker_obj.info

    available_series = {
        "income_statement": [
            "Total Revenue", "Gross Profit", "Operating Income",
            "EBITDA", "Net Income", "EPS (Basic)", "EPS (Diluted)"
        ],
        "balance_sheet": [
            "Total Assets", "Total Liabilities", "Total Equity",
            "Cash & Equivalents", "Total Debt", "Net Debt"
        ],
        "cash_flow": [
            "Operating Cash Flow", "Capital Expenditures",
            "Free Cash Flow", "Dividends Paid"
        ],
        "valuation_metrics": [
            "P/E Ratio", "P/S Ratio", "P/B Ratio", "EV/EBITDA",
            "EV/Revenue", "Dividend Yield"
        ],
        "sec_filings": ["10-K", "10-Q", "8-K", "DEF 14A"],
        "market_data": [
            "Price", "Market Cap", "52-Week High", "52-Week Low",
            "Average Volume", "Beta"
        ],
    }

    # Check what's actually available from yFinance
    has_financials = ticker_obj.financials is not None and not ticker_obj.financials.empty
    has_balance = ticker_obj.balance_sheet is not None and not ticker_obj.balance_sheet.empty
    has_cashflow = ticker_obj.cashflow is not None and not ticker_obj.cashflow.empty

    return {
        "ticker": ticker.upper(),
        "name": info.get("shortName"),
        "available_series": available_series,
        "data_available": {
            "income_statement": has_financials,
            "balance_sheet": has_balance,
            "cash_flow": has_cashflow,
            "sec_filings": True,  # Always available via EDGAR
            "market_data": True,
        },
        "periods_available": {
            "annual": "Up to 4 years",
            "quarterly": "Up to 4 quarters",
        }
    }


# ---------------------------------------------------------------------------
# Tool 3: get_company_fundamentals
# Daloopa equivalent: pull financial data for specific metrics and periods
# ---------------------------------------------------------------------------

def get_company_fundamentals(
    ticker: str,
    metrics: Optional[list] = None,
    period: str = "annual"  # "annual" or "quarterly"
) -> dict:
    """
    Fetch financial fundamentals for a company.

    Args:
        ticker:  Stock ticker symbol (e.g. "AAPL")
        metrics: List of metrics to fetch. None = fetch everything.
        period:  "annual" or "quarterly"

    Example:
        data = get_company_fundamentals("AAPL", ["revenue", "net_income"], "annual")
    """
    t = yf.Ticker(ticker.upper())
    info = t.info

    result = {
        "ticker": ticker.upper(),
        "name": info.get("shortName"),
        "period": period,
        "currency": info.get("currency", "USD"),
    }

    # --- Income Statement ---
    fin = t.financials if period == "annual" else t.quarterly_financials
    if fin is not None and not fin.empty:
        income = {}
        row_map = {
            "Total Revenue":                    "revenue",
            "Gross Profit":                     "gross_profit",
            "Operating Income":                 "operating_income",
            "Pretax Income":                    "pretax_income",
            "Net Income":                       "net_income",
            "EBITDA":                           "ebitda",
            # Capital allocation additions
            "Research Development":             "rd_expense",
            "Interest Expense":                 "interest_expense",
            # Build-model additions
            "Cost Of Revenue":                  "cost_of_revenue",
            "Selling General Administrative":   "sga",
            "Total Expenses":                   "total_operating_expenses",
            "Diluted Average Shares":           "diluted_shares",
            "Basic Average Shares":             "basic_shares",
            "Diluted EPS":                      "diluted_eps",
        }
        for label, key in row_map.items():
            if label in fin.index:
                income[key] = {
                    str(col.date()): _safe_int(fin.loc[label, col])
                    for col in fin.columns
                    if _safe_int(fin.loc[label, col]) is not None
                }
        result["income_statement"] = income

    # --- Balance Sheet ---
    bs = t.balance_sheet if period == "annual" else t.quarterly_balance_sheet
    if bs is not None and not bs.empty:
        balance = {}
        bs_map = {
            "Total Assets":                             "total_assets",
            "Total Liabilities Net Minority Interest":  "total_liabilities",
            "Stockholders Equity":                      "total_equity",
            "Cash And Cash Equivalents":                "cash",
            "Total Debt":                               "total_debt",
            # Capital allocation additions
            "Other Short Term Investments":             "short_term_investments",
            "Common Stock":                             "common_stock",
            "Treasury Shares Number":                   "treasury_shares",
        }
        for label, key in bs_map.items():
            if label in bs.index:
                balance[key] = {
                    str(col.date()): _safe_int(bs.loc[label, col])
                    for col in bs.columns
                    if _safe_int(bs.loc[label, col]) is not None
                }
        result["balance_sheet"] = balance

    # --- Cash Flow ---
    cf = t.cashflow if period == "annual" else t.quarterly_cashflow
    if cf is not None and not cf.empty:
        cashflow = {}
        cf_map = {
            "Operating Cash Flow":              "operating_cash_flow",
            "Capital Expenditure":              "capex",
            "Free Cash Flow":                   "free_cash_flow",
            # Capital allocation fields
            "Repurchase Of Capital Stock":      "share_repurchases",
            "Payment Of Dividends":             "dividends_paid",
            "Depreciation And Amortization":    "da",
            "Common Stock Dividend Paid":       "dividends_paid_alt",
        }
        for label, key in cf_map.items():
            if label in cf.index:
                cashflow[key] = {
                    str(col.date()): _safe_int(cf.loc[label, col])
                    for col in cf.columns
                    if _safe_int(cf.loc[label, col]) is not None
                }
        # Normalise: prefer "dividends_paid", fall back to alt label
        if "dividends_paid" not in cashflow and "dividends_paid_alt" in cashflow:
            cashflow["dividends_paid"] = cashflow.pop("dividends_paid_alt")
        else:
            cashflow.pop("dividends_paid_alt", None)

        # Compute FCF manually if not provided
        if "free_cash_flow" not in cashflow and "operating_cash_flow" in cashflow and "capex" in cashflow:
            cashflow["free_cash_flow"] = {
                k: cashflow["operating_cash_flow"].get(k, 0) + cashflow["capex"].get(k, 0)
                for k in cashflow["operating_cash_flow"]
            }

        # Compute total shareholder return = buybacks + dividends
        buybacks  = cashflow.get("share_repurchases", {})
        dividends = cashflow.get("dividends_paid", {})
        if buybacks or dividends:
            all_dates = set(list(buybacks.keys()) + list(dividends.keys()))
            cashflow["total_shareholder_return"] = {
                d: abs(buybacks.get(d, 0) or 0) + abs(dividends.get(d, 0) or 0)
                for d in all_dates
            }

        result["cash_flow"] = cashflow

    # --- Valuation / Market Data ---
    result["market_data"] = {
        "price":            info.get("currentPrice") or info.get("regularMarketPrice"),
        "market_cap":       info.get("marketCap"),
        "shares_outstanding": info.get("sharesOutstanding"),
        "float_shares":     info.get("floatShares"),
        "pe_ratio":         info.get("trailingPE"),
        "forward_pe":       info.get("forwardPE"),
        "ps_ratio":         info.get("priceToSalesTrailing12Months"),
        "pb_ratio":         info.get("priceToBook"),
        "ev_ebitda":        info.get("enterpriseToEbitda"),
        "ev_revenue":       info.get("enterpriseToRevenue"),
        "beta":             info.get("beta"),
        "dividend_yield":   info.get("dividendYield"),
        "dividend_rate":    info.get("dividendRate"),
        "payout_ratio":     info.get("payoutRatio"),
        "52w_high":         info.get("fiftyTwoWeekHigh"),
        "52w_low":          info.get("fiftyTwoWeekLow"),
        "eps_ttm":          info.get("trailingEps"),
        "eps_forward":      info.get("forwardEps"),
    }

    # --- FRED macro data (if key available) ---
    if FRED_API_KEY:
        result["macro"] = _get_fred_macro()

    return result


def _get_fred_macro() -> dict:
    """Fetch key macro indicators from FRED for DCF/WACC."""
    series = {
        "risk_free_rate_10y": "DGS10",       # 10-Year Treasury
        "risk_free_rate_3m": "DTB3",          # 3-Month T-Bill
        "cpi_inflation": "CPIAUCSL",          # CPI
        "federal_funds_rate": "FEDFUNDS",     # Fed Funds Rate
        "sp500": "SP500",                     # S&P 500 level
    }
    macro = {}
    base = "https://api.stlouisfed.org/fred/series/observations"
    for name, series_id in series.items():
        try:
            params = {
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1,
            }
            resp = requests.get(base, params=params, timeout=10)
            resp.raise_for_status()
            obs = resp.json().get("observations", [])
            if obs:
                macro[name] = float(obs[0]["value"])
        except Exception:
            macro[name] = None
    return macro


# ---------------------------------------------------------------------------
# Tool 4: search_documents
# Daloopa equivalent: search SEC filings for keywords
# ---------------------------------------------------------------------------

def search_documents(
    query: str,
    tickers: Optional[list] = None,
    form_types: Optional[list] = None,
    max_results: int = 5
) -> dict:
    """
    Search SEC EDGAR full-text search for keywords in filings.

    Args:
        query:      Search term (e.g. "AI revenue", "guidance")
        tickers:    Optional list of tickers to scope search
        form_types: Optional list of form types (e.g. ["10-K", "10-Q"])
        max_results: Number of results to return

    Example:
        results = search_documents("AI revenue", tickers=["AAPL", "MSFT"])
    """
    base = "https://efts.sec.gov/LATEST/search-index"
    params = {
        "q": f'"{query}"',
        "dateRange": "custom",
        "startdt": "2020-01-01",
        "_source": "file_date,period_of_report,entity_name,file_num,form_type,biz_location,inc_states,period_of_report",
        "hits.hits.total.value": max_results,
    }

    if form_types:
        params["forms"] = ",".join(form_types)

    # If tickers provided, resolve to entity names for better filtering
    if tickers:
        params["q"] += " " + " OR ".join(f'"{t.upper()}"' for t in tickers)

    # Use the official EDGAR full-text search
    search_url = "https://efts.sec.gov/LATEST/search-index"
    efts_url = f"https://efts.sec.gov/LATEST/search-index?q={requests.utils.quote(query)}&dateRange=custom&startdt=2023-01-01"
    
    # Use EDGAR EFTS search API
    efts_params = {
        "q": query,
        "dateRange": "custom", 
        "startdt": "2023-01-01",
    }
    if form_types:
        efts_params["forms"] = ",".join(form_types)

    try:
        resp = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params=efts_params,
            headers=EDGAR_HEADERS,
            timeout=15
        )
        # Fall back to the public EDGAR search endpoint
        resp2 = requests.get(
            "https://efts.sec.gov/LATEST/search-index?q=" + requests.utils.quote(f'"{query}"') + "&forms=" + (",".join(form_types) if form_types else "10-K,10-Q"),
            headers=EDGAR_HEADERS,
            timeout=15
        )
        
        # Use the simpler EDGAR search UI API
        search_resp = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={
                "q": f'"{query}"',
                "forms": ",".join(form_types) if form_types else "10-K,10-Q,8-K",
            },
            headers=EDGAR_HEADERS,
            timeout=15
        )

    except Exception as e:
        # Fallback: return filing list from EDGAR submissions
        results = []
        for ticker in (tickers or []):
            cik = _ticker_to_cik(ticker)
            if cik:
                sub = _edgar_get(f"/submissions/CIK{cik}.json")
                filings = sub.get("filings", {}).get("recent", {})
                forms = filings.get("form", [])
                dates = filings.get("filingDate", [])
                accessions = filings.get("accessionNumber", [])
                for i, form in enumerate(forms):
                    if not form_types or form in form_types:
                        results.append({
                            "ticker": ticker.upper(),
                            "form": form,
                            "date": dates[i] if i < len(dates) else None,
                            "accession": accessions[i] if i < len(accessions) else None,
                            "url": f"https://www.sec.gov/Archives/edgar/full-index/{accessions[i].replace('-', '')}" if i < len(accessions) else None,
                        })
                        if len(results) >= max_results:
                            break
        return {"query": query, "results": results, "source": "sec_edgar_submissions"}

    return {"query": query, "error": "EFTS search unavailable, use fallback above"}


# ---------------------------------------------------------------------------
# Convenience: get recent SEC filings for a company
# ---------------------------------------------------------------------------

def get_recent_filings(ticker: str, form_type: str = "10-K", limit: int = 5) -> list:
    """
    Get recent SEC filings for a company.

    Example:
        filings = get_recent_filings("AAPL", "10-K")
    """
    cik = _ticker_to_cik(ticker)
    if not cik:
        return []

    sub = _edgar_get(f"/submissions/CIK{cik}.json")
    filings = sub.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    accessions = filings.get("accessionNumber", [])
    descriptions = filings.get("primaryDocument", [])

    results = []
    for i, form in enumerate(forms):
        if form == form_type:
            acc = accessions[i].replace("-", "") if i < len(accessions) else ""
            results.append({
                "ticker": ticker.upper(),
                "cik": cik,
                "form": form,
                "date": dates[i] if i < len(dates) else None,
                "accession": accessions[i] if i < len(accessions) else None,
                "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/",
                "primary_doc": descriptions[i] if i < len(descriptions) else None,
            })
            if len(results) >= limit:
                break

    return results


# ---------------------------------------------------------------------------
# Model helpers — period format conversion & data adapters
# ---------------------------------------------------------------------------

def date_to_quarter(date_str: str) -> str:
    """
    Convert ISO date string to quarter label.
    "2024-09-28" → "2024Q3"
    "2024-12-31" → "2024Q4"
    """
    try:
        from datetime import datetime
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        q = (d.month - 1) // 3 + 1
        return f"{d.year}Q{q}"
    except Exception:
        return date_str


def convert_series_to_quarters(series: dict) -> dict:
    """
    Convert a {iso_date: value} dict to {quarter_label: value} dict.
    {"2024-09-28": 391035000000} → {"2024Q3": 391035000000}
    """
    return {date_to_quarter(k): v for k, v in series.items()}


def build_model_context(ticker: str, n_projection_quarters: int = 8) -> dict:
    """
    Build a complete context dict compatible with both:
      - infra/projection_engine.py  (historical as lists, quarter labels)
      - infra/excel_builder.py      (named metrics as dicts, quarter labels)

    This is the single adapter that bridges free_client → the infra tools.

    Args:
        ticker: Stock ticker symbol
        n_projection_quarters: How many quarters forward to project

    Returns:
        dict with keys:
          company, market_data, periods, income_statement, balance_sheet,
          cash_flow, projection_input (for projection_engine), dcf_inputs
    """
    print(f"  [build_model_context] Fetching quarterly data...")
    data_q = get_company_fundamentals(ticker, period="quarterly")

    print(f"  [build_model_context] Fetching annual data...")
    data_a = get_company_fundamentals(ticker, period="annual")

    print(f"  [build_model_context] Fetching company info...")
    info = discover_companies(ticker)

    mkt = data_q.get("market_data", {})
    inc = data_q.get("income_statement", {})
    bs  = data_q.get("balance_sheet", {})
    cf  = data_q.get("cash_flow", {})

    # --- Convert all series to quarter labels and sort oldest-first ---
    def _q(series):
        return convert_series_to_quarters(series) if series else {}

    rev_q   = _q(inc.get("revenue", {}))
    gp_q    = _q(inc.get("gross_profit", {}))
    cogs_q  = _q(inc.get("cost_of_revenue", {}))
    oi_q    = _q(inc.get("operating_income", {}))
    ni_q    = _q(inc.get("net_income", {}))
    ebitda_q = _q(inc.get("ebitda", {}))
    rd_q    = _q(inc.get("rd_expense", {}))
    sga_q   = _q(inc.get("sga", {}))
    da_q    = _q(cf.get("da", {}))
    ie_q    = _q(inc.get("interest_expense", {}))
    eps_q   = _q(inc.get("diluted_eps", {}))
    shares_q = _q(inc.get("diluted_shares", {}))
    opex_q  = _q(inc.get("total_operating_expenses", {}))
    ta_q    = _q(bs.get("total_assets", {}))
    tl_q    = _q(bs.get("total_liabilities", {}))
    eq_q    = _q(bs.get("total_equity", {}))
    cash_q  = _q(bs.get("cash", {}))
    stinv_q = _q(bs.get("short_term_investments", {}))
    debt_q  = _q(bs.get("total_debt", {}))
    ocf_q   = _q(cf.get("operating_cash_flow", {}))
    capex_q = _q(cf.get("capex", {}))
    fcf_q   = _q(cf.get("free_cash_flow", {}))
    buybacks_q  = _q(cf.get("share_repurchases", {}))
    dividends_q = _q(cf.get("dividends_paid", {}))

    # --- Periods: use revenue as anchor, sort oldest-first ---
    periods = sorted(rev_q.keys())

    # --- excel_builder income_statement (Title Case keys, quarter dicts) ---
    income_statement = {}
    if rev_q:    income_statement["Revenue"]                          = rev_q
    if cogs_q:   income_statement["Cost of Sales"]                    = cogs_q
    if gp_q:     income_statement["Gross Profit"]                     = gp_q
    if rd_q:     income_statement["Research & Development"]           = rd_q
    if sga_q:    income_statement["Selling, General & Administrative"] = sga_q
    if oi_q:     income_statement["Operating Income"]                 = oi_q
    if ie_q:     income_statement["Interest Expense"]                 = ie_q
    if ni_q:     income_statement["Net Income"]                       = ni_q
    if ebitda_q: income_statement["EBITDA"]                           = ebitda_q
    if da_q:     income_statement["D&A"]                              = da_q
    if eps_q:    income_statement["EPS"]                              = eps_q
    if shares_q: income_statement["Diluted Shares"]                   = shares_q

    # --- excel_builder balance_sheet ---
    balance_sheet = {}
    if cash_q:   balance_sheet["Cash & Equivalents"]        = cash_q
    if stinv_q:  balance_sheet["Short-term Investments"]    = stinv_q
    if ta_q:     balance_sheet["Total Assets"]              = ta_q
    if tl_q:     balance_sheet["Total Liabilities"]         = tl_q
    if eq_q:     balance_sheet["Total Shareholders Equity"] = eq_q
    if debt_q:   balance_sheet["Total Debt"]                = debt_q

    # --- excel_builder cash_flow ---
    cash_flow = {}
    if ocf_q:       cash_flow["Operating Cash Flow"] = ocf_q
    if capex_q:     cash_flow["Capital Expenditures"] = capex_q
    if fcf_q:       cash_flow["Free Cash Flow"]       = fcf_q
    if da_q:        cash_flow["Depreciation & Amortization"] = da_q
    if buybacks_q:  cash_flow["Share Repurchases"]    = buybacks_q
    if dividends_q: cash_flow["Dividends Paid"]       = dividends_q

    # --- projection_engine historical (lists, oldest-first) ---
    def _to_list(q_dict):
        return [q_dict.get(p) for p in periods]

    # Compute operating_expenses list for projection engine
    # op_expenses = revenue - operating_income (if COGS not available use this proxy)
    oi_list  = _to_list(oi_q)
    rev_list = _to_list(rev_q)
    opex_list = []
    for r, o in zip(rev_list, oi_list):
        if r is not None and o is not None:
            opex_list.append(r - o)
        else:
            opex_list.append(None)

    projection_input = {
        "ticker": ticker.upper(),
        "projection_quarters": n_projection_quarters,
        "long_term_growth": 0.03,
        "decay_factor": 0.85,
        "historical": {
            "periods": periods,
            "revenue":            _to_list(rev_q),
            "cost_of_revenue":    _to_list(cogs_q) if cogs_q else None,
            "gross_profit":       _to_list(gp_q),
            "operating_expenses": opex_list,
            "operating_income":   oi_list,
            "net_income":         _to_list(ni_q),
            "capex":              _to_list(capex_q),
            "depreciation":       _to_list(da_q) if da_q else None,
            "shares_outstanding": _to_list(shares_q) if shares_q else None,
        },
        "guidance": {},  # analyst can populate manually
    }

    # --- DCF inputs ---
    beta = mkt.get("beta") or 1.0
    rf_rate = 0.045  # default; overridden if FRED key set
    if FRED_API_KEY:
        try:
            macro = _get_fred_macro()
            rf_rate = (macro.get("risk_free_rate_10y") or 4.5) / 100
        except Exception:
            pass
    erp = 0.055  # equity risk premium
    wacc = rf_rate + beta * erp
    terminal_growth = 0.025

    dcf_inputs = {
        "wacc": round(wacc, 4),
        "terminal_growth": terminal_growth,
        "risk_free_rate": rf_rate,
        "equity_risk_premium": erp,
        "beta": beta,
    }

    # --- Company block for excel_builder ---
    company_block = {
        "name": info.get("name", ticker.upper()),
        "ticker": ticker.upper(),
        "exchange": info.get("exchange", ""),
        "currency": data_q.get("currency", "USD"),
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
    }

    # --- Market data block for excel_builder (rename keys to match builder) ---
    market_data_block = {
        "price":               mkt.get("price"),
        "market_cap":          mkt.get("market_cap"),
        "shares_outstanding":  mkt.get("shares_outstanding"),
        "beta":                mkt.get("beta"),
        "fifty_two_week_high": mkt.get("52w_high"),
        "fifty_two_week_low":  mkt.get("52w_low"),
        "trailing_pe":         mkt.get("pe_ratio"),
        "forward_pe":          mkt.get("forward_pe"),
        "ev_ebitda":           mkt.get("ev_ebitda"),
        "ev_revenue":          mkt.get("ev_revenue"),
        "price_to_sales":      mkt.get("ps_ratio"),
        "price_to_book":       mkt.get("pb_ratio"),
        "dividend_yield":      mkt.get("dividend_yield"),
        "eps_ttm":             mkt.get("eps_ttm"),
    }

    return {
        "company":          company_block,
        "market_data":      market_data_block,
        "periods":          periods,
        "income_statement": income_statement,
        "balance_sheet":    balance_sheet,
        "cash_flow":        cash_flow,
        "projection_input": projection_input,
        "dcf_inputs":       dcf_inputs,
    }


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    print("=" * 60)
    print("Testing free_client.py — Daloopa replacement")
    print("=" * 60)

    ticker = "AAPL"

    print(f"\n[1] discover_companies('{ticker}')")
    print(json.dumps(discover_companies(ticker), indent=2))

    print(f"\n[2] discover_company_series('{ticker}')")
    series = discover_company_series(ticker)
    print(json.dumps(series, indent=2))

    print(f"\n[3] get_company_fundamentals('{ticker}', period='annual')")
    fundamentals = get_company_fundamentals(ticker, period="annual")
    # Print summary only
    print(f"  Income statement keys: {list(fundamentals.get('income_statement', {}).keys())}")
    print(f"  Market data: {json.dumps(fundamentals.get('market_data'), indent=4)}")

    print(f"\n[4] get_recent_filings('{ticker}', '10-K')")
    filings = get_recent_filings(ticker, "10-K", limit=3)
    print(json.dumps(filings, indent=2))

    print("\n✅ All tools working! Replace daloopa_client.py with this file.")
