"""
Market Lens — Signal Scoring Engine
Aggregates signals from all data sources and scores tickers for the Research Radar.
Sources: news sentiment, insider clustering, fund positions, substack mentions,
         options flow, short interest.
"""
from datetime import date, datetime, timedelta, timezone
from typing import List, Dict
from collections import defaultdict

from sqlalchemy.orm import Session

from market_lens.database.models import (
    Company,
    NewsSentiment,
    InsiderTransaction,
    FundPosition,
    FundPositionDelta,
    SubstackPost,
    OptionsSignal,
    ResearchRadar,
)

SIGNAL_WEIGHTS = {
    "news_sentiment": 0.15,
    "insider_buying": 0.25,
    "fund_conviction": 0.25,
    "substack_mentions": 0.15,
    "options_flow": 0.10,
    "short_squeeze": 0.10,
}


def _score_news(session: Session, ticker: str, lookback_days: int = 7) -> float:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    rows = (
        session.query(NewsSentiment.sentiment_score)
        .filter(NewsSentiment.ticker == ticker)
        .filter(NewsSentiment.article_date >= cutoff)
        .all()
    )
    if not rows:
        return 0.0
    avg = sum(r[0] or 0 for r in rows) / len(rows)
    return max(0.0, min(1.0, (avg + 1.0) / 2.0))


def _score_insider(session: Session, ticker: str, lookback_days: int = 90) -> float:
    cutoff = date.today() - timedelta(days=lookback_days)
    buys = (
        session.query(InsiderTransaction)
        .filter(InsiderTransaction.ticker == ticker)
        .filter(InsiderTransaction.filing_date >= cutoff)
        .filter(
            InsiderTransaction.transaction_type.in_(
                ["P", "A", "Buy", "purchase", "buy"]
            )
        )
        .all()
    )
    sells = (
        session.query(InsiderTransaction)
        .filter(InsiderTransaction.ticker == ticker)
        .filter(InsiderTransaction.filing_date >= cutoff)
        .filter(InsiderTransaction.transaction_type.in_(["S", "Sell", "sale"]))
        .all()
    )
    unique_buyers = len(set(t.insider_name for t in buys if t.insider_name))
    if unique_buyers == 0:
        return 0.0
    buy_count = len(buys)
    sell_count = len(sells)
    net_ratio = buy_count / max(1, buy_count + sell_count)
    conviction = min(1.0, unique_buyers / 3.0)
    return round(net_ratio * conviction, 3)


def _score_fund_conviction(session: Session, ticker: str) -> float:
    latest_q = (
        session.query(FundPosition.quarter)
        .filter(FundPosition.ticker == ticker)
        .order_by(FundPosition.quarter.desc())
        .first()
    )
    if not latest_q:
        return 0.0
    quarter = latest_q[0]
    positions = (
        session.query(FundPosition)
        .filter(FundPosition.ticker == ticker)
        .filter(FundPosition.quarter == quarter)
        .all()
    )
    fund_count = len(positions)
    if fund_count == 0:
        return 0.0
    deltas = (
        session.query(FundPositionDelta)
        .filter(FundPositionDelta.ticker == ticker)
        .filter(FundPositionDelta.quarter == quarter)
        .all()
    )
    adds = sum(1 for d in deltas if d.change_type in ("added", "increased"))
    exits = sum(1 for d in deltas if d.change_type in ("exited", "decreased"))
    net = adds - exits
    base_score = min(1.0, fund_count / 3.0)
    delta_bonus = min(0.3, net * 0.1)
    return round(min(1.0, base_score + delta_bonus), 3)


def _score_substack(session: Session, ticker: str, lookback_days: int = 30) -> float:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    try:
        posts = (
            session.query(SubstackPost)
            .filter(SubstackPost.tickers.contains([ticker]))
            .filter(SubstackPost.published_date >= cutoff)
            .all()
        )
    except Exception:
        return 0.0
    if not posts:
        return 0.0
    unique_authors = len(set(p.feed_id for p in posts))
    return min(1.0, unique_authors * 0.33 + len(posts) * 0.1)


