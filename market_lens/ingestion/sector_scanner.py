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
    from market_lens.database.watchlist import WatchlistManager

    session = SessionLocal()
    try:
        today = _utc_today()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        # Watchlist summary as baseline context
        wl = WatchlistManager()
        tickers = []
        for c in wl.list_watchlist():
            if hasattr(c, "ticker"):
                tickers.append(c.ticker)
            elif isinstance(c, dict) and "ticker" in c:
                tickers.append(str(c["ticker"]))
        watchlist_summary = (
            f"Monitoring: {', '.join(tickers)}" if tickers else "Watchlist is currently empty."
        )

        # Recent news sentiment snapshot (last 5 articles)
        recent_news = (
            session.query(NewsSentiment)
            .order_by(NewsSentiment.article_date.desc())
            .limit(5)
            .all()
        )
        if recent_news:
            news_summary = "; ".join(
                f"{r.ticker} {r.sentiment_label} ({r.sentiment_score:.2f})"
                for r in recent_news
                if r.sentiment_score is not None
            )
        else:
            news_summary = "No recent news sentiment data yet."

        # Simple macro summary fallback (FRED-backed context can be wired later)
        macro_summary = (
            "Monitor Fed rate path, inflation trajectory, yield curve shape, and AI infrastructure spending."
        )

        system_prompt = """You are a concise financial research assistant for a personal investment platform.
Your job is to write a 3-bullet daily market briefing based on whatever data is available.
Always write exactly 3 bullets. Never refuse or ask for more data.
If market data is limited, summarize the macro environment and note what to watch.
Format each bullet as: [SIGNAL] One clear sentence. (sector tag)
SIGNAL must be one of: BULLISH, BEARISH, NEUTRAL, WATCH."""

        user_content = f"""Write today's 3-bullet {slot} briefing for {today}.
Available context:
- Watchlist: {watchlist_summary}
- Recent news sentiment: {news_summary}
- Macro indicators: {macro_summary}

Write 3 bullets now. Do not refuse. Do not ask questions. Just write the briefing."""

        try:
            full_text = summarize_low_stakes(system_prompt, user_content, max_tokens=400)
        except Exception as e:
            fallback_context = f"Watchlist: {watchlist_summary}; News: {news_summary}; Macro: {macro_summary}"
            full_text = f"Briefing unavailable: {e}. Raw: {fallback_context}"

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
    Generate weekly sector digest using Claude Sonnet.

    Uses last 7 days of news sentiment plus the current watchlist as context,
    and overwrites the weekly placeholder row (if any) in WeeklyDigest.
    """
    from datetime import timedelta
    from market_lens.agent.llm_client import call_claude_sonnet
    from market_lens.database.watchlist import WatchlistManager

    today = _utc_today()
    wl = WatchlistManager()

    # Build watchlist ticker list (robust to dict- or ORM-style entries)
    tickers: List[str] = []
    for c in wl.list_watchlist():
        if hasattr(c, "ticker"):
            tickers.append(c.ticker)
        elif isinstance(c, dict) and "ticker" in c:
            tickers.append(str(c["ticker"]))

    session = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        news_rows = (
            session.query(NewsSentiment)
            .filter(NewsSentiment.article_date >= cutoff)
            .order_by(NewsSentiment.sentiment_score.desc().nullslast())
            .limit(20)
            .all()
        )
        if news_rows:
            news_context = "\n".join(
                f"{n.ticker}: {n.headline} ({n.sentiment_label} {n.sentiment_score:.2f})"
                for n in news_rows
                if n.sentiment_score is not None
            )
        else:
            news_context = "No news sentiment data this week."

        system_prompt = """You are a senior equity research analyst writing a weekly sector digest
for a personal investment platform focused on AI infrastructure, cybersecurity, and supply chain.
Write in a direct, analytical style. No fluff. Focus on what matters for position sizing and watchlist management."""

        user_prompt = f"""Write a weekly sector digest for the week ending {today}.

Watchlist: {', '.join(tickers) if tickers else 'No active watchlist tickers'}

News and sentiment this week:
{news_context}

Structure your digest as:
1. MACRO PULSE (2 sentences on the macro backdrop)
2. SECTOR SIGNALS (one paragraph each for: AI Cybersecurity, Automotive Tech, Supply Chain)
3. WATCHLIST MOVERS (which tickers had notable signal this week and why)
4. WHAT TO WATCH NEXT WEEK (2-3 specific things)

Write the full digest now."""

        try:
            full_text = call_claude_sonnet(system_prompt, user_prompt, max_tokens=1000)
        except Exception as e:
            full_text = f"Weekly digest generation failed: {e}. Context: {news_context[:500]}"

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

