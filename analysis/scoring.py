"""
Market Lens — Scoring Engine (Phase 5)
Lynch Score (0-100) and Swing Score. Weights from config. Score override table support.
"""
from datetime import date, datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from market_lens.config import DATABASE_URL, LYNCH_WEIGHTS, SWING_WEIGHTS
from market_lens.database.models import (
    Base,
    Company,
    Score,
    ScoreOverride,
    RecommendationLabel,
    SwingLabel,
)


def _engine_session():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    return engine, Session()


def _get_override(session, ticker: str, field_name: str) -> Optional[float]:
    row = (
        session.query(ScoreOverride)
        .filter(ScoreOverride.ticker == ticker, ScoreOverride.field_name == field_name, ScoreOverride.locked == True)
        .first()
    )
    return float(row.override_value) if row else None


def _component_revenue_growth_3y(session, company: Company) -> float:
    ov = _get_override(session, company.ticker, "revenue_growth_3y_cagr")
    if ov is not None:
        return min(100, max(0, ov))
    cagr = company.revenue_cagr_3y
    if cagr is None:
        return 50.0
    if cagr >= 15:
        return 100.0
    if cagr >= 10:
        return 80.0
    if cagr >= 5:
        return 60.0
    if cagr >= 0:
        return 40.0
    return max(0, 40 + cagr * 2)


def _component_fcf_yield_vs_sector(session, company: Company) -> float:
    ov = _get_override(session, company.ticker, "fcf_yield_vs_sector")
    if ov is not None:
        return min(100, max(0, ov))
    fcf_y = company.fcf_yield
    if fcf_y is None:
        return 50.0
    if fcf_y >= 8:
        return 100.0
    if fcf_y >= 5:
        return 80.0
    if fcf_y >= 3:
        return 60.0
    if fcf_y >= 0:
        return 40.0
    return max(0, 20 + fcf_y * 2)


def _component_pe_vs_own_5y(session, company: Company) -> float:
    ov = _get_override(session, company.ticker, "pe_vs_own_5y_avg")
    if ov is not None:
        return min(100, max(0, ov))
    if company.trailing_pe is None or company.trailing_pe <= 0:
        return 50.0
    return 50.0


def _component_insider_net_buy(session, ticker: str) -> float:
    ov = _get_override(session, ticker, "insider_net_buy")
    if ov is not None:
        return min(100, max(0, ov))
    return 50.0


def _component_gross_margin_trend(session, company: Company) -> float:
    ov = _get_override(session, company.ticker, "gross_margin_trend")
    if ov is not None:
        return min(100, max(0, ov))
    t = (company.gross_margin_trend or "").lower()
    if t == "improving":
        return 85.0
    if t == "deteriorating":
        return 25.0
    return 50.0


def _component_dividend_streak(session, company: Company) -> float:
    ov = _get_override(session, company.ticker, "dividend_growth_streak")
    if ov is not None:
        return min(100, max(0, ov))
    streak = company.dividend_streak_years or 0
    if streak >= 25:
        return 100.0
    if streak >= 10:
        return 80.0
    if streak >= 5:
        return 65.0
    if streak >= 1:
        return 50.0
    return 40.0


def _component_debt_ebitda(session, company: Company) -> float:
    ov = _get_override(session, company.ticker, "debt_ebitda_ratio")
    if ov is not None:
        return max(0, min(100, 100 - ov * 5))
    d = company.debt_ebitda_ratio
    if d is None:
        return 50.0
    if d <= 1:
        return 90.0
    if d <= 2:
        return 70.0
    if d <= 3:
        return 50.0
    return max(0, 50 - (d - 3) * 15)


def _component_leadership_stability(session, ticker: str) -> float:
    ov = _get_override(session, ticker, "leadership_stability")
    if ov is not None:
        return min(100, max(0, ov))
    return 50.0


def _component_supplier_chain_risk(session, ticker: str) -> float:
    ov = _get_override(session, ticker, "supplier_chain_risk")
    if ov is not None:
        return min(100, max(0, ov))
    return 50.0


def _component_news_sentiment_30d(session, ticker: str) -> float:
    return 50.0


