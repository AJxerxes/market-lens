"""
Market Lens — Fundamentals Analysis (Phase 4)
Revenue CAGR, gross margin trend, FCF yield, Debt/EBITDA, dividend streak.
"""
from datetime import date, datetime, timezone
from typing import Optional, List, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from market_lens.config import DATABASE_URL
from market_lens.database.models import Base, Company, EdgarFact, Fundamentals


def _engine_session():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    return engine, Session()


def _ensure_company_metrics_columns(engine) -> None:
    from sqlalchemy import text
    cols = [
        ("revenue_cagr_3y", "DOUBLE PRECISION"),
        ("gross_margin_trend", "VARCHAR(20)"),
        ("fcf_yield", "DOUBLE PRECISION"),
        ("debt_ebitda_ratio", "DOUBLE PRECISION"),
        ("dividend_streak_years", "INTEGER"),
    ]
    with engine.connect() as conn:
        for col_name, col_type in cols:
            try:
                conn.execute(text(f'ALTER TABLE companies ADD COLUMN "{col_name}" {col_type}'))
                conn.commit()
            except Exception:
                conn.rollback()
    # Score table: dcf_fair_value_mid
    with engine.connect() as conn:
        try:
            conn.execute(text('ALTER TABLE scores ADD COLUMN "dcf_fair_value_mid" DOUBLE PRECISION'))
            conn.commit()
        except Exception:
            conn.rollback()


def compute_revenue_cagr(session, ticker: str, years: int = 3) -> Optional[float]:
    """Compute revenue CAGR from edgar_facts Revenues. (end/start)^(1/years) - 1."""
    r = session.execute(
        text("""
            SELECT period_end, value FROM edgar_facts
            WHERE ticker = :t AND tag = 'Revenues'
            ORDER BY period_end
        """),
        {"t": ticker},
    )
    rows = list(r)
    if len(rows) < 2:
        return None
    by_date = {row[0]: row[1] for row in rows}
    sorted_dates = sorted(by_date.keys(), reverse=True)
    if years == 3:
        need_span = 4  # need at least 4 annual points for 3Y cagr
    else:
        need_span = years + 1
    annual = []
    seen_years = set()
    for d in sorted_dates:
        y = d.year
        if y not in seen_years:
            annual.append((d, by_date[d]))
            seen_years.add(y)
        if len(annual) >= need_span:
            break
    if len(annual) < 2:
        return None
    end_val = annual[0][1]
    start_val = annual[min(years, len(annual) - 1)][1]
    if start_val is None or start_val == 0:
        return None
    n = min(years, len(annual) - 1)
    if n == 0:
        return None
    return (end_val / start_val) ** (1 / n) - 1.0


def compute_gross_margin_trend(session, ticker: str) -> str:
    """Gross margin = GrossProfit/Revenues per quarter. Last 8 quarters, trend: improving/flat/deteriorating."""
    r = session.execute(
        text("""
            SELECT f.period_end,
                   (SELECT value FROM edgar_facts e WHERE e.ticker = f.ticker AND e.tag = 'GrossProfit' AND e.period_end = f.period_end LIMIT 1) as gp,
                   (SELECT value FROM edgar_facts e WHERE e.ticker = f.ticker AND e.tag = 'Revenues' AND e.period_end = f.period_end LIMIT 1) as rev
            FROM edgar_facts f
            WHERE f.ticker = :t AND f.tag = 'Revenues'
            ORDER BY f.period_end DESC
            LIMIT 8
        """),
        {"t": ticker},
    )
    rows = list(r)
    margins = []
    for row in rows:
        rev = row[2]
        gp = row[1]
        if rev and rev != 0 and gp is not None:
            margins.append(gp / rev)
    if len(margins) < 3:
        return "flat"
    first_avg = sum(margins[-3:]) / 3
    last_avg = sum(margins[:3]) / 3
    if last_avg > first_avg + 0.01:
        return "improving"
    if last_avg < first_avg - 0.01:
        return "deteriorating"
    return "flat"


