"""
Anomaly detection using IsolationForest (Phase 12B).

This is the only machine learning component in Market Lens.
It runs on historical price, volume, and sentiment time-series
to flag statistically unusual behavior that might warrant a
closer look by the agent brain.

Design notes:
- Uses scikit-learn's IsolationForest (unsupervised).
- No labels, no complex training pipeline.
- Intended to be called periodically (e.g. daily) per ticker.
- Results are fed into delta.py; this module itself does not
  send alerts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_lens import config
from market_lens.database.models import PriceHistory, NewsSentiment


_engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=_engine)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AnomalyEvent:
    ticker: str
    timestamp: datetime
    score: float  # anomaly score from IsolationForest (lower = more anomalous)
    feature_vector: dict


def _load_features_for_ticker(
    ticker: str,
    lookback_days: int = 90,
) -> tuple[np.ndarray, List[datetime]]:
    """
    Build a simple feature matrix for a given ticker over the
    specified lookback window:
    - Normalized daily returns
    - Volume (log-scaled)
    - 7-day rolling news sentiment mean (if available)
    """
    session = SessionLocal()
    try:
        cutoff = _utc_now().date() - timedelta(days=lookback_days)
        prices = (
            session.query(PriceHistory)
            .filter(PriceHistory.ticker == ticker)
            .filter(PriceHistory.date >= cutoff)
            .order_by(PriceHistory.date.asc())
            .all()
        )
        if not prices:
            return np.empty((0, 3)), []

        # Build arrays
        closes = np.array([p.close for p in prices], dtype=float)
        volumes = np.array([p.volume or 0 for p in prices], dtype=float)
        dates = [datetime.combine(p.date, datetime.min.time(), tzinfo=timezone.utc) for p in prices]

        # Daily returns (first day return = 0)
        rets = np.zeros_like(closes)
        if len(closes) > 1:
            rets[1:] = (closes[1:] - closes[:-1]) / np.where(closes[:-1] != 0, closes[:-1], 1.0)

        # Log volume to dampen extremes
        log_vol = np.log10(np.where(volumes > 0, volumes, 1.0))

        # Simple sentiment feature: 7-day rolling mean per day
        sent_by_date = _load_sentiment_by_date(session, ticker, cutoff)
        sent_vals = np.array([sent_by_date.get(p.date, 0.0) for p in prices], dtype=float)

        # Stack into feature matrix
        X = np.stack([rets, log_vol, sent_vals], axis=1)
        return X, dates
    finally:
        session.close()


def _load_sentiment_by_date(session, ticker: str, cutoff: datetime.date) -> dict:
    rows = (
        session.query(NewsSentiment)
        .filter(NewsSentiment.ticker == ticker)
        .filter(NewsSentiment.article_date >= cutoff)
        .all()
    )
    by_date: dict = {}
    for r in rows:
        d = r.article_date.date()
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(r.sentiment_score or 0.0)
    return {d: float(np.mean(vs)) for d, vs in by_date.items()}


def detect_price_volume_sentiment_anomalies(
    ticker: str,
    lookback_days: int = 90,
    contamination: float = 0.05,
) -> List[AnomalyEvent]:
    """
    Run IsolationForest on (returns, log-volume, sentiment) for a single ticker.

    Returns a list of AnomalyEvent objects for points flagged as anomalies.
    """
    X, dates = _load_features_for_ticker(ticker, lookback_days=lookback_days)
    if X.shape[0] == 0:
        return []

    # Fit IsolationForest
    clf = IsolationForest(
        n_estimators=100,
        contamination=contamination,
        random_state=42,
    )
    clf.fit(X)

    scores = clf.decision_function(X)  # higher = more normal
    preds = clf.predict(X)  # -1 = anomaly, 1 = normal

    anomalies: List[AnomalyEvent] = []
    for i, pred in enumerate(preds):
        if pred == -1:
            anomalies.append(
                AnomalyEvent(
                    ticker=ticker,
                    timestamp=dates[i],
                    score=float(scores[i]),
                    feature_vector={
                        "return": float(X[i, 0]),
                        "log_volume": float(X[i, 1]),
                        "sentiment": float(X[i, 2]),
                    },
                )
            )
    return anomalies


# NOTE: Wiring these anomalies into delta.py and the agent brain
# will happen in a later phase. For now, this module exposes a
# simple detection API that higher layers can call.

