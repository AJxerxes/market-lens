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
from market_lens.database.models import (
    SectorScanResult,
    WeeklyDigest,
    Company,
    NewsSentiment,
    InsiderTransaction,
    CongressTrade,
    Score,
)


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


def to_float(val):
    """Convert to native Python float for PostgreSQL; avoids np.float64 schema error."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


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
                price = to_float(info.get("currentPrice") or info.get("regularMarketPrice") or 0.0)
                pe_ratio = to_float(info.get("trailingPE") or 0.0)

                # 1-year daily history for return calculations
                hist = yf_ticker.history(period="1y")
                week_ret, month_ret, ytd_ret = _compute_returns(hist)

                result = SectorScanResult(
                    scan_date=scan_date,
                    sector=sector,
                    ticker=c.ticker,
                    company_name=c.name,
                    market_cap=to_float(c.market_cap),
                    rank_in_sector=rank,
                    price=to_float(price),
                    week_return=to_float(week_ret),
                    month_return=to_float(month_ret),
                    ytd_return=to_float(ytd_ret),
                    pe_ratio=to_float(pe_ratio),
                    revenue_growth_yoy=to_float(0.0),  # To be populated from fundamentals module
                    analyst_consensus=None,
                    one_sentence_state=None,  # To be generated via Claude Haiku
                    hidden_giant_flag=_is_hidden_giant(float(price or 0), float(pe_ratio or 0), float(c.market_cap or 0), float(week_ret or 0)),
                    brand_awareness_ratio=to_float(0.0),
                )
                session.add(result)

        session.commit()

        # After writing raw results, generate and store a digest shell record.
        _create_weekly_digest_stub(session, scan_date)
        session.commit()
    finally:
        session.close()


def _create_weekly_digest_stub(session, scan_date: date) -> None:
    """Create a placeholder WeeklyDigest row for the given scan_date (digest_type=weekly)."""
    existing = session.query(WeeklyDigest).filter_by(
        digest_date=scan_date, digest_type="weekly", digest_time=None
    ).first()
    if existing:
        return
    digest = WeeklyDigest(
        digest_date=scan_date,
        digest_type="weekly",
        digest_time=None,
        full_digest_text="Weekly sector digest placeholder. To be generated via Claude Haiku.",
        sector_summaries_json=None,
        hidden_giants_json=None,
        watchlist_suggestions_json=None,
        delivered_telegram=False,
    )
    session.add(digest)


def run_daily_digest(slot: str = "morning") -> None:
    """
    Lightweight daily briefing at 7am or 7pm ET. Uses Claude Haiku.
    Gathers: last 24h news sentiment, Lynch score changes, new insider tx, substack posts, congressional trades.
    Stores in weekly_digest with digest_type='daily', digest_time=slot.
    """
    from market_lens.agent.llm_client import summarize_low_stakes
    from market_lens.database.models import SubstackPost

    session = SessionLocal()
    try:
        today = _utc_today()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        cutoff_d = cutoff.date()

        bullets: List[str] = []
        # News sentiment (last 24h)
        news_rows = (
            session.query(NewsSentiment)
            .filter(NewsSentiment.article_date >= cutoff_d)
            .limit(50)
            .all()
        )
        if news_rows:
            bullets.append(f"News: {len(news_rows)} articles in last 24h; sample sentiment scores available.")
        # New insider transactions
        insiders = (
            session.query(InsiderTransaction)
            .filter(InsiderTransaction.filing_date >= cutoff_d)
            .limit(30)
            .all()
        )
        if insiders:
            bullets.append(f"Insider: {len(insiders)} new filings in last 24h.")
        # New congressional trades
        trades = (
            session.query(CongressTrade)
            .filter(CongressTrade.disclosure_date >= cutoff_d)
            .limit(30)
            .all()
        )
        if trades:
            bullets.append(f"Congress: {len(trades)} new disclosures in last 24h.")
        # New substack posts today
        try:
            substack = (
                session.query(SubstackPost)
                .filter(SubstackPost.published_at >= cutoff)
                .limit(20)
                .all()
            )
            if substack:
                bullets.append(f"Substack: {len(substack)} new posts in last 24h.")
        except Exception:
            pass

        if not bullets:
            bullets = ["No significant activity in the last 24 hours."]

        context = "\n".join(bullets)
        system_prompt = (
            "You are an assistant that generates a brief market briefing in exactly 3 bullet points. "
            "For each bullet: name the specific company or sector, describe what happened, and state whether "
            "it is a positive, negative, or neutral signal. Be specific — no generic statements."
        )
        user_content = (
            f"Generate a brief {slot} market briefing in 3 bullet points based on this data:\n{context}"
        )
        try:
            full_text = summarize_low_stakes(system_prompt, user_content, max_tokens=400)
        except Exception as e:
            full_text = f"Briefing unavailable: {e}. Raw: {context}"

        existing = (
            session.query(WeeklyDigest)
            .filter_by(digest_date=today, digest_type="daily", digest_time=slot)
            .first()
        )
        if existing:
            existing.full_digest_text = full_text
        else:
            session.add(
                WeeklyDigest(
                    digest_date=today,
                    digest_type="daily",
                    digest_time=slot,
                    full_digest_text=full_text,
                    sector_summaries_json=None,
                    hidden_giants_json=None,
                    watchlist_suggestions_json=None,
                    delivered_telegram=False,
                )
            )
        session.commit()
    finally:
        session.close()


def run_weekly_digest() -> None:
    """
    Full weekly digest: sector scan + deep analysis. Uses Claude Sonnet.
    Runs Saturday 8pm ET. Stores with digest_type='weekly'.
    """
    from market_lens.agent.llm_client import synthesize_material_change

    run_sector_scan()
    today = _utc_today()
    session = SessionLocal()
    try:
        scans = (
            session.query(SectorScanResult)
            .filter(SectorScanResult.scan_date == today)
            .order_by(SectorScanResult.sector, SectorScanResult.rank_in_sector)
            .limit(200)
            .all()
        )
        context_lines = []
        for s in scans[:50]:
            context_lines.append(
                f"{s.sector} | {s.ticker} | {s.company_name} | cap={s.market_cap} | week_ret={s.week_return}%"
            )
        context = "\n".join(context_lines) or "No sector scan data yet."
        system_prompt = (
            "You are an assistant that produces a weekly sector digest. Summarize the key sectors, "
            "highlight hidden giants (small-to-mid cap with positive momentum or reasonable P/E), "
            "and provide a short watchlist suggestion."
        )
        try:
            full_text = synthesize_material_change(system_prompt, context, max_tokens=1000)
        except Exception as e:
            full_text = f"Weekly digest unavailable: {e}. Raw scan count: {len(scans)}."

        existing = (
            session.query(WeeklyDigest)
            .filter_by(digest_date=today, digest_type="weekly", digest_time=None)
            .first()
        )
        if existing:
            existing.full_digest_text = full_text
        else:
            session.add(
                WeeklyDigest(
                    digest_date=today,
                    digest_type="weekly",
                    digest_time=None,
                    full_digest_text=full_text,
                    sector_summaries_json=None,
                    hidden_giants_json=None,
                    watchlist_suggestions_json=None,
                    delivered_telegram=False,
                )
            )
        session.commit()
    finally:
        session.close()

