"""
Options flow ingestion and cross-validation.

Final stack (per spec & update briefs):
- Layer 1: yfinance option_chain() (no key required)
- Layer 2: Unusual Whales public flow page (HTML scrape)
- Layer 3: Nasdaq options activity page (HTML scrape)

Cross-validation rule:
Fire a swing alert only when at least two of the three sources
flag the same ticker on the same day. All raw signals are stored
in options_signals; cross_validated is set when ≥2 distinct sources
agree.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterable, List, Optional, Set

import requests
import yfinance as yf
from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_lens.config import DATABASE_URL
from market_lens.database.models import OptionsSignal


_engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=_engine)


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _get_session():
    return SessionLocal()


# ---------------------------------------------------------------------------
# Layer 1 - yfinance option chains
# ---------------------------------------------------------------------------


def fetch_yfinance_option_signals(ticker: str, as_of: Optional[date] = None) -> None:
    """
    Layer 1: use yfinance to pull the option chain and compute
    simple unusual-volume candidates.

    NOTE: This implements the volume/open-interest ratio logic.
    A true 20-day rolling average per contract can be added later
    once enough history is accumulated in options_signals.
    """
    if as_of is None:
        as_of = _utc_today()

    session = _get_session()
    try:
        yf_ticker = yf.Ticker(ticker)
        expiries = yf_ticker.options
        if not expiries:
            return

        # Use nearest 1–2 expiries to keep runtime reasonable
        expiries = expiries[:2]

        for exp in expiries:
            chain = yf_ticker.option_chain(exp)
            for side_df in (chain.calls, chain.puts):
                for _, row in side_df.iterrows():
                    volume = int(row.get("volume") or 0)
                    oi = int(row.get("openInterest") or 0)
                    if oi <= 0:
                        continue

                    volume_oi_ratio = volume / oi if oi else 0.0
                    # Placeholder for 20-day average multiplier; replace with
                    # contract-specific history when available.
                    vs_20day_avg = None

                    # Spec logic: ratio > 0.5 AND volume > 3x 20-day avg.
                    # Here we approximate with a minimum absolute volume to avoid
                    # flagging tiny contracts; refine once history exists.
                    flagged_unusual = volume_oi_ratio > 0.5 and volume >= 500

                    contract_symbol = row.get("contractSymbol") or ""

                    signal = OptionsSignal(
                        ticker=ticker,
                        signal_date=as_of,
                        contract=contract_symbol,
                        source="yfinance",
                        volume=volume,
                        open_interest=oi,
                        volume_oi_ratio=volume_oi_ratio,
                        vs_20day_avg=vs_20day_avg if vs_20day_avg is not None else 0.0,
                        flagged_unusual=flagged_unusual,
                        cross_validated=False,
                    )
                    session.add(signal)

        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Layer 2 - Unusual Whales public flow (HTML scrape)
# ---------------------------------------------------------------------------


UNUSUAL_WHALES_URL = "https://unusualwhales.com/flow"


def fetch_unusual_whales_signals(
    watchlist_tickers: Iterable[str],
    as_of: Optional[date] = None,
) -> None:
    """
    Layer 2: scrape the public Unusual Whales flow page.

    Only rows for watchlist tickers are stored. If the HTML
    structure changes or the request fails, this function logs
    and exits quietly so the rest of the pipeline can continue.
    """
    if as_of is None:
        as_of = _utc_today()

    watchlist = {t.upper() for t in watchlist_tickers}

    session = _get_session()
    try:
        resp = requests.get(UNUSUAL_WHALES_URL, timeout=10)
        if resp.status_code != 200:
            # Degrade gracefully
            return

        soup = BeautifulSoup(resp.text, "lxml")

        # The exact table structure may change; this is written defensively.
        table = soup.find("table")
        if not table:
            return

        header_cells = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        # Try to identify key column indices; fall back if missing.
        try:
            ticker_idx = header_cells.index("ticker")
        except ValueError:
            ticker_idx = None

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue

            if ticker_idx is not None and ticker_idx < len(cells):
                ticker = cells[ticker_idx].get_text(strip=True).upper()
            else:
                # Best effort: assume first cell is ticker
                ticker = cells[0].get_text(strip=True).upper()

            if ticker not in watchlist:
                continue

            # Volume & OI may or may not be present in the public table.
            # We store whatever we can and let downstream logic decide.
            volume = None
            open_interest = None

            signal = OptionsSignal(
                ticker=ticker,
                signal_date=as_of,
                contract="",  # Unspecified in public table
                source="unusualwhales",
                volume=volume if volume is not None else 0,
                open_interest=open_interest if open_interest is not None else 0,
                volume_oi_ratio=0.0,
                vs_20day_avg=0.0,
                flagged_unusual=True,  # By definition this page lists unusual flow
                cross_validated=False,
            )
            session.add(signal)

        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Layer 3 - Nasdaq options activity (HTML scrape)
# ---------------------------------------------------------------------------


NASDAQ_OPTIONS_URL = "https://www.nasdaq.com/market-activity/options"


def fetch_nasdaq_option_signals(
    watchlist_tickers: Iterable[str],
    as_of: Optional[date] = None,
) -> None:
    """
    Layer 3: scrape Nasdaq's unusual options activity page.

    Extract ticker, volume, and open interest where available,
    constrain to watchlist tickers, and store a signal row
    for each.
    """
    if as_of is None:
        as_of = _utc_today()

    watchlist = {t.upper() for t in watchlist_tickers}

    session = _get_session()
    try:
        resp = requests.get(NASDAQ_OPTIONS_URL, timeout=10)
        if resp.status_code != 200:
            return

        soup = BeautifulSoup(resp.text, "lxml")
        container = soup.find("div", class_="market-options-activity")
        if not container:
            return

        table = container.find("table")
        if not table:
            return

        header_cells = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        try:
            ticker_idx = header_cells.index("symbol")
        except ValueError:
            ticker_idx = None

        volume_idx = None
        oi_idx = None
        for i, name in enumerate(header_cells):
            if "volume" in name and volume_idx is None:
                volume_idx = i
            if "open" in name and "interest" in name and oi_idx is None:
                oi_idx = i

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue

            if ticker_idx is not None and ticker_idx < len(cells):
                ticker = cells[ticker_idx].get_text(strip=True).upper()
            else:
                ticker = cells[0].get_text(strip=True).upper()

            if ticker not in watchlist:
                continue

            volume = 0
            oi = 0
            if volume_idx is not None and volume_idx < len(cells):
                try:
                    volume = int(cells[volume_idx].get_text(strip=True).replace(",", ""))
                except ValueError:
                    volume = 0
            if oi_idx is not None and oi_idx < len(cells):
                try:
                    oi = int(cells[oi_idx].get_text(strip=True).replace(",", ""))
                except ValueError:
                    oi = 0

            volume_oi_ratio = volume / oi if oi else 0.0

            signal = OptionsSignal(
                ticker=ticker,
                signal_date=as_of,
                contract="",
                source="nasdaq",
                volume=volume,
                open_interest=oi,
                volume_oi_ratio=volume_oi_ratio,
                vs_20day_avg=0.0,
                flagged_unusual=True,
                cross_validated=False,
            )
            session.add(signal)

        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Cross-validation
# ---------------------------------------------------------------------------


def mark_cross_validated_signals(for_date: Optional[date] = None) -> None:
    """
    Set cross_validated=True for any ticker+date that has
    >= 2 distinct sources with flagged_unusual=True.
    """
    if for_date is None:
        for_date = _utc_today()

    session = _get_session()
    try:
        rows: List[OptionsSignal] = (
            session.query(OptionsSignal)
            .filter(OptionsSignal.signal_date == for_date)
            .all()
        )

        # Group by ticker
        by_ticker: dict[str, List[OptionsSignal]] = {}
        for row in rows:
            by_ticker.setdefault(row.ticker, []).append(row)

        for ticker, signals in by_ticker.items():
            sources: Set[str] = {
                s.source for s in signals if s.flagged_unusual
            }
            if len(sources) >= 2:
                for s in signals:
                    if s.flagged_unusual:
                        s.cross_validated = True

        session.commit()
    finally:
        session.close()


def run_options_ingestion_for_watchlist(watchlist_tickers: Iterable[str]) -> None:
    """
    High-level entry point used by the scheduler / agent brain:
    - Layer 1: yfinance per ticker
    - Layer 2: Unusual Whales (global page, filter to watchlist)
    - Layer 3: Nasdaq (global page, filter to watchlist)
    - Cross-validation: mark signals where ≥2 sources agree
    """
    today = _utc_today()

    # Layer 1: per-ticker yfinance chains
    for ticker in watchlist_tickers:
        fetch_yfinance_option_signals(ticker, as_of=today)

    # Layer 2 & 3 are global pages filtered by watchlist
    fetch_unusual_whales_signals(watchlist_tickers, as_of=today)
    fetch_nasdaq_option_signals(watchlist_tickers, as_of=today)

    # Cross-validation
    mark_cross_validated_signals(for_date=today)

