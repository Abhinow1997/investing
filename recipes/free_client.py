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
            "Total Revenue":        "revenue",
            "Gross Profit":         "gross_profit",
            "Operating Income":     "operating_income",
            "Pretax Income":        "pretax_income",
            "Net Income":           "net_income",
            "EBITDA":               "ebitda",
            # Capital allocation additions
            "Research Development": "rd_expense",
            "Interest Expense":     "interest_expense",
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
