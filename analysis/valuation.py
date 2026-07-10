"""
Market Lens — Valuation (Phase 4)
DCF (bear/base/bull), Comps (FMP sector P/E, EV/EBITDA), Mean reversion (5Y avg P/E).
"""
from datetime import date, datetime, timezone
from typing import Optional, List, Tuple
import os
import requests

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from market_lens.config import DATABASE_URL, FMP_API_KEY, FRED_API_KEY
from market_lens.database.models import Base, Company, Score, Fundamentals, EdgarFact


FMP_BASE = "https://financialmodelingprep.com/api"
FRED_BASE = "https://api.stlouisfed.org/fred"


def _engine_session():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    return engine, Session()


def _risk_free_rate_10y() -> float:
    """10Y Treasury yield from FRED. Fallback 4.5%."""
    if not FRED_API_KEY:
        return 0.045
    try:
        r = requests.get(
            f"{FRED_BASE}/series/observations",
            params={"series_id": "DGS10", "api_key": FRED_API_KEY, "file_type": "json", "sort_order": "desc", "limit": 1},
            timeout=10,
        )
        if r.status_code != 200:
            return 0.045
        data = r.json()
        obs = data.get("observations", [])
        if obs and obs[0].get("value") not in (".", None, ""):
            return float(obs[0]["value"]) / 100.0
    except Exception:
        pass
    return 0.045


def _dcf_fair_values(
    ttm_fcf: float,
    growth_bear: float,
    growth_base: float,
    growth_bull: float,
    discount_rate: float,
    terminal_growth: float = 0.02,
    years: int = 10,
    shares_outstanding: Optional[float] = None,
) -> Tuple[float, float, float]:
    """DCF: terminal value at year 10, Gordon Growth. Returns (bear, base, bull) per share if shares_outstanding given else total equity value."""
    def pv(scenario_growth: float) -> float:
        cf = ttm_fcf
        pv_sum = 0.0
        for t in range(1, years + 1):
            cf = cf * (1 + scenario_growth)
            pv_sum += cf / ((1 + discount_rate) ** t)
        terminal_cf = cf * (1 + terminal_growth)
        terminal_val = terminal_cf / (discount_rate - terminal_growth)
        pv_sum += terminal_val / ((1 + discount_rate) ** years)
        return pv_sum
    bear = pv(growth_bear)
    base = pv(growth_base)
    bull = pv(growth_bull)
    if shares_outstanding and shares_outstanding > 0:
        bear, base, bull = bear / shares_outstanding, base / shares_outstanding, bull / shares_outstanding
    return round(bear, 2), round(base, 2), round(bull, 2)


def _fmp_sector_pe_ev(session, ticker: str) -> Tuple[Optional[float], Optional[float]]:
    """FMP sector P/E and EV/EBITDA medians for comps. Returns (sector_pe, sector_ev_ebitda)."""
    if not FMP_API_KEY:
        return None, None
    try:
        company = session.query(Company).filter(Company.ticker == ticker).first()
        sector = (company.sector or "").replace(" ", "%20")
        r = requests.get(
            f"{FMP_BASE}/v4/sector_price_earning_ratio",
            params={"date": date.today().isoformat(), "exchange": "NYSE", "apikey": FMP_API_KEY},
            timeout=10,
        )
        if r.status_code != 200:
            return None, None
        data = r.json()
        if not data:
            return None, None
        for row in data:
            if row.get("sector") == (company.sector or ""):
                pe = row.get("priceEarningRatio")
                return (float(pe), None) if pe is not None else (None, None)
        pe = data[0].get("priceEarningRatio") if data else None
        return (float(pe), None) if pe is not None else (None, None)
    except Exception:
        return None, None


def _comps_target(session, ticker: str, sector_pe: Optional[float], sector_ev_ebitda: Optional[float]) -> Optional[float]:
    """Apply sector median P/E to company EPS. Apply sector EV/EBITDA to company EBITDA if available. Average the two."""
    company = session.query(Company).filter(Company.ticker == ticker).first()
    if not company or not company.current_price:
        return None
    targets = []
    if sector_pe is not None:
        r = session.execute(
            text("SELECT value FROM edgar_facts WHERE ticker = :t AND tag = 'EarningsPerShareBasic' ORDER BY period_end DESC LIMIT 4"),
            {"t": ticker},
        )
        rows = list(r)
        if rows:
            eps_ttm = sum(row[0] for row in rows if row[0] is not None)
            if eps_ttm and eps_ttm > 0:
                targets.append(sector_pe * eps_ttm)
    if sector_ev_ebitda is not None:
        r = session.execute(
            text("SELECT value FROM edgar_facts WHERE ticker = :t AND tag = 'OperatingIncomeLoss' ORDER BY period_end DESC LIMIT 4"),
            {"t": ticker},
        )
        rows = list(r)
        if rows and company.market_cap:
            ebitda_ttm = sum(row[0] for row in rows if row[0] is not None)
            if ebitda_ttm and ebitda_ttm > 0:
                ev = sector_ev_ebitda * ebitda_ttm
                targets.append(ev / (company.market_cap / company.current_price) if company.current_price else None)
    targets = [t for t in targets if t is not None and t > 0]
    if not targets:
        return None
    return round(sum(targets) / len(targets), 2)


