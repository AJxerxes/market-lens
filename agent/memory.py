"""
Market Lens — Agent 90-day signal history (Phase 11).

Builds a compressed 90-day event log from DB for a ticker, for use in
agent_memory.signal_history_90d and in synthesizer history_90d input.
"""
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

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
from market_lens.database.models import EventType, SignalType


def _dt_90d_ago() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=90)


def _date_90d_ago():
    return _dt_90d_ago().date()


def build_signal_history_90d(session: Session, ticker: str) -> Dict[str, Any]:
    """
    Build 90-day signal history from all relevant tables.
    Returns a dict suitable for JSON storage and for synthesizer history_90d.
    """
    cutoff = _date_90d_ago()
    cutoff_dt = _dt_90d_ago()

    events: List[Dict[str, Any]] = []

    # Scores (use score_date)
    scores = (
        session.query(Score)
        .filter(Score.ticker == ticker, Score.score_date >= cutoff)
        .order_by(Score.score_date.asc())
        .all()
    )
    for s in scores:
        events.append({
            "date": s.score_date.isoformat(),
            "source": "score",
            "lynch_score": s.lynch_score,
            "swing_score": s.swing_score,
            "recommendation_label": s.recommendation_label.value if s.recommendation_label else None,
        })

    # Insider (filing_date)
    insiders = (
        session.query(InsiderTransaction)
        .filter(InsiderTransaction.ticker == ticker, InsiderTransaction.filing_date >= cutoff)
        .order_by(InsiderTransaction.filing_date.asc())
        .all()
    )
    for i in insiders:
        events.append({
            "date": i.filing_date.isoformat(),
            "source": "insider",
            "insider_name": i.insider_name,
            "transaction_type": i.transaction_type,
            "shares": i.shares,
            "total_value": i.total_value,
        })

    # Options (signal_date)
    options = (
        session.query(OptionsSignal)
        .filter(OptionsSignal.ticker == ticker, OptionsSignal.signal_date >= cutoff)
        .order_by(OptionsSignal.signal_date.asc())
        .all()
    )
    for o in options:
        events.append({
            "date": o.signal_date.isoformat(),
            "source": "options",
            "contract": o.contract,
            "volume_oi_ratio": o.volume_oi_ratio,
            "cross_validated": o.cross_validated,
        })

    # News (article_date)
    news = (
        session.query(NewsSentiment)
        .filter(NewsSentiment.ticker == ticker, NewsSentiment.article_date >= cutoff_dt)
        .order_by(NewsSentiment.article_date.asc())
        .limit(200)
        .all()
    )
    for n in news:
        events.append({
            "date": n.article_date.date().isoformat(),
            "source": "news",
            "sentiment_score": n.sentiment_score,
            "headline": (n.headline or "")[:120],
        })

    # Leadership (event_date)
    leadership = (
        session.query(LeadershipEvent)
        .filter(LeadershipEvent.ticker == ticker, LeadershipEvent.event_date >= cutoff)
        .order_by(LeadershipEvent.event_date.asc())
        .all()
    )
    for l in leadership:
        events.append({
            "date": l.event_date.isoformat(),
            "source": "leadership",
            "person_name": l.person_name,
            "role": l.role,
            "event_type": l.event_type.value if l.event_type else None,
            "departure_classified": l.departure_language_classified.value if l.departure_language_classified else None,
        })

    # Supplier signals (detected_date)
    suppliers = (
        session.query(SupplierSignal)
        .filter(SupplierSignal.ticker == ticker, SupplierSignal.detected_date >= cutoff)
        .order_by(SupplierSignal.detected_date.asc())
        .all()
    )
    for s in suppliers:
        events.append({
            "date": s.detected_date.isoformat(),
            "source": "supplier",
            "signal_type": s.signal_type.value if s.signal_type else None,
            "supplier_name": s.supplier_name,
            "severity": s.severity.value if s.severity else None,
        })

    # Court cases (filed_date)
    cases = (
        session.query(CourtCase)
        .filter(CourtCase.ticker == ticker)
        .filter(CourtCase.filed_date is not None, CourtCase.filed_date >= cutoff)
        .order_by(CourtCase.filed_date.asc())
        .all()
    )
    for c in cases:
        events.append({
            "date": c.filed_date.isoformat(),
            "source": "court",
            "case_number": c.case_number,
            "case_type": c.case_type,
        })

    # Sort by date and cap size for storage
    events.sort(key=lambda e: e["date"])
    if len(events) > 500:
        events = events[-500:]

    return {
        "window_start": cutoff.isoformat(),
        "window_end": datetime.now(timezone.utc).date().isoformat(),
        "ticker": ticker,
        "events": events,
        "count_by_source": _count_by_source(events),
    }


def _count_by_source(events: List[Dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for e in events:
        src = e.get("source", "unknown")
        out[src] = out.get(src, 0) + 1
    return out


def get_latest_memory(session: Session, ticker: str) -> Optional[AgentMemory]:
    """Return the most recent agent_memory row for ticker, or None."""
    return (
        session.query(AgentMemory)
        .filter(AgentMemory.ticker == ticker)
        .order_by(AgentMemory.snapshot_date.desc())
        .limit(1)
        .first()
    )


def prior_state_from_memory(mem: Optional[AgentMemory]) -> Dict[str, Any]:
    """Turn an AgentMemory row into the prior_state dict for synthesizer."""
    if not mem:
        return {}
    return {
        "snapshot_date": mem.snapshot_date.isoformat() if mem.snapshot_date else None,
        "lynch_score": mem.lynch_score,
        "swing_score": mem.swing_score,
        "sentiment_score": mem.sentiment_score,
        "insider_net": mem.insider_net,
        "recommendation_label": mem.recommendation_label,
        "thesis_summary": mem.thesis_summary,
    }
