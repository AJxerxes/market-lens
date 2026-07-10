"""
Tracked funds & 13F positions (Phase 20).

Responsibilities:
- Maintain a small set of high-conviction / thematic funds in `tracked_funds`.
- Discover their CIKs via SEC search-index.
- Ingest historical 13F-HR filings and store positions in `fund_positions`.
- Compute quarter-over-quarter deltas in `fund_position_delta`.
- Ingest ARK Invest daily trade history into `ark_daily_trades`.
- Provide raw inputs for agent brain synthesis and convergence analysis.

This module focuses on ingestion and bookkeeping. The agent brain
handles reasoning and alerting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, List, Optional

import csv
import io
import re

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from market_lens import config
from market_lens.database.models import (
    TrackedFund,
    FundPosition,
    FundPositionDelta,
    ArkDailyTrade,
)


_engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=_engine)

EDGAR_SEARCH_INDEX_URL = "https://efts.sec.gov/LATEST/search-index"
ARK_TRADE_HISTORY_URL = "https://ark-funds.com/trade-history"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_session() -> Session:
    return SessionLocal()


def _edgar_session() -> requests.Session:
    s = requests.Session()
    # Per spec: every EDGAR request must carry this User-Agent
    s.headers.update({"User-Agent": config.EDGAR_USER_AGENT})
    return s


@dataclass
class CIKSearchResult:
    cik: str
    name: str


def discover_cik_for_fund(fund_name: str) -> Optional[CIKSearchResult]:
    """
    Use SEC search-index to discover a fund's CIK from its legal name.

    This is a best-effort helper; some funds may require manual CIK entry.
    """
    session = _edgar_session()
    params = {
        "q": f"\"{fund_name}\"",
        "forms": "13F-HR",
    }
    resp = session.get(EDGAR_SEARCH_INDEX_URL, params=params, timeout=15)
    if resp.status_code != 200:
        return None

    try:
        data = resp.json()
    except Exception:
        return None

    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        return None

    # Pick the first hit; refine later if needed.
    hit = hits[0].get("_source", {})
    cik = str(hit.get("cik") or "").lstrip("0")
    name = hit.get("entityName") or fund_name
    if not cik:
        return None

    return CIKSearchResult(cik=cik, name=name)


def ensure_tracked_funds_seeded() -> None:
    """
    Ensure core tracked funds exist in `tracked_funds`.

    Names and thesis notes are per spec; CIKs can be discovered
    automatically via `discover_cik_for_fund` or filled manually.
    """
    default_funds = [
        "Situational Awareness LP",
        "Pershing Square Capital Management",
        "Coatue Management",
        "Tiger Global Management",
        "ARK Invest",
    ]

    session = _get_session()
    try:
        for name in default_funds:
            existing = session.query(TrackedFund).filter_by(name=name).first()
            if existing:
                continue

            tracked = TrackedFund(
                name=name,
                cik=None,
                fund_type="hedge_fund" if "ARK" not in name else "etf_family",
                thesis_notes=None,
                active=True,
            )
            session.add(tracked)

        session.commit()
    finally:
        session.close()


FMP_BASE = "https://financialmodelingprep.com"


def _fmp_get(path: str, params: Optional[dict] = None) -> Optional[list]:
    if not config.FMP_API_KEY:
        return None
    params = dict(params or {})
    params.setdefault("apikey", config.FMP_API_KEY)
    try:
        r = requests.get(f"{FMP_BASE}{path}", params=params, timeout=20)
        if r.status_code != 200:
            return None
        data = r.json()
        return data if isinstance(data, list) else None
    except Exception:
        return None


def ingest_13f_positions_for_fund(fund: TrackedFund) -> None:
    """
    Ingest 13F positions via FMP form-thirteen API (when API key has access).
    Fallback: no-op if no CIK or FMP returns nothing.
    """
    cik = (fund.cik or "").strip().lstrip("0") or None
    if not cik:
        return
    # FMP: /api/v4/form_thirteen?cik= or similar
    data = _fmp_get("/api/v4/form_thirteen", params={"cik": cik})
    if not data:
        return
    session = _get_session()
    try:
        for item in data[:500]:
            ticker = (item.get("ticker") or item.get("symbol") or "").upper()
            if not ticker or len(ticker) > 20:
                continue
            report_date = item.get("reportDate") or item.get("filingDate")
            if report_date and len(str(report_date)) >= 10:
                try:
                    as_of = date.fromisoformat(str(report_date)[:10])
                except ValueError:
                    as_of = _utc_now().date()
            else:
                as_of = _utc_now().date()
            quarter = f"{as_of.year}Q{(as_of.month - 1) // 3 + 1}"
            shares = float(item.get("shares") or item.get("value") or 0)
            market_value = float(item.get("value") or item.get("marketValue") or 0)
            existing = (
                session.query(FundPosition)
                .filter_by(fund_id=fund.id, ticker=ticker, quarter=quarter)
                .first()
            )
            if not existing:
                session.add(
                    FundPosition(
                        fund_id=fund.id,
                        ticker=ticker,
                        company_name=item.get("companyName") or item.get("name"),
                        quarter=quarter,
                        shares=shares,
                        market_value=market_value,
                        form_type="13F-HR",
                        accession_number=item.get("accessionNumber"),
                        as_of_date=as_of,
                    )
                )
        session.commit()
    finally:
        session.close()


def recompute_fund_position_deltas(fund: TrackedFund) -> None:
    """
    Placeholder for computing quarter-over-quarter deltas.

    A full implementation would:
    - Group FundPosition rows by quarter.
    - Compare current vs previous quarters to detect added/exited/increased/decreased.
    - Write results into FundPositionDelta.
    """
    # TODO: Implement fund position delta logic.
    return


def ingest_ark_daily_trades() -> None:
    """
    Parse ARK's daily trade history CSV.

    The ARK site exposes daily trades as downloadable CSV(s).
    This function fetches the page, finds CSV links, downloads
    the most recent file(s), and populates `ark_daily_trades`.
    """
    resp = requests.get(ARK_TRADE_HISTORY_URL, timeout=15)
    if resp.status_code != 200:
        return

    # Many implementations expose a direct CSV link via an <a> tag.
    # Here we extract any .csv URL from the HTML as a simple heuristic.
    csv_urls = set(re.findall(r"https?://[^\s\"']+\\.csv", resp.text))
    if not csv_urls:
        return

    session_db = _get_session()
    try:
        for url in csv_urls:
            csv_resp = requests.get(url, timeout=15)
            if csv_resp.status_code != 200:
                continue

            try:
                text = csv_resp.text
                reader = csv.DictReader(io.StringIO(text))
            except Exception:
                continue

            for row in reader:
                try:
                    trade_date = _parse_date(row.get("date") or row.get("Date"))
                    ticker = (row.get("ticker") or row.get("Ticker") or "").upper()
                    fund_name = row.get("fund") or row.get("Fund") or "ARK"
                    company_name = row.get("company") or row.get("Company")
                    direction = (row.get("direction") or row.get("Direction") or "").lower()
                    shares = float(row.get("shares") or row.get("Shares") or 0)
                    notional = float(row.get("value") or row.get("Value") or 0)
                except Exception:
                    continue

                large_flag = notional > 10_000_000

                trade = ArkDailyTrade(
                    trade_date=trade_date or _utc_now().date(),
                    fund_name=fund_name,
                    ticker=ticker,
                    company_name=company_name,
                    direction=direction,
                    shares=shares,
                    notional_value=notional,
                    large_trade_flag=large_flag,
                    raw_source_url=url,
                )
                session_db.add(trade)

        session_db.commit()
    finally:
        session_db.close()


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except Exception:
            continue
    return None


def run_tracked_funds_ingestion() -> None:
    """
    High-level entry point for APScheduler:
    - Ensure default tracked funds exist.
    - Discover / confirm CIKs where missing.
    - Ingest or refresh 13F positions.
    - Recompute position deltas.
    - Ingest ARK daily trades.
    """
    ensure_tracked_funds_seeded()

    session = _get_session()
    try:
        funds: List[TrackedFund] = session.query(TrackedFund).filter_by(active=True).all()

        # Discover CIKs for funds that lack them.
        for fund in funds:
            if not fund.cik:
                result = discover_cik_for_fund(fund.name)
                if result:
                    fund.cik = result.cik
                    if not fund.thesis_notes:
                        fund.thesis_notes = f"Tracked fund discovered via EDGAR search-index: {result.name}"

        session.commit()
        fund_ids = [f.id for f in funds]
    finally:
        session.close()

    # EDGAR-intensive operations can run outside the DB session.
    for fund_id in fund_ids:
        session2 = _get_session()
        try:
            fund = session2.query(TrackedFund).filter_by(id=fund_id).first()
            if fund:
                ingest_13f_positions_for_fund(fund)
                recompute_fund_position_deltas(fund)
        finally:
            session2.close()

    # ARK trades can be ingested daily.
    ingest_ark_daily_trades()


if __name__ == "__main__":
    print("Market Lens — Tracked Funds")
    print("---------------------------")
    run_tracked_funds_ingestion()
    print("[OK] Tracked funds ingestion done.")
