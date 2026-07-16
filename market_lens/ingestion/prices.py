"""
Market Lens — Price and Fundamentals Ingestion (Phase 2)
Pulls 5Y price history and current fundamentals via yfinance.
ETFs and mutual funds skip quarterly financials.
"""
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

import yfinance as yf
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

from market_lens.config import DATABASE_URL
from market_lens.database.models import (
    Base,
    Company,
    PriceHistory,
    Fundamentals,
    InstrumentType,
)


def _engine_and_session():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    return engine, Session()


def _ensure_company_columns(engine) -> None:
    """Add Phase 2 columns to companies if missing (idempotent)."""
    from sqlalchemy import text
    cols = [
        ("data_quality_flag", "VARCHAR(20)"),
        ("market_cap", "DOUBLE PRECISION"),
        ("trailing_pe", "DOUBLE PRECISION"),
        ("forward_pe", "DOUBLE PRECISION"),
        ("dividend_yield", "DOUBLE PRECISION"),
        ("revenue_growth", "DOUBLE PRECISION"),
        ("gross_margins", "DOUBLE PRECISION"),
        ("operating_margins", "DOUBLE PRECISION"),
        ("free_cash_flow", "DOUBLE PRECISION"),
        ("debt_to_equity", "DOUBLE PRECISION"),
        ("beta", "DOUBLE PRECISION"),
        ("industry", "VARCHAR(255)"),
        ("long_name", "VARCHAR(500)"),
        ("current_price", "DOUBLE PRECISION"),
    ]
    with engine.connect() as conn:
        for col_name, col_type in cols:
            try:
                conn.execute(text(f'ALTER TABLE companies ADD COLUMN "{col_name}" {col_type}'))
                conn.commit()
            except Exception:
                conn.rollback()
                pass


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _ingest_price_history(session, ticker: str) -> int:
    """Pull 5Y history for ticker, upsert into price_history. Returns row count."""
    t = yf.Ticker(ticker)
    hist = t.history(period="5y", auto_adjust=False)
    if hist is None or hist.empty:
        return 0
    count = 0
    for dt, row in hist.iterrows():
        if hasattr(dt, "date"):
            d = dt.date() if hasattr(dt, "date") else date(dt.year, dt.month, dt.day)
        else:
            d = date(dt.year, dt.month, dt.day)
        open_ = _safe_float(row.get("Open"))
        high = _safe_float(row.get("High"))
        low = _safe_float(row.get("Low"))
        close = _safe_float(row.get("Close"))
        if close is None:
            continue
        vol = _safe_int(row.get("Volume"))
        adj = _safe_float(row.get("Adj Close"))
        stmt = pg_insert(PriceHistory).values(
            ticker=ticker,
            date=d,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=vol,
            adj_close=adj,
        ).on_conflict_do_update(
            index_elements=["ticker", "date"],
            set_={
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": vol,
                "adj_close": adj,
            },
        )
        session.execute(stmt)
        count += 1
    return count


