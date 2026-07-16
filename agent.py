"""
Market Lens — Agent scheduler (Phase 14).

APScheduler runs all ingestion and analysis jobs. Run as a long-lived process;
on Windows can be installed as a service via NSSM (see docs/nssm_setup.md).

Schedule (ET):
- Daily 06:00 ET: prices, fundamentals, scoring, valuation, EDGAR, options, news/nlp.
- Daily 07:00 ET: congress disclosures (FMP), court dockets (CourtListener/PTAB).
- Daily 08:00 ET: tracked funds (13F/ARK), then agent brain (memory + delta + synthesis).
- Saturday 20:00 ET: sector scan + weekly digest.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# Ensure project root on path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from market_lens.config import ensure_directories, LOG_DIR, DISPLAY_TIMEZONE

# ASCII-only logs for Windows
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
if LOG_DIR:
    ensure_directories()
    _log_file = LOG_DIR / "agent.log"
    try:
        logging.getLogger().addHandler(logging.FileHandler(_log_file, encoding="utf-8"))
    except Exception:
        pass

logger = logging.getLogger("market_lens.agent")
ET = pytz.timezone(DISPLAY_TIMEZONE if "America" in str(DISPLAY_TIMEZONE) else "America/New_York")


def _run_prices():
    from market_lens.ingestion.prices import run_prices_ingestion
    run_prices_ingestion()
    logger.info("Prices ingestion finished.")


def _run_fundamentals():
    from market_lens.analysis.fundamentals import run_fundamentals
    run_fundamentals()
    logger.info("Fundamentals finished.")


def _run_scoring():
    from market_lens.analysis.scoring import run_scoring
    run_scoring()
    logger.info("Scoring finished.")


def _run_valuation():
    from market_lens.analysis.valuation import run_valuation
    run_valuation()
    logger.info("Valuation finished.")


def _run_edgar():
    from market_lens.ingestion.edgar import run_edgar_ingestion
    run_edgar_ingestion()
    logger.info("EDGAR ingestion finished.")


def _run_options():
    from market_lens.ingestion.options import run_options_ingestion_for_watchlist
    from market_lens.database.watchlist import WatchlistManager
    with WatchlistManager() as wl:
        tickers = [c.ticker for c in wl.get_watchlist()]
    run_options_ingestion_for_watchlist(tickers or [])
    logger.info("Options ingestion finished.")


def _run_nlp():
    from market_lens.processing.nlp import run_nlp_pipeline
    run_nlp_pipeline()
    logger.info("NLP pipeline finished.")


def _run_congress():
    from market_lens.ingestion.congress_tracker import ingest_house_disclosures, ingest_senate_disclosures
    ingest_house_disclosures()
    ingest_senate_disclosures()
    logger.info("Congress disclosures finished.")


def _run_court_dockets():
    from market_lens.config import DATABASE_URL
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from market_lens.database.models import Company
    from market_lens.ingestion.court_dockets import upsert_court_cases
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        companies = session.query(Company).filter(Company.active == True).all()
        for c in companies:
            name = (c.legal_name or c.name or c.ticker or "").strip()
            if name:
                upsert_court_cases(session, c.ticker, name, from_courtlistener=True, from_ptab=True)
        session.commit()
        logger.info("Court dockets ingestion finished.")
    except Exception as e:
        session.rollback()
        logger.exception("Court dockets failed: %s", e)
    finally:
        session.close()


def _run_tracked_funds():
    from market_lens.ingestion.tracked_funds import run_tracked_funds_ingestion
    run_tracked_funds_ingestion()
    logger.info("Tracked funds ingestion finished.")


def _run_substack_feeds():
    from market_lens.ingestion.substack_reader import run_substack_ingestion
    run_substack_ingestion()
    logger.info("Substack feeds ingestion finished.")


def _run_sector_scan():
    from market_lens.ingestion.sector_scanner import run_sector_scan
    run_sector_scan()
    logger.info("Sector scan finished.")


def _run_daily_digest_morning():
    from market_lens.ingestion.sector_scanner import run_daily_digest
    run_daily_digest(slot="morning")
    logger.info("Daily digest (morning) finished.")


def _run_daily_digest_evening():
    from market_lens.ingestion.sector_scanner import run_daily_digest
    run_daily_digest(slot="evening")
    logger.info("Daily digest (evening) finished.")


def _run_weekly_digest():
    from market_lens.ingestion.sector_scanner import run_weekly_digest
    run_weekly_digest()
    logger.info("Weekly digest finished.")


def _run_daily_chain():
    """06:00 ET: prices -> fundamentals -> scoring -> valuation -> EDGAR -> options -> nlp."""
    _run_prices()
    _run_fundamentals()
    _run_scoring()
    _run_valuation()
    _run_edgar()
    _run_options()
    _run_nlp()


def _run_agent_brain():
    """Run delta detection and synthesis for watchlist tickers (after daily data)."""
    from market_lens.config import DATABASE_URL
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from market_lens.database.models import Company, AgentMemory, AgentCycleLog
    from market_lens.agent.memory import build_signal_history_90d, get_latest_memory, prior_state_from_memory
    from market_lens.agent.delta import detect_delta
    from market_lens.agent.synthesizer import synthesize_change
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        companies = session.query(Company).filter(Company.active == True).all()
        for c in companies:
            ticker = c.ticker
            prior = get_latest_memory(session, ticker)
            delta, should_synth = detect_delta(session, ticker, prior_memory=prior)
            if not should_synth:
                continue
            history_90d = build_signal_history_90d(session, ticker)
            prior_state = prior_state_from_memory(prior)
            thesis = (c.thesis_notes or "")[:2000]
            try:
                synthesis_text = synthesize_change(
                    ticker, thesis, prior_state, delta, history_90d
                )
            except Exception as e:
                logger.warning("Synthesis failed for %s: %s", ticker, e)
                synthesis_text = ""
            session.add(AgentCycleLog(
                ticker=ticker,
                cycle_at=datetime.now(timezone.utc),
                delta_trigger=delta,
                synthesis_text=synthesis_text or None,
                material_flag=bool(delta.get("coincidence") or delta.get("score_change")),
                alert_sent=False,
            ))
        session.commit()
        logger.info("Agent brain cycle finished.")
    except Exception as e:
        session.rollback()
        logger.exception("Agent brain failed: %s", e)
    finally:
        session.close()


def main():
    scheduler = BlockingScheduler(timezone=ET)
    # Daily 06:00 ET
    scheduler.add_job(_run_daily_chain, CronTrigger(hour=6, minute=0, timezone=ET), id="daily_chain")
    # Intraday price quotes every 15 min during market hours
    scheduler.add_job(
        lambda: __import__("market_lens.ingestion.prices", fromlist=["run_intraday_quotes"]).run_intraday_quotes(),
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="0,15,30,45",
            timezone=ET,
        ),
        id="intraday_quotes",
        name="Intraday price quotes (15-min)",
    )
    # Daily 07:00 ET
    scheduler.add_job(_run_congress, CronTrigger(hour=7, minute=0, timezone=ET), id="congress")
    scheduler.add_job(_run_court_dockets, CronTrigger(hour=7, minute=15, timezone=ET), id="court_dockets")
    scheduler.add_job(_run_substack_feeds, CronTrigger(hour=7, minute=0, timezone=ET), id="substack_feeds")
    # Daily 07:00 ET — morning briefing
    scheduler.add_job(_run_daily_digest_morning, CronTrigger(hour=7, minute=0, timezone=ET), id="daily_digest_morning")
    # Daily 19:00 ET — evening briefing
    scheduler.add_job(_run_daily_digest_evening, CronTrigger(hour=19, minute=0, timezone=ET), id="daily_digest_evening")
    # Earnings calendar refresh (Mon/Wed/Fri 07:30 ET)
    scheduler.add_job(
        lambda: __import__("market_lens.ingestion.earnings", fromlist=["ingest_earnings_calendar"]).ingest_earnings_calendar(),
        CronTrigger(day_of_week="mon,wed,fri", hour=7, minute=30, timezone=ET),
        id="earnings_calendar",
        name="Earnings calendar refresh",
    )
    # Short interest refresh (Saturday 08:00 ET)
    scheduler.add_job(
        lambda: __import__("market_lens.ingestion.short_interest", fromlist=["ingest_short_interest"]).ingest_short_interest(),
        CronTrigger(day_of_week="sat", hour=8, minute=0, timezone=ET),
        id="short_interest",
        name="Short interest refresh",
    )
    # Debt maturity schedule refresh (1st of month 09:00 ET)
    scheduler.add_job(
        lambda: __import__("market_lens.ingestion.debt_maturity", fromlist=["ingest_debt_maturities"]).ingest_debt_maturities(),
        CronTrigger(day=1, hour=9, minute=0, timezone=ET),
        id="debt_maturity",
        name="Debt maturity schedule refresh",
    )
    # Daily 08:00 ET
    scheduler.add_job(_run_tracked_funds, CronTrigger(hour=8, minute=0, timezone=ET), id="tracked_funds")
    scheduler.add_job(_run_agent_brain, CronTrigger(hour=8, minute=30, timezone=ET), id="agent_brain")
    # Saturday 20:00 ET — full weekly digest
    scheduler.add_job(_run_sector_scan, CronTrigger(day_of_week="sat", hour=20, minute=0, timezone=ET), id="sector_scan")
    scheduler.add_job(_run_weekly_digest, CronTrigger(day_of_week="sat", hour=20, minute=0, timezone=ET), id="weekly_digest")

    logger.info("Agent scheduler started (ET). Jobs: daily_chain 06:00, congress 07:00, daily_digest 07:00/19:00, tracked_funds 08:00, agent_brain 08:30, sector_scan+weekly_digest Sat 20:00.")
    scheduler.start()


if __name__ == "__main__":
    main()
