"""
Weekly sector scanner (Phase 18).

Runs every Saturday at 8pm ET via APScheduler:
- Scans all 11 GICS sectors.
- Pulls top 10 companies by market cap per sector (yfinance + FMP).
- Computes price, 1-week / 1-month / YTD returns, P/E, and YoY revenue growth.
- Stores results in `sector_scan_results`.
- Builds a Saturday digest and stores in `weekly_digest` (Claude Haiku will
  be wired in a later phase).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import yfinance as yf
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_lens.config import DATABASE_URL
from market_lens.database.models import SectorScanResult, WeeklyDigest, Company


_engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=_engine)


GICS_SECTORS: List[str] = [
    "Information Technology",
    "Health Care",
    "Financials",
    "Consumer Discretionary",
    "Communication Services",
    "Industrials",
    "Consumer Staples",
    "Energy",
    "Utilities",
    "Real Estate",
    "Materials",
]


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


@dataclass
class SectorConstituent:
    ticker: str
    name: str
    sector: str
    market_cap: float


def _get_top_constituents_for_sector(
    session,
    sector: str,
    limit: int = 10,
) -> List[SectorConstituent]:
    """
    Use watchlist companies whose sector matches; fallback to all active watchlist
    if no sector match. FMP sector universe can be added later.
    """
    from sqlalchemy import or_
    q = session.query(Company).filter(Company.active == True)
    # Match sector or industry (some DBs have sector, some industry)
    q = q.filter(or_(Company.sector == sector, Company.industry == sector))
    companies = q.order_by(Company.market_cap.desc().nullslast()).limit(limit).all()
    if not companies:
        q2 = session.query(Company).filter(Company.active == True).order_by(Company.market_cap.desc().nullslast()).limit(limit)
        companies = q2.all()
    return [
        SectorConstituent(
            ticker=c.ticker,
            name=c.name or c.ticker,
            sector=sector,
            market_cap=float(c.market_cap or 0),
        )
        for c in companies
    ]


def _is_hidden_giant(price: float, pe_ratio: float, market_cap: float, week_return: float) -> bool:
    """Simple hidden-giant flag: small-to-mid cap with positive momentum or reasonable P/E."""
    if market_cap <= 0 or price <= 0:
        return False
    # Cap < 50B and (positive week return or P/E in 10-25 range)
    if market_cap > 50e9:
        return False
    return week_return > 0 or (pe_ratio and 10 <= pe_ratio <= 25)


def _compute_returns(hist) -> tuple[float, float, float]:
    """
    Compute weekly, monthly, and YTD returns from a yfinance history DataFrame.
    Returns (week_return, month_return, ytd_return) as percentages.
    """
    if hist is None or hist.empty:
        return 0.0, 0.0, 0.0

    latest = hist["Close"].iloc[-1]

    def pct_return(days: int) -> float:
        if len(hist) < days + 1:
            return 0.0
        past = hist["Close"].iloc[-(days + 1)]
        return (latest - past) / past * 100.0 if past else 0.0

    week_ret = pct_return(5)
    month_ret = pct_return(21)

    # YTD: compare to first close of the calendar year
    try:
        year_start = hist[hist.index.year == datetime.now().year]["Close"].iloc[0]
        ytd_ret = (latest - year_start) / year_start * 100.0 if year_start else 0.0
    except Exception:
        ytd_ret = 0.0

    return week_ret, month_ret, ytd_ret


def run_sector_scan(scan_date: Optional[date] = None) -> None:
    """
    Main entry point for the weekly sector scanner.

    This function is designed to be called by APScheduler in agent.py.
    """
    if scan_date is None:
        scan_date = _utc_today()

    session = SessionLocal()
    try:
        for sector in GICS_SECTORS:
            constituents = _get_top_constituents_for_sector(session, sector, limit=10)

            for rank, c in enumerate(constituents, start=1):
                yf_ticker = yf.Ticker(c.ticker)

                # Basic metrics from yfinance.info (may be partial for some instruments)
                info = yf_ticker.info or {}
                price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0.0)
                pe_ratio = float(info.get("trailingPE") or 0.0)

                # 1-year daily history for return calculations
                hist = yf_ticker.history(period="1y")
                week_ret, month_ret, ytd_ret = _compute_returns(hist)

                result = SectorScanResult(
                    scan_date=scan_date,
                    sector=sector,
                    ticker=c.ticker,
                    company_name=c.name,
                    market_cap=c.market_cap,
                    rank_in_sector=rank,
                    price=price,
                    week_return=week_ret,
                    month_return=month_ret,
                    ytd_return=ytd_ret,
                    pe_ratio=pe_ratio,
                    revenue_growth_yoy=0.0,  # To be populated from fundamentals module
                    analyst_consensus=None,
                    one_sentence_state=None,  # To be generated via Claude Haiku
                    hidden_giant_flag=_is_hidden_giant(price, pe_ratio, float(c.market_cap or 0), week_ret),
                    brand_awareness_ratio=0.0,
                )
                session.add(result)

        session.commit()

        # After writing raw results, generate and store a digest shell record.
        _create_weekly_digest_stub(session, scan_date)
        session.commit()
    finally:
        session.close()


def _create_weekly_digest_stub(session, scan_date: date) -> None:
    """
    Create a placeholder WeeklyDigest row for the given scan_date.

    In a later phase, this function will:
    - Query SectorScanResult.
    - Call Claude Haiku to generate sector summaries and hidden giant writeups.
    - Populate the JSON fields with structured summaries.
    """
    # Avoid duplicating digest for same day
    existing = session.query(WeeklyDigest).filter_by(digest_date=scan_date).first()
    if existing:
        return

    digest = WeeklyDigest(
        digest_date=scan_date,
        full_digest_text="Weekly sector digest placeholder. To be generated via Claude Haiku.",
        sector_summaries_json=None,
        hidden_giants_json=None,
        watchlist_suggestions_json=None,
        delivered_telegram=False,
    )
    session.add(digest)