def _ingest_current_fundamentals(session, ticker: str, info: dict, instrument_type: InstrumentType) -> None:
    """Update Company row with current snapshot; set data_quality_flag if key fields missing."""
    company = session.query(Company).filter(Company.ticker == ticker).first()
    if not company:
        return
    incomplete = False
    key_fields = ["marketCap", "trailingPE", "sector", "longName"]
    for k in key_fields:
        if info.get(k) is None and instrument_type in (InstrumentType.equity, InstrumentType.otc_adr):
            incomplete = True
            break
    company.data_quality_flag = "incomplete" if incomplete else "complete"
    company.market_cap = _safe_float(info.get("marketCap"))
    company.trailing_pe = _safe_float(info.get("trailingPE"))
    company.forward_pe = _safe_float(info.get("forwardPE"))
    company.dividend_yield = _safe_float(info.get("dividendYield"))
    if company.dividend_yield is not None and company.dividend_yield <= 1.0:
        company.dividend_yield = company.dividend_yield * 100.0  # yfinance often 0.02 for 2%
    company.revenue_growth = _safe_float(info.get("revenueGrowth"))
    if company.revenue_growth is not None and abs(company.revenue_growth) <= 1.0:
        company.revenue_growth = company.revenue_growth * 100.0
    company.gross_margins = _safe_float(info.get("grossMargins"))
    if company.gross_margins is not None and company.gross_margins <= 1.0:
        company.gross_margins = company.gross_margins * 100.0
    company.operating_margins = _safe_float(info.get("operatingMargins"))
    if company.operating_margins is not None and company.operating_margins <= 1.0:
        company.operating_margins = company.operating_margins * 100.0
    company.free_cash_flow = _safe_float(info.get("freeCashFlow"))
    company.debt_to_equity = _safe_float(info.get("debtToEquity"))
    company.beta = _safe_float(info.get("beta"))
    company.sector = info.get("sector") or company.sector
    company.industry = info.get("industry")
    company.long_name = info.get("longName") or company.name
    company.current_price = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
    session.flush()


def _ingest_quarterly_financials(session, ticker: str) -> int:
    """Pull last 8 quarters from quarterly_financials, upsert into fundamentals. Skip for ETF/mutual_fund."""
    t = yf.Ticker(ticker)
    qf = t.quarterly_financials
    if qf is None or qf.empty:
        return 0
    count = 0
    # quarterly_financials columns are period-end dates
    for col in list(qf.columns)[:8]:
        if hasattr(col, "date"):
            period_end = col.date()
        else:
            period_end = date(col.year, col.month, col.day) if hasattr(col, "year") else date.today()
        row = qf[col]
        revenue = _safe_float(row.get("Total Revenue") or row.get("Revenue"))
        gross_profit = _safe_float(row.get("Gross Profit"))
        operating_income = _safe_float(row.get("Operating Income") or row.get("EBITDA"))
        net_income = _safe_float(row.get("Net Income") or row.get("Net Income Common Stockholders"))
        stmt = pg_insert(Fundamentals).values(
            ticker=ticker,
            period_end=period_end,
            revenue=revenue,
            gross_profit=gross_profit,
            operating_income=operating_income,
            net_income=net_income,
        ).on_conflict_do_update(
            index_elements=["ticker", "period_end"],
            set_={
                "revenue": revenue,
                "gross_profit": gross_profit,
                "operating_income": operating_income,
                "net_income": net_income,
            },
        )
        session.execute(stmt)
        count += 1
    return count


def run_prices_ingestion(tickers: Optional[List[str]] = None) -> None:
    """
    Ingest 5Y price history and fundamentals for watchlist.
    If tickers is None, use all active companies.
    """
    engine, session = _engine_and_session()
    try:
        _ensure_company_columns(engine)
        if tickers is None:
            companies = (
                session.query(Company)
                .filter(Company.active == True, Company.paused == False)
                .all()
            )
            tickers = [c.ticker for c in companies]
        else:
            companies = session.query(Company).filter(Company.ticker.in_(tickers)).all()
            company_map = {c.ticker: c for c in companies}

        for ticker in tickers:
            company = next((c for c in companies if c.ticker == ticker), None)
            if not company:
                print(f"  [SKIP] {ticker} not in watchlist")
                continue
            itype = company.instrument_type

            # 1) Price history for all
            try:
                n = _ingest_price_history(session, ticker)
                print(f"  [OK] {ticker} price_history: {n} rows")
            except Exception as e:
                print(f"  [ERROR] {ticker} price_history: {e}")
                continue
            session.flush()

            # 2) Current fundamentals from .info
            try:
                t = yf.Ticker(ticker)
                info = t.info or {}
                _ingest_current_fundamentals(session, ticker, info, itype)
                if company.data_quality_flag == "incomplete":
                    print(f"  [WARN] {ticker}: incomplete data, flag set")
            except Exception as e:
                print(f"  [ERROR] {ticker} fundamentals snapshot: {e}")

            # 3) Quarterly financials only for equity / otc_adr
            if itype in (InstrumentType.equity, InstrumentType.otc_adr):
                try:
                    nq = _ingest_quarterly_financials(session, ticker)
                    print(f"  [OK] {ticker} quarterly fundamentals: {nq} periods")
                except Exception as e:
                    print(f"  [ERROR] {ticker} quarterly financials: {e}")
            else:
                print(f"  [SKIP] {ticker} quarterly financials (instrument type {itype.value})")

        session.commit()
        print("[OK] Prices ingestion complete")
    except Exception as e:
        session.rollback()
        print(f"[ERROR] Prices ingestion failed: {e}")
        raise
    finally:
        session.close()


