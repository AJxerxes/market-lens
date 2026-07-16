"""
Earnings calendar ingestion.
Pulls upcoming earnings dates and EPS estimates via yfinance.
Updates actuals after earnings release.
"""
from datetime import datetime, date, timedelta, timezone
from typing import List, Optional

import yfinance as yf

from market_lens.database.models import EarningsEvent, Company
from market_lens.ingestion.tracked_funds import _get_session


def ingest_earnings_calendar(tickers: Optional[List[str]] = None) -> None:
    """
    Pull earnings dates and EPS estimates for all watchlist tickers.
    Uses yfinance calendar and earnings_history data.
    """
    session = _get_session()
    try:
        if tickers is None:
            companies = session.query(Company).filter_by(active=True, paused=False).all()
            tickers = [c.ticker for c in companies]

        print(f"[Earnings] Processing {len(tickers)} tickers...")
        inserted = 0
        updated = 0

        for ticker in tickers:
            try:
                yf_ticker = yf.Ticker(ticker)

                # Get upcoming earnings date
                info = getattr(yf_ticker, "info", {}) or {}
                earnings_ts = info.get("earningsTimestamp") or info.get("earningsDate")
                next_earnings = None
                if earnings_ts:
                    try:
                        if isinstance(earnings_ts, (int, float)):
                            next_earnings = datetime.fromtimestamp(earnings_ts, tz=timezone.utc).date()
                        elif isinstance(earnings_ts, (list, tuple)) and earnings_ts:
                            next_earnings = datetime.fromtimestamp(earnings_ts[0], tz=timezone.utc).date()
                    except Exception:
                        next_earnings = None

                eps_estimate = info.get("forwardEps") or info.get("epsForward")
                company_name = info.get("longName") or info.get("shortName") or ticker

                # Insert upcoming earnings if date found
                if next_earnings and next_earnings >= date.today():
                    existing = session.query(EarningsEvent).filter_by(
                        ticker=ticker,
                        earnings_date=next_earnings
                    ).first()

                    if not existing:
                        ev = EarningsEvent(
                            ticker=ticker,
                            company_name=company_name,
                            earnings_date=next_earnings,
                            fiscal_quarter=_estimate_fiscal_quarter(next_earnings),
                            fiscal_year=next_earnings.year,
                            eps_estimate=eps_estimate,
                            confirmed=False,
                            source="yfinance",
                        )
                        session.add(ev)
                        inserted += 1
                    else:
                        if eps_estimate and not existing.eps_estimate:
                            existing.eps_estimate = eps_estimate
                            updated += 1

                # Get historical earnings actuals
                try:
                    earnings_hist = getattr(yf_ticker, "earnings_history", None)
                    if earnings_hist is not None and not earnings_hist.empty:
                        for _, row in earnings_hist.iterrows():
                            try:
                                eq = row.get("Earnings Date") or row.get("earningsDate")
                                if eq is None:
                                    continue
                                if hasattr(eq, "date"):
                                    eq = eq.date()
                                elif isinstance(eq, str):
                                    eq = date.fromisoformat(eq[:10])

                                eps_est = row.get("EPS Estimate") or row.get("epsEstimate")
                                eps_act = row.get("Reported EPS") or row.get("epsActual")

                                surprise = None
                                beat = None
                                if eps_est and eps_act:
                                    try:
                                        est_f = float(eps_est)
                                        act_f = float(eps_act)
                                        if est_f != 0:
                                            surprise = ((act_f - est_f) / abs(est_f)) * 100
                                        beat = act_f >= est_f
                                    except Exception:
                                        surprise = None
                                        beat = None

                                existing_hist = session.query(EarningsEvent).filter_by(
                                    ticker=ticker,
                                    earnings_date=eq,
                                ).first()

                                if not existing_hist:
                                    ev = EarningsEvent(
                                        ticker=ticker,
                                        company_name=company_name,
                                        earnings_date=eq,
                                        fiscal_quarter=_estimate_fiscal_quarter(eq),
                                        fiscal_year=eq.year,
                                        eps_estimate=float(eps_est) if eps_est else None,
                                        eps_actual=float(eps_act) if eps_act else None,
                                        surprise_pct=surprise,
                                        beat=beat,
                                        confirmed=True,
                                        source="yfinance_history",
                                    )
                                    session.add(ev)
                                    inserted += 1
                                else:
                                    changed = False
                                    if eps_act and not existing_hist.eps_actual:
                                        existing_hist.eps_actual = float(eps_act)
                                        changed = True
                                    if surprise is not None:
                                        existing_hist.surprise_pct = surprise
                                        changed = True
                                    if beat is not None:
                                        existing_hist.beat = beat
                                        changed = True
                                    if changed:
                                        updated += 1
                            except Exception:
                                continue
                except Exception:
                    # yfinance earnings history can be flaky; ignore per-ticker failures
                    pass

                session.commit()
                print(f"[Earnings] {ticker}: done")

            except Exception:
                session.rollback()
                print(f"[Earnings] {ticker} failed")
                continue

        print(f"[Earnings] Complete — inserted: {inserted} | updated: {updated}")

    finally:
        session.close()


def _estimate_fiscal_quarter(d: date) -> str:
    """Estimate fiscal quarter label from date."""
    q = (d.month - 1) // 3 + 1
    return f"Q{q} {d.year}"