def _mean_reversion_target(session, ticker: str) -> Optional[float]:
    """5Y average P/E from trailing_pe history applied to current EPS."""
    r = session.execute(
        text("""
            SELECT period_end, pe_ratio FROM fundamentals
            WHERE ticker = :t AND pe_ratio IS NOT NULL AND pe_ratio > 0
            ORDER BY period_end DESC LIMIT 20
        """),
        {"t": ticker},
    )
    rows = list(r)
    if len(rows) < 5:
        company = session.query(Company).filter(Company.ticker == ticker).first()
        if company and company.trailing_pe and company.trailing_pe > 0:
            pe_avg = company.trailing_pe
        else:
            return None
    else:
        pe_avg = sum(row[1] for row in rows[:min(20, len(rows))]) / min(20, len(rows))
    r2 = session.execute(
        text("SELECT value FROM edgar_facts WHERE ticker = :t AND tag = 'EarningsPerShareBasic' ORDER BY period_end DESC LIMIT 4"),
        {"t": ticker},
    )
    eps_rows = list(r2)
    if not eps_rows:
        return None
    eps_ttm = sum(row[0] for row in eps_rows if row[0] is not None)
    if not eps_ttm or eps_ttm <= 0:
        return None
    return round(pe_avg * eps_ttm, 2)


def run_valuation_for_ticker(session, ticker: str) -> Optional[Score]:
    """Compute DCF, comps, mean reversion and upsert Score row."""
    company = session.query(Company).filter(Company.ticker == ticker).first()
    if not company:
        return None
    today = date.today()
    # TTM FCF
    r = session.execute(
        text("SELECT value FROM edgar_facts WHERE ticker = :t AND tag = 'NetCashProvidedByUsedInOperatingActivities' ORDER BY period_end DESC LIMIT 4"),
        {"t": ticker},
    )
    fcf_rows = list(r)
    ttm_fcf = sum(row[0] for row in fcf_rows if row[0] is not None) if fcf_rows else None
    if ttm_fcf is None or ttm_fcf <= 0:
        ttm_fcf = company.free_cash_flow or 0
    if ttm_fcf <= 0:
        ttm_fcf = 1.0
    shares = None
    if company.market_cap and company.current_price and company.current_price > 0:
        shares = company.market_cap / company.current_price
    rf = _risk_free_rate_10y()
    discount_rate = rf + 0.055
    growth_base = (company.revenue_cagr_3y or 0) / 100.0 if company.revenue_cagr_3y else 0.05
    bear, base, bull = _dcf_fair_values(ttm_fcf, -0.02, growth_base, growth_base + 0.02, discount_rate, 0.02, 10, shares)
    sector_pe, sector_ev = _fmp_sector_pe_ev(session, ticker)
    comps = _comps_target(session, ticker, sector_pe, sector_ev)
    mean_rev = _mean_reversion_target(session, ticker)
    low = min(x for x in [bear, comps, mean_rev] if x is not None) if any(x for x in [bear, comps, mean_rev] if x is not None) else bear
    high = max(x for x in [bull, comps, mean_rev] if x is not None) if any(x for x in [bull, comps, mean_rev] if x is not None) else bull
    mid = (low + high) / 2
    existing = session.query(Score).filter(Score.ticker == ticker, Score.score_date == today).first()
    if existing:
        existing.dcf_fair_value_low = bear
        existing.dcf_fair_value_mid = base
        existing.dcf_fair_value_high = bull
        existing.comps_target = comps
        existing.mean_reversion_target = mean_rev
        session.flush()
        return existing
    score = Score(
        ticker=ticker,
        score_date=today,
        dcf_fair_value_low=bear,
        dcf_fair_value_mid=base,
        dcf_fair_value_high=bull,
        comps_target=comps,
        mean_reversion_target=mean_rev,
    )
    session.add(score)
    session.flush()
    return score


def _ensure_score_mid_column(engine) -> None:
    from sqlalchemy import text
    with engine.connect() as conn:
        try:
            conn.execute(text('ALTER TABLE scores ADD COLUMN "dcf_fair_value_mid" DOUBLE PRECISION'))
            conn.commit()
        except Exception:
            conn.rollback()


def run_valuation(tickers: Optional[List[str]] = None) -> None:
    """Run valuation for watchlist (or given tickers)."""
    engine, Session = _engine_session()
    _ensure_score_mid_column(engine)
    session = Session()
    try:
        if tickers is None:
            companies = session.query(Company).filter(Company.active == True).all()
            tickers = [c.ticker for c in companies]
        for ticker in tickers:
            try:
                run_valuation_for_ticker(session, ticker)
                print(f"  [OK] {ticker} valuation updated")
            except Exception as e:
                print(f"  [ERROR] {ticker}: {e}")
        session.commit()
        print("[OK] Valuation complete")
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()
