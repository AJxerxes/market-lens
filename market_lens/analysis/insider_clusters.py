"""
Insider transaction clustering analysis.
Detects when multiple insiders buy the same ticker within a short window.
This is a strong bullish signal — insiders rarely coordinate unless they
share conviction about upcoming value.
"""
from datetime import datetime, date, timedelta
from typing import List, Dict
from collections import defaultdict

from market_lens.database.models import InsiderTransaction
from market_lens.ingestion.tracked_funds import _get_session


def detect_insider_clusters(
    lookback_days: int = 90,
    min_insiders: int = 2,
    min_transactions: int = 3,
) -> List[Dict]:
    """
    Find tickers where multiple insiders have been buying within lookback window.

    Returns list of cluster dicts sorted by signal strength.
    """
    session = _get_session()
    try:
        cutoff = date.today() - timedelta(days=lookback_days)

        transactions = (
            session.query(InsiderTransaction)
            .filter(
                InsiderTransaction.filing_date >= cutoff,
                InsiderTransaction.transaction_type.in_(
                    ["P", "A", "Buy", "purchase", "buy"]
                ),
            )
            .order_by(InsiderTransaction.filing_date.desc())
            .all()
        )

        # Group by ticker
        by_ticker = defaultdict(list)
        for t in transactions:
            by_ticker[t.ticker].append(t)

        clusters = []
        for ticker, txns in by_ticker.items():
            unique_insiders = set(t.insider_name for t in txns if t.insider_name)
            total_shares = sum(t.shares or 0 for t in txns)
            total_value = sum(
                (t.shares or 0) * (t.price_per_share or 0) for t in txns
            )

            if len(unique_insiders) < min_insiders or len(txns) < min_transactions:
                continue

            dates = sorted(t.filing_date for t in txns)
            date_range_days = (dates[-1] - dates[0]).days if len(dates) > 1 else 0

            clusters.append(
                {
                    "ticker": ticker,
                    "unique_insiders": len(unique_insiders),
                    "insider_names": list(unique_insiders),
                    "total_transactions": len(txns),
                    "total_shares": int(total_shares),
                    "total_value_usd": round(total_value, 2),
                    "first_transaction": dates[0].isoformat(),
                    "last_transaction": dates[-1].isoformat(),
                    "date_range_days": date_range_days,
                    "signal_strength": len(unique_insiders) * len(txns),
                }
            )

        clusters.sort(key=lambda x: x["signal_strength"], reverse=True)
        return clusters

    finally:
        session.close()


def get_insider_cluster_summary() -> Dict:
    """
    Get a summary of insider clusters for dashboard display.
    """
    clusters = detect_insider_clusters()
    return {
        "total_clusters": len(clusters),
        "top_clusters": clusters[:10],
        "generated_at": datetime.utcnow().isoformat(),
    }

