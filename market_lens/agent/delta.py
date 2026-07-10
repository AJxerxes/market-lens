"""
Market Lens — Cross-module coincidence detection (Phase 11).

Detects same-day or tight-window coincidences (e.g. score change + options
+ insider) and produces a delta_trigger dict for synthesis and AgentCycleLog.
"""
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from market_lens.database.models import (
    Score,
    InsiderTransaction,
    OptionsSignal,
    NewsSentiment,
    LeadershipEvent,
    SupplierSignal,
    CourtCase,
    AgentMemory,
)


def detect_delta(
    session: Session,
    ticker: str,
    as_of_date: Optional[date] = None,
    prior_memory: Optional[AgentMemory] = None,
) -> Tuple[Dict[str, Any], bool]:
    """
    Detect what changed and whether multiple modules fired on the same day
    (coincidence). Returns (delta_trigger, should_synthesize).

    delta_trigger: dict with keys like score_change, insider_activity, options_activity,
                   news_spike, leadership_event, supplier_signal, court_filing, coincidence.
    should_synthesize: True when there is at least one material trigger or coincidence.
    """
    if as_of_date is None:
        as_of_date = datetime.now(timezone.utc).date()
    window_start = as_of_date - timedelta(days=7)

    delta: Dict[str, Any] = {
        "as_of_date": as_of_date.isoformat(),
        "ticker": ticker,
        "score_change": None,
        "insider_activity": None,
        "options_activity": None,
        "news_spike": None,
        "leadership_event": None,
        "supplier_signal": None,
        "court_filing": None,
        "coincidence": False,
        "same_day_sources": [],
    }

    # Latest score vs prior
    latest_score = (
        session.query(Score)
        .filter(Score.ticker == ticker, Score.score_date <= as_of_date)
        .order_by(Score.score_date.desc())
        .limit(1)
        .first()
    )
    if latest_score and prior_memory:
        if prior_memory.lynch_score is not None and latest_score.lynch_score is not None:
            lynch_delta = latest_score.lynch_score - prior_memory.lynch_score
            if abs(lynch_delta) >= 0.5:
                delta["score_change"] = {
                    "lynch_delta": round(lynch_delta, 2),
                    "prior_lynch": prior_memory.lynch_score,
                    "current_lynch": latest_score.lynch_score,
                    "recommendation": latest_score.recommendation_label.value if latest_score.recommendation_label else None,
                }
        if prior_memory.swing_score is not None and latest_score.swing_score is not None:
            swing_delta = latest_score.swing_score - prior_memory.swing_score
            if abs(swing_delta) >= 0.5:
                if delta["score_change"] is None:
                    delta["score_change"] = {}
                if not isinstance(delta["score_change"], dict):
                    delta["score_change"] = {"lynch_delta": delta["score_change"]}
                delta["score_change"]["swing_delta"] = round(swing_delta, 2)
                delta["score_change"]["current_swing"] = latest_score.swing_score

    # Insider in last 7 days
    insider_count = (
        session.query(InsiderTransaction)
        .filter(
            InsiderTransaction.ticker == ticker,
            InsiderTransaction.filing_date >= window_start,
            InsiderTransaction.filing_date <= as_of_date,
        )
        .count()
    )
    if insider_count > 0:
        delta["insider_activity"] = {"filings_last_7d": insider_count}
        same_day_insider = (
            session.query(InsiderTransaction)
            .filter(
                InsiderTransaction.ticker == ticker,
                InsiderTransaction.filing_date == as_of_date,
            )
            .count()
        )
        if same_day_insider > 0:
            delta["same_day_sources"].append("insider")

    # Options (same day or last 3 days)
    options_on_date = (
        session.query(OptionsSignal)
        .filter(
            OptionsSignal.ticker == ticker,
            OptionsSignal.signal_date == as_of_date,
            OptionsSignal.cross_validated == True,
        )
        .count()
    )
    if options_on_date > 0:
        delta["options_activity"] = {"cross_validated_same_day": options_on_date}
        delta["same_day_sources"].append("options")

    # News spike (same day negative or strong positive)
    start_of_day = datetime(as_of_date.year, as_of_date.month, as_of_date.day, tzinfo=timezone.utc)
    end_of_day = start_of_day + timedelta(days=1)
    news_today = (
        session.query(NewsSentiment)
        .filter(
            NewsSentiment.ticker == ticker,
            NewsSentiment.article_date >= start_of_day,
            NewsSentiment.article_date < end_of_day,
        )
        .all()
    )
    if news_today:
        avg_sent = sum(n.sentiment_score or 0 for n in news_today) / len(news_today)
        delta["news_spike"] = {"articles_today": len(news_today), "avg_sentiment": round(avg_sent, 3)}
        delta["same_day_sources"].append("news")

    # Leadership (event_date in window)
    leadership = (
        session.query(LeadershipEvent)
        .filter(
            LeadershipEvent.ticker == ticker,
            LeadershipEvent.event_date >= window_start,
            LeadershipEvent.event_date <= as_of_date,
        )
        .all()
    )
    if leadership:
        delta["leadership_event"] = [
            {"person": e.person_name, "role": e.role, "event_type": e.event_type.value if e.event_type else None, "date": e.event_date.isoformat()}
            for e in leadership
        ]
        if any(e.event_date == as_of_date for e in leadership):
            delta["same_day_sources"].append("leadership")

    # Supplier signal in window
    supplier = (
        session.query(SupplierSignal)
        .filter(
            SupplierSignal.ticker == ticker,
            SupplierSignal.detected_date >= window_start,
            SupplierSignal.detected_date <= as_of_date,
        )
        .first()
    )
    if supplier:
        delta["supplier_signal"] = {
            "signal_type": supplier.signal_type.value if supplier.signal_type else None,
            "supplier_name": supplier.supplier_name,
            "date": supplier.detected_date.isoformat(),
        }
        if supplier.detected_date == as_of_date:
            delta["same_day_sources"].append("supplier")

    # Court filing in window
    court = (
        session.query(CourtCase)
        .filter(
            CourtCase.ticker == ticker,
            CourtCase.filed_date.isnot(None),
            CourtCase.filed_date >= window_start,
            CourtCase.filed_date <= as_of_date,
        )
        .first()
    )
    if court:
        delta["court_filing"] = {"case_number": court.case_number, "filed_date": court.filed_date.isoformat()}
        if court.filed_date == as_of_date:
            delta["same_day_sources"].append("court")

    # Coincidence: 2+ same-day sources or score change + any other
    same_day = list(dict.fromkeys(delta["same_day_sources"]))
    delta["coincidence"] = len(same_day) >= 2 or (delta["score_change"] and len(same_day) >= 1)
    if delta["coincidence"]:
        delta["same_day_sources"] = same_day

    should_synthesize = (
        delta["score_change"] is not None
        or delta["insider_activity"] is not None
        or delta["options_activity"] is not None
        or delta["news_spike"] is not None
        or delta["leadership_event"] is not None
        or delta["supplier_signal"] is not None
        or delta["court_filing"] is not None
        or delta["coincidence"]
    )
    return delta, should_synthesize