def _score_options(session: Session, ticker: str, lookback_days: int = 7) -> float:
    cutoff = date.today() - timedelta(days=lookback_days)
    try:
        signals = (
            session.query(OptionsSignal)
            .filter(OptionsSignal.ticker == ticker)
            .filter(OptionsSignal.signal_date >= cutoff)
            .filter(OptionsSignal.unusual_flag == True)
            .all()
        )
    except Exception:
        return 0.0
    if not signals:
        return 0.0
    bullish = sum(1 for s in signals if (s.sentiment or "").lower() == "bullish")
    return min(1.0, bullish * 0.33)


def _score_short_squeeze(session: Session, ticker: str) -> float:
    company = session.query(Company).filter_by(ticker=ticker).first()
    if not company:
        return 0.0
    spf = getattr(company, "short_percent_float", None)
    sr = getattr(company, "short_ratio", None)
    if spf is None:
        return 0.0
    squeeze_potential = min(1.0, spf / 20.0)
    if sr and sr > 10:
        squeeze_potential = min(1.0, squeeze_potential + 0.2)
    return round(squeeze_potential, 3)


def score_ticker(session: Session, ticker: str) -> Dict:
    scores = {
        "news_sentiment": _score_news(session, ticker),
        "insider_buying": _score_insider(session, ticker),
        "fund_conviction": _score_fund_conviction(session, ticker),
        "substack_mentions": _score_substack(session, ticker),
        "options_flow": _score_options(session, ticker),
        "short_squeeze": _score_short_squeeze(session, ticker),
    }
    weighted = sum(scores[k] * SIGNAL_WEIGHTS[k] for k in scores)
    total = round(weighted * 100, 1)
    firing = [k for k, v in scores.items() if v > 0.3]
    return {
        "ticker": ticker,
        "total_score": total,
        "signals": scores,
        "firing_signals": firing,
        "signal_count": len(firing),
    }


def run_signal_engine(session: Session) -> Dict:
    """
    Score all watchlist tickers and detect non-watchlist tickers appearing
    across 2 or more external sources as consider-adding candidates.
    """
    watchlist = session.query(Company).filter_by(active=True, paused=False).all()
    watchlist_tickers = {c.ticker for c in watchlist}

    watchlist_scores: List[Dict] = []
    for company in watchlist:
        result = score_ticker(session, company.ticker)
        result["name"] = company.name or company.ticker
        watchlist_scores.append(result)
    watchlist_scores.sort(key=lambda x: x["total_score"], reverse=True)

    candidate_counts: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"substack": 0, "funds": 0}
    )

    cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)
    try:
        posts = (
            session.query(SubstackPost)
            .filter(SubstackPost.published_date >= cutoff_30d)
            .filter(SubstackPost.tickers.isnot(None))
            .all()
        )
        for post in posts:
            for t in (post.tickers or []):
                if t not in watchlist_tickers:
                    candidate_counts[t]["substack"] += 1
    except Exception:
        pass

    try:
        latest_q = (
            session.query(FundPosition.quarter)
            .order_by(FundPosition.quarter.desc())
            .first()
        )
        if latest_q:
            fund_positions = (
                session.query(FundPosition.ticker)
                .filter(FundPosition.quarter == latest_q[0])
                .distinct()
                .all()
            )
            for (t,) in fund_positions:
                if t not in watchlist_tickers:
                    candidate_counts[t]["funds"] += 1
    except Exception:
        pass

    try:
        radar_rows = (
            session.query(ResearchRadar.ticker)
            .filter(ResearchRadar.mention_date >= date.today() - timedelta(days=30))
            .all()
        )
        for (t,) in radar_rows:
            if t not in watchlist_tickers:
                candidate_counts[t]["substack"] += 1
    except Exception:
        pass

    consider_adding: List[Dict] = []
    for ticker, counts in candidate_counts.items():
        source_count = sum(1 for v in counts.values() if v > 0)
        if source_count >= 2:
            consider_adding.append(
                {
                    "ticker": ticker,
                    "substack_mentions": counts["substack"],
                    "fund_appearances": counts["funds"],
                    "source_count": source_count,
                }
            )
    consider_adding.sort(key=lambda x: x["source_count"], reverse=True)

    return {
        "watchlist_scores": watchlist_scores,
        "consider_adding": consider_adding[:10],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

