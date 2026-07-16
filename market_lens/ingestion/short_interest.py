"""
Short interest data ingestion.
Uses yfinance for days-to-cover and short float percentage.
Free tier — no API key required.
"""
from typing import Optional, List

import yfinance as yf

from market_lens.database.models import Company
from market_lens.ingestion.tracked_funds import _get_session


def ingest_short_interest(tickers: Optional[List[str]] = None) -> None:
    """
    Pull short interest metrics for all watchlist tickers via yfinance.
    Updates Company table with short_ratio (days to cover) and short_percent_float.
    """
    session = _get_session()
    try:
        if tickers is None:
            companies = session.query(Company).filter_by(active=True, paused=False).all()
        else:
            companies = (
                session.query(Company)
                .filter(Company.ticker.in_(tickers))
                .all()
            )

        print(f"[ShortInterest] Processing {len(companies)} tickers...")
        updated = 0

        for company in companies:
            try:
                yf_ticker = yf.Ticker(company.ticker)
                info = yf_ticker.info or {}

                short_ratio = info.get("shortRatio")
                short_percent_float = info.get("shortPercentOfFloat")

                if short_ratio is not None and hasattr(Company, "short_ratio"):
                    company.short_ratio = float(short_ratio)
                if short_percent_float is not None and hasattr(Company, "short_percent_float"):
                    company.short_percent_float = float(short_percent_float) * 100

                print(
                    f"[ShortInterest] {company.ticker}: "
                    f"days_to_cover={short_ratio} short_float={short_percent_float}"
                )
                updated += 1
                session.commit()

            except Exception as e:
                print(f"[ShortInterest] {company.ticker} failed: {type(e).__name__}")
                session.rollback()
                continue

        print(f"[ShortInterest] Complete — updated: {updated}")

    finally:
        session.close()