def run_intraday_quotes(tickers: Optional[List[str]] = None) -> None:
    """
    Lightweight intraday price update — runs every 15 min during market hours.
    Only updates current_price on Company and inserts/updates today's PriceHistory row.
    Does NOT re-pull 5Y history or quarterly financials.
    """
    from datetime import time as dt_time  # noqa: F401  (kept for future market window tweaks)
    import pytz

    ET = pytz.timezone("America/New_York")
    now_et = datetime.now(ET)
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

    # Only run during market hours
    if not (market_open <= now_et <= market_close):
        return

    engine, session = _engine_and_session()
    try:
        if tickers is None:
            companies = session.query(Company).filter_by(active=True, paused=False).all()
            tickers = [c.ticker for c in companies]

        print(f"[IntradayQuotes] Fetching {len(tickers)} tickers...")
        updated = 0

        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                info = t.info or {}

                price = _safe_float(
                    info.get("currentPrice")
                    or info.get("regularMarketPrice")
                    or info.get("bid")
                )
                if not price:
                    continue

                # Update current_price on Company
                company = session.query(Company).filter_by(ticker=ticker).first()
                if company:
                    company.current_price = price

                # Upsert today's PriceHistory row
                today = date.today()
                existing_ph = (
                    session.query(PriceHistory)
                    .filter_by(ticker=ticker, date=today)
                    .first()
                )

                open_price = _safe_float(
                    info.get("regularMarketOpen") or info.get("open")
                )
                high_price = _safe_float(
                    info.get("regularMarketDayHigh") or info.get("dayHigh")
                )
                low_price = _safe_float(
                    info.get("regularMarketDayLow") or info.get("dayLow")
                )
                volume = info.get("regularMarketVolume") or info.get("volume")

                if existing_ph:
                    existing_ph.close = price
                    if high_price:
                        existing_ph.high = high_price
                    if low_price:
                        existing_ph.low = low_price
                    if volume:
                        existing_ph.volume = volume
                else:
                    session.add(
                        PriceHistory(
                            ticker=ticker,
                            date=today,
                            open=open_price,
                            high=high_price,
                            low=low_price,
                            close=price,
                            volume=volume,
                            adj_close=price,
                            source="yfinance_intraday",
                        )
                    )

                updated += 1
                session.commit()

            except Exception as e:
                try:
                    print(f"[IntradayQuotes] {ticker} failed: {type(e).__name__}")
                except OSError:
                    pass
                session.rollback()
                continue

        print(f"[IntradayQuotes] Done — {updated} tickers updated")

    finally:
        session.close()


def run_prices_for_all() -> None:
    """
    Convenience wrapper for dashboards/schedulers: run price/fundamentals
    ingestion for all active, unpaused companies.
    """
    run_prices_ingestion(tickers=None)


if __name__ == "__main__":
    import sys
    tickers = sys.argv[1:] if len(sys.argv) > 1 else None
    print("Market Lens — Price & Fundamentals Ingestion")
    print("---------------------------------------------")
    run_prices_ingestion(tickers)
