"""
Debt maturity schedule ingestion via EDGAR XBRL API.
Uses structured LongTermDebtMaturities XBRL facts — no HTML parsing.
Values are in USD, converted to millions for storage.
"""
import time
from datetime import date
from typing import Optional, List, Dict

import requests

from market_lens.database.models import Company
from market_lens.ingestion.tracked_funds import _get_session
from market_lens.ingestion.edgar import _get_cik_for_ticker, _rate_limit

EDGAR_HEADERS = {
    "User-Agent": "MarketLens/1.0 (compliance; omniaj@aol.com)",
    "Accept-Encoding": "gzip, deflate",
}

XBRL_MATURITY_KEYS = [
    "LongTermDebtMaturitiesRepaymentsOfPrincipalRemainderOfFiscalYear",
    "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",
    "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo",
    "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree",
    "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour",
    "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive",
    "LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive",
]

YEAR_OFFSETS = {
    "RemainderOfFiscalYear": 0,
    "InNextTwelveMonths": 1,
    "InYearTwo": 2,
    "InYearThree": 3,
    "InYearFour": 4,
    "InYearFive": 5,
    "AfterYearFive": 6,
}


def _fetch_xbrl_facts(cik: int) -> Optional[Dict]:
    cik_padded = str(cik).zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    try:
        r = requests.get(url, headers=EDGAR_HEADERS, timeout=30)
        _rate_limit()
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _extract_debt_maturities_xbrl(facts: Dict, ticker: str) -> List[Dict]:
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        return []

    current_year = date.today().year

    latest_accn = None
    latest_end = ""
    latest_fy = None

    for key in XBRL_MATURITY_KEYS:
        entries = us_gaap.get(key, {}).get("units", {}).get("USD", [])
        for e in entries:
            if e.get("form") == "10-K" and e.get("end", "") > latest_end:
                latest_end = e.get("end", "")
                latest_accn = e.get("accn")
                latest_fy = e.get("fy")

    if not latest_accn or not latest_fy:
        return []

    results = []
    for key in XBRL_MATURITY_KEYS:
        entries = us_gaap.get(key, {}).get("units", {}).get("USD", [])
        match = next((e for e in entries if e.get("accn") == latest_accn), None)
        if not match:
            match = next(
                (e for e in entries if e.get("fy") == latest_fy and e.get("form") == "10-K"),
                None,
            )
        if not match:
            continue

        val = match.get("val")
        if val is None or val <= 0:
            continue

        suffix = next((s for s in YEAR_OFFSETS if key.endswith(s)), None)
        if suffix is None:
            continue

        offset = YEAR_OFFSETS[suffix]
        maturity_year = latest_fy + offset

        if maturity_year < current_year or maturity_year > current_year + 10:
            continue

        amount_millions = round(val / 1_000_000, 1)
        if amount_millions < 1:
            continue

        results.append({
            "ticker": ticker,
            "maturity_year": maturity_year,
            "amount_millions": amount_millions,
            "label": f"XBRL {key[-25:]} FY{latest_fy}",
            "source": "EDGAR XBRL",
        })

    by_year: Dict[int, Dict] = {}
    for r in results:
        yr = r["maturity_year"]
        if yr not in by_year or r["amount_millions"] > by_year[yr]["amount_millions"]:
            by_year[yr] = r

    return sorted(by_year.values(), key=lambda x: x["maturity_year"])


def ingest_debt_maturities(tickers: Optional[List[str]] = None) -> None:
    from market_lens.database.models import DebtMaturity

    session = _get_session()
    try:
        if tickers is None:
            companies = (
                session.query(Company)
                .filter_by(active=True, paused=False)
                .all()
            )
            tickers = [
                c.ticker
                for c in companies
                if str(c.instrument_type) not in ("InstrumentType.etf", "ETF")
            ]

        print(f"[DebtMaturity] Processing {len(tickers)} tickers via XBRL...")
        total_inserted = 0

        for ticker in tickers:
            db_session = _get_session()
            cik_session = _get_session()
            try:
                cik = _get_cik_for_ticker(cik_session, ticker)
            finally:
                cik_session.close()

            if not cik:
                print(f"[DebtMaturity] {ticker}: no CIK found")
                db_session.close()
                continue

            facts = _fetch_xbrl_facts(int(cik))
            if not facts:
                print(f"[DebtMaturity] {ticker}: XBRL fetch failed")
                db_session.close()
                continue

            maturities = _extract_debt_maturities_xbrl(facts, ticker)
            print(f"[DebtMaturity] {ticker}: {len(maturities)} maturity entries")

            try:
                for m in maturities:
                    existing = (
                        db_session.query(DebtMaturity)
                        .filter_by(ticker=ticker, maturity_year=m["maturity_year"])
                        .first()
                    )
                    if not existing:
                        db_session.add(DebtMaturity(**m))
                        total_inserted += 1
                    else:
                        existing.amount_millions = m["amount_millions"]
                        existing.label = m["label"]
                db_session.commit()
            except Exception as e:
                db_session.rollback()
                print(f"[DebtMaturity] {ticker}: DB error {e}")
            finally:
                db_session.close()

            time.sleep(0.5)

        print(f"[DebtMaturity] Complete — inserted: {total_inserted}")
    finally:
        session.close()