def _should_skip_lynch(company: Company) -> bool:
    """Return True if Lynch score should not be computed."""
    if not company:
        return True
    # OTC ADRs often have incomplete flags but can still be scored if market_cap exists
    is_otc = "otc" in str(company.instrument_type or "").lower()
    if is_otc:
        # For OTC just need market_cap at minimum
        return company.market_cap is None
    # For regular equities require complete flag and key fields
    if (company.data_quality_flag or "").lower() != "complete":
        return True
    if company.market_cap is None or company.trailing_pe is None:
        return True
    return False


def compute_lynch_score(session, ticker: str) -> Optional[float]:
    """Compute Lynch score 0-100 from weighted components. Returns None if data is incomplete (e.g. OTC)."""
    company = session.query(Company).filter(Company.ticker == ticker).first()
    if not company:
        return 0.0
    if _should_skip_lynch(company):
        return None
    components = {
        "revenue_growth_3y_cagr": _component_revenue_growth_3y(session, company),
        "fcf_yield_vs_sector": _component_fcf_yield_vs_sector(session, company),
        "pe_vs_own_5y_avg": _component_pe_vs_own_5y(session, company),
        "insider_net_buy": _component_insider_net_buy(session, ticker),
        "gross_margin_trend": _component_gross_margin_trend(session, company),
        "dividend_growth_streak": _component_dividend_streak(session, company),
        "debt_ebitda_ratio": _component_debt_ebitda(session, company),
        "leadership_stability": _component_leadership_stability(session, ticker),
        "supplier_chain_risk": _component_supplier_chain_risk(session, ticker),
        "news_sentiment_30d": _component_news_sentiment_30d(session, ticker),
    }
    total = 0.0
    for key, weight in LYNCH_WEIGHTS.items():
        total += (components.get(key) or 50.0) * weight
    # Weights sum to 1.0; components are 0-100, so total is already 0-100
    return round(min(100.0, max(0.0, total)), 2)


def lynch_label(score: float) -> RecommendationLabel:
    if score >= 80:
        return RecommendationLabel.strong_buy
    if score >= 65:
        return RecommendationLabel.buy
    if score >= 45:
        return RecommendationLabel.watch
    return RecommendationLabel.avoid


def compute_swing_score(session, ticker: str) -> float:
    """Swing score from RSI, options, volume, insider, news. Placeholder components return 50."""
    return 50.0


def swing_label(score: float) -> SwingLabel:
    if score >= 65:
        return SwingLabel.setup_present
    if score >= 40:
        return SwingLabel.monitor
    return SwingLabel.no_signal


def run_scoring_for_ticker(session, ticker: str) -> Optional[Score]:
    today = date.today()
    lynch = compute_lynch_score(session, ticker)
    swing = compute_swing_score(session, ticker)
    rec_label = lynch_label(lynch) if lynch is not None else None
    existing = session.query(Score).filter(Score.ticker == ticker, Score.score_date == today).first()
    if existing:
        existing.lynch_score = lynch
        existing.recommendation_label = rec_label
        existing.swing_score = swing
        existing.swing_label = swing_label(swing)
        session.flush()
        return existing
    score = Score(
        ticker=ticker,
        score_date=today,
        lynch_score=lynch,
        swing_score=swing,
        recommendation_label=rec_label,
        swing_label=swing_label(swing),
    )
    session.add(score)
    session.flush()
    return score


def run_scoring(tickers: Optional[List[str]] = None) -> None:
    """Run Lynch and swing scoring for watchlist (or given tickers)."""
    engine, session = _engine_session()
    Base.metadata.create_all(engine)
    try:
        if tickers is None:
            companies = session.query(Company).filter(Company.active == True).all()
            tickers = [c.ticker for c in companies]
        for ticker in tickers:
            try:
                score = run_scoring_for_ticker(session, ticker)
                lyn = score.lynch_score if score else None
                print(f"  [OK] {ticker} lynch_score={lyn}")
            except Exception as e:
                print(f"  [ERROR] {ticker}: {e}")
        session.commit()
        # Print final scores for verification
        today = date.today()
        for ticker in tickers:
            s = session.query(Score).filter(Score.ticker == ticker, Score.score_date == today).first()
            if s:
                print(f"  {ticker}: lynch_score={s.lynch_score}, recommendation={s.recommendation_label}")
        print("[OK] Scoring complete")
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    import sys
    tickers = sys.argv[1:] if len(sys.argv) > 1 else None
    print("Market Lens — Scoring")
    print("---------------------")
    run_scoring(tickers)