def compute_fcf_yield(session, ticker: str) -> Optional[float]:
    """FCF / market_cap. FCF from NetCashProvidedByUsedInOperatingActivities minus capex proxy."""
    company = session.query(Company).filter(Company.ticker == ticker).first()
    if not company or not company.market_cap or company.market_cap <= 0:
        return None
    r = session.execute(
        text("""
            SELECT value FROM edgar_facts
            WHERE ticker = :t AND tag = 'NetCashProvidedByUsedInOperatingActivities'
            ORDER BY period_end DESC LIMIT 4
        """),
        {"t": ticker},
    )
    rows = list(r)
    if not rows:
        return None
    ttm_fcf = sum(row[0] for row in rows if row[0] is not None)
    if ttm_fcf is None or ttm_fcf <= 0:
        return None
    return (ttm_fcf / company.market_cap) * 100.0


def compute_debt_ebitda(session, ticker: str) -> Optional[float]:
    """LongTermDebt / (OperatingIncomeLoss + depreciation proxy)."""
    r_debt = session.execute(
        text("SELECT value FROM edgar_facts WHERE ticker = :t AND tag = 'LongTermDebt' ORDER BY period_end DESC LIMIT 1"),
        {"t": ticker},
    )
    r_op = session.execute(
        text("SELECT value FROM edgar_facts WHERE ticker = :t AND tag = 'OperatingIncomeLoss' ORDER BY period_end DESC LIMIT 4"),
        {"t": ticker},
    )
    debt_row = r_debt.fetchone()
    op_rows = list(r_op)
    if not debt_row or debt_row[0] is None:
        return None
    debt = float(debt_row[0])
    op_ttm = sum(row[0] for row in op_rows if row[0] is not None)
    if op_ttm is None or op_ttm <= 0:
        return None
    return debt / op_ttm


def compute_dividend_streak(session, ticker: str) -> int:
    """Count consecutive years of dividend increases from CommonStockDividendsPaidPerShare."""
    r = session.execute(
        text("""
            SELECT fy, SUM(value) as annual FROM edgar_facts
            WHERE ticker = :t AND tag = 'CommonStockDividendsPaidPerShare'
            GROUP BY fy ORDER BY fy DESC
        """),
        {"t": ticker},
    )
    rows = list(r)
    if len(rows) < 2:
        return 0
    # Initialize with the most recent year, then walk backward
    streak = 0
    prev = rows[0][1]
    for row in rows[1:]:
        val = row[1]
        if prev is None or val is None or val <= prev:
            break
        streak += 1
        prev = val
    return streak


def run_fundamentals_for_ticker(session, ticker: str) -> None:
    """Compute all fundamental metrics and update Company."""
    company = session.query(Company).filter(Company.ticker == ticker).first()
    if not company:
        return
    company.revenue_cagr_3y = None
    cagr = compute_revenue_cagr(session, ticker, 3)
    if cagr is not None:
        company.revenue_cagr_3y = round(cagr * 100, 2)
    company.gross_margin_trend = compute_gross_margin_trend(session, ticker)
    company.fcf_yield = compute_fcf_yield(session, ticker)
    company.debt_ebitda_ratio = compute_debt_ebitda(session, ticker)
    company.dividend_streak_years = compute_dividend_streak(session, ticker)
    session.flush()


def run_fundamentals(tickers: Optional[List[str]] = None) -> None:
    """Run fundamentals analysis for watchlist (or given tickers)."""
    engine, session = _engine_session()
    _ensure_company_metrics_columns(engine)
    try:
        if tickers is None:
            companies = session.query(Company).filter(Company.active == True).all()
            tickers = [c.ticker for c in companies]
        for ticker in tickers:
            try:
                run_fundamentals_for_ticker(session, ticker)
                print(f"  [OK] {ticker} fundamentals updated")
            except Exception as e:
                print(f"  [ERROR] {ticker}: {e}")
        session.commit()
        print("[OK] Fundamentals analysis complete")
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()
