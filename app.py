"""
Market Lens "" Streamlit Dashboard (Phase 7)
Run: streamlit run app.py
"""
import streamlit as st
from pathlib import Path
import os

# On Streamlit Community Cloud, config comes from st.secrets rather than a local
# .env file. Bridge it into os.environ so the rest of the codebase (which reads
# config via os.getenv, e.g. market_lens/config.py) works unchanged in both places.
try:
    for _k, _v in st.secrets.items():
        os.environ.setdefault(_k, str(_v))
except Exception:
    pass  # no secrets.toml locally — fine, .env covers it instead

import pandas as pd
import requests
from datetime import date, datetime, timezone, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import plotly.express as px
import plotly.graph_objects as go
import threading
import atexit

from market_lens import config
from market_lens.config import DATABASE_URL, DASHBOARD_BASE_URL, FRED_API_KEY, FMP_API_KEY
from apscheduler.schedulers.background import BackgroundScheduler
from market_lens.agent.llm_client import summarize_low_stakes
from market_lens.database.models import (
    Base,
    Company,
    Score,
    PriceHistory,
    Fundamentals,
    AgentCycleLog,
    SupplierRegistry,
    LeadershipEvent,
    SectorScanResult,
    WeeklyDigest,
    CongressTrade,
    CommitteeSectorMap,
    TrackedFund,
    FundPosition,
    FundPositionDelta,
    LobbyingRegistration,
    CommitteeHearing,
    SubstackFeed,
    SubstackPost,
    ResearchRadar,
)
from market_lens.database.watchlist import WatchlistManager
from market_lens.ingestion.prices import run_prices_ingestion
from market_lens.analysis.fundamentals import run_fundamentals
from market_lens.analysis.valuation import run_valuation
from market_lens.analysis.scoring import run_scoring
from market_lens.recommendation.engine import generate_recommendation_card
from market_lens.alerts.notifier import send_telegram, send_email, format_telegram_alert
from market_lens.ingestion.congress_tracker import (
    ingest_house_disclosures,
    ingest_senate_disclosures,
    compute_recent_trading_activity,
    get_congress_hearing_timeline,
    compute_convergence_signals,
)
from market_lens.ingestion.substack_reader import run_substack_ingestion_for_single_feed
from market_lens.ingestion.tracked_funds import ensure_tracked_funds_seeded, run_tracked_funds_ingestion
from market_lens.ingestion.earnings import ingest_earnings_calendar

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)


def _session():
    return Session()


def fmt_millions(value):
    """Format a value stored in millions. Shows as $XB if >= 1000, else $XM. Uses dots as thousand separators."""
    if value is None:
        return "-"
    if value >= 1000:
        billions = value / 1000
        return f"${billions:,.2f}B".replace(",", ".")
    return f"${value:,.0f}M".replace(",", ".")


@st.cache_data(ttl=3600)
def _cached_macro_snapshot():
    from market_lens.processing.nlp import fetch_macro_news_snapshot
    return fetch_macro_news_snapshot()


# ---------------------------------------------------------------------------
# Startup ingestion: run once per browser session (background thread)
# ---------------------------------------------------------------------------

def _run_startup_ingestion():
    try:
        from market_lens.ingestion.prices import run_prices_for_all
        from market_lens.ingestion.edgar import run_edgar_for_all
        from market_lens.ingestion.congress_tracker import (
            ingest_house_disclosures,
            ingest_senate_disclosures,
        )
        from market_lens.ingestion.tracked_funds import run_tracked_funds_ingestion
        from market_lens.ingestion.substack_reader import run_substack_ingestion
        from market_lens.ingestion.sector_scanner import run_sector_scan

        print("[STARTUP] Running prices...")
        run_prices_for_all()
        print("[STARTUP] Running EDGAR...")
        run_edgar_for_all()
        print("[STARTUP] Running congressional...")
        ingest_house_disclosures()
        ingest_senate_disclosures()
        print("[STARTUP] Running tracked funds...")
        run_tracked_funds_ingestion()
        print("[STARTUP] Running substack...")
        run_substack_ingestion()
        print("[STARTUP] Running sector scan...")
        run_sector_scan()
        print("[STARTUP] All ingestion complete.")
    except Exception as e:
        print(f"[STARTUP ERROR] {e}")


if "startup_ingestion_done" not in st.session_state:
    st.session_state.startup_ingestion_done = True
    st.session_state["last_refresh"] = "Running in background..."
    t = threading.Thread(target=_run_startup_ingestion, daemon=True)
    t.start()


st.set_page_config(page_title="Market Lens", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');

/* Base */
html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

/* Title */
h1 {
    font-size: 1.6rem !important;
    font-weight: 600 !important;
    color: #c8842a !important;
    letter-spacing: -0.02em;
}

h2, h3, h4 {
    font-weight: 500 !important;
    color: #c8842a !important;
}

/* Insight cards */
.insight-card {
    background: #fff;
    border-left: 3px solid #c8842a;
    border-radius: 6px;
    padding: 14px 18px;
    margin-bottom: 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07);
}

.insight-card .label {
    font-size: 0.68rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #c8842a;
    margin-bottom: 4px;
}

.insight-card .text {
    font-size: 0.92rem;
    color: #1a1a1a;
    line-height: 1.5;
}

.insight-card.risk { border-left-color: #d94f4f; }
.insight-card.risk .label { color: #d94f4f; }

.insight-card.watch { border-left-color: #c8842a; }
.insight-card.watch .label { color: #c8842a; }

.insight-card.positive { border-left-color: #2a9d5c; }
.insight-card.positive .label { color: #2a9d5c; }

/* Metric tiles */
.metric-row {
    display: flex;
    gap: 12px;
    margin-bottom: 20px;
}

.metric-tile {
    flex: 1;
    background: #f8f7f4;
    border-radius: 8px;
    padding: 16px;
    text-align: center;
}

.metric-tile .val {
    font-family: 'DM Mono', monospace;
    font-size: 1.4rem;
    font-weight: 500;
    color: #1a1a1a;
}

.metric-tile .lbl {
    font-size: 0.72rem;
    color: #888;
    margin-top: 2px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

/* Tab styling */
.stTabs [data-baseweb="tab"] {
    font-size: 0.82rem;
    font-weight: 500;
    padding: 8px 16px;
}

/* Sidebar */
.css-1d391kg { background: #f8f7f4; }

/* Dataframe */
.stDataFrame { font-size: 0.82rem; }

/* Expander */
.streamlit-expanderHeader {
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    color: #444 !important;
}
</style>
""", unsafe_allow_html=True)

st.title("Market Lens - Peter Lynch Research")

st.sidebar.markdown("---")
st.sidebar.markdown("### Controls")
if st.sidebar.button("Force Refresh All Data", type="primary"):
    with st.spinner("Running all ingestion jobs..."):
        try:
            import threading
            from market_lens.ingestion.prices import run_prices_for_all
            from market_lens.ingestion.edgar import run_edgar_for_all
            from market_lens.ingestion.congress_tracker import ingest_house_disclosures, ingest_senate_disclosures
            from market_lens.ingestion.tracked_funds import run_tracked_funds_ingestion
            from market_lens.ingestion.short_interest import ingest_short_interest
            from market_lens.ingestion.substack_reader import run_substack_ingestion
            from market_lens.ingestion.sector_scanner import run_sector_scan
            from market_lens.ingestion.debt_maturity import ingest_debt_maturities

            run_prices_for_all()
            run_edgar_for_all()

            def _run_congress_thread():
                try:
                    ingest_house_disclosures()
                    ingest_senate_disclosures()
                except Exception:
                    pass

            congress_thread = threading.Thread(target=_run_congress_thread, daemon=True)
            congress_thread.start()
            congress_thread.join(timeout=120)

            ingest_earnings_calendar()
            run_tracked_funds_ingestion()
            ingest_short_interest()
            ingest_debt_maturities()
            run_substack_ingestion()
            run_sector_scan()

            ts = datetime.now().strftime("%Y-%m-%d %H:%M ET")
            st.session_state["last_refresh"] = ts
            st.sidebar.success("All data refreshed.")
            st.rerun()
        except OSError:
            pass
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            st.sidebar.error(f"Refresh error: {e}")
            with st.sidebar.expander("Full traceback (for Errno 22 / path errors)"):
                st.code(tb, language="text")

st.sidebar.caption(f"Last refresh: {st.session_state.get('last_refresh', 'Not yet this session')}")

st.sidebar.markdown("---")
if st.sidebar.button("Refresh Congress & Hearings", type="secondary"):
    st.sidebar.info(
        "Run this in PowerShell to refresh congressional data:\n\n"
        "cd 'C:\\Users\\User\\.cursor\\worktrees\\Market_Lens\\avi'\n"
        ".\\venv\\Scripts\\python.exe -c \""
        "from market_lens.ingestion.congress_tracker import ingest_house_disclosures, ingest_senate_disclosures, update_hearing_schedule; "
        "ingest_house_disclosures(); ingest_senate_disclosures(); "
        "update_hearing_schedule(119, 'house'); update_hearing_schedule(119, 'senate')\""
    )

st.sidebar.caption(f"Last congress refresh: {st.session_state.get('last_congress_refresh', 'Not yet this session')}")

if st.sidebar.button("Run Briefing Now", key="sidebar_run_briefing"):
    with st.spinner("Running daily briefing..."):
        try:
            from market_lens.ingestion.sector_scanner import run_daily_digest
            run_daily_digest(slot="evening")
            st.sidebar.success("Briefing generated.")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"Briefing error: {e}")


# ---------------------------------------------------------------------------
# Background auto-refresh every 2 hours
# ---------------------------------------------------------------------------


def run_all_ingestion():
    """Used by background scheduler to refresh all data."""
    try:
        from market_lens.ingestion.prices import run_prices_for_all
        from market_lens.ingestion.edgar import run_edgar_for_all
        from market_lens.ingestion.congress_tracker import (
            ingest_house_disclosures,
            ingest_senate_disclosures,
        )
        from market_lens.ingestion.tracked_funds import run_tracked_funds_ingestion
        from market_lens.ingestion.substack_reader import run_substack_ingestion
        from market_lens.ingestion.short_interest import ingest_short_interest

        run_prices_for_all()
        run_edgar_for_all()
        ingest_earnings_calendar()
        ingest_house_disclosures()
        ingest_senate_disclosures()
        run_tracked_funds_ingestion()
        ingest_short_interest()
        run_substack_ingestion()
    except Exception as e:
        print(f"[ERROR] Background ingestion failed: {e}")


if "scheduler_started" not in st.session_state:
    st.session_state.scheduler_started = True
    scheduler = BackgroundScheduler(timezone="America/New_York")
    scheduler.add_job(run_all_ingestion, "interval", hours=2, id="auto_refresh")
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "Today's Brief",
    "My Watchlist", 
    "Deep Dive",
    "Market Signals",
    "Congress & Funds",
    "Macro & Sectors",
    "System",
])


def _render_quick_add(prefix: str) -> None:
    """Shared quick-add widget: search first, confirm the real company, then add."""
    st.caption(
        "Quick add to watchlist (equities, ETFs, mutual funds; background backfill runs after add)."
    )
    q = st.text_input(
        "Ticker or company/fund name",
        key=f"{prefix}_add_input",
        placeholder="e.g. AAPL, SPY, or 'Vanguard Total World'",
    )

    result_key = f"{prefix}_search_result"
    searched_query_key = f"{prefix}_searched_query"

    # A new/changed query invalidates any previous search result.
    if st.session_state.get(searched_query_key) != q:
        st.session_state.pop(result_key, None)

    if st.button("Search", key=f"{prefix}_search_btn"):
        if not q or not q.strip():
            st.warning("Enter a ticker or name.")
        else:
            with st.spinner("Searching..."):
                st.session_state[result_key] = WatchlistManager().search_ticker(q.strip())
                st.session_state[searched_query_key] = q

    search_result = st.session_state.get(result_key)
    if search_result:
        if search_result.get("error"):
            st.error(search_result["error"])
        else:
            matches = search_result.get("matches") or []
            options = {
                f"{m['ticker']} — {m['name']} ({m.get('exchange') or 'Unknown'})": m
                for m in matches
            }
            choice = st.radio(
                "Confirm this is the company/fund you meant:",
                list(options.keys()),
                key=f"{prefix}_confirm_choice",
            )
            thesis = st.text_input(
                "Optional thesis / notes",
                key=f"{prefix}_add_thesis",
                placeholder="Why this belongs on your Lynch list (optional)",
            )
            if st.button("Confirm & Add to Watchlist", key=f"{prefix}_add_btn", type="primary"):
                selected = options[choice]
                with st.spinner(f"Adding {selected['ticker']}..."):
                    try:
                        add_result = WatchlistManager().add_ticker(
                            selected["ticker"],
                            thesis_notes=thesis.strip() or None,
                            force=True,
                        )
                        if add_result.get("status") == "error":
                            st.error(add_result.get("error", "Add to watchlist failed."))
                        else:
                            st.success(add_result.get("message", f"{selected['ticker']} on watchlist."))
                            st.session_state.pop(result_key, None)
                            st.session_state.pop(searched_query_key, None)
                    except Exception as e:
                        st.error(f"Add to watchlist failed: {e}")


with tab1:
    st.markdown("### What matters today")
    st.caption(f"Market Lens research summary - {datetime.now().strftime('%A, %B %d %Y')}")
    
    # --- Generate insight cards ---
    insights = []
    
    session = _session()
    try:
        # Debt risk flags
        from market_lens.database.models import DebtMaturity, EarningsEvent
        from datetime import date as _d, timedelta as _td
        
        current_year = _d.today().year
        near_term_debt = session.query(DebtMaturity).filter(
            DebtMaturity.maturity_year <= current_year + 2
        ).all()
        
        debt_by_ticker = {}
        for d in near_term_debt:
            if d.ticker not in debt_by_ticker:
                debt_by_ticker[d.ticker] = []
            debt_by_ticker[d.ticker].append(d)
        
        # Only flag top 2 debt risks - highest total near-term debt only
        debt_risks = []
        for ticker, maturities in debt_by_ticker.items():
            total = sum(m.amount_millions or 0 for m in maturities)
            debt_risks.append((ticker, maturities, total))

        debt_risks.sort(key=lambda x: x[2], reverse=True)
        for ticker, maturities, total in debt_risks[:2]:
            if total > 5000:
                insights.append({
                    "type": "risk",
                    "label": "Debt Risk",
                    "text": f"{ticker} has {fmt_millions(total)} in debt maturing by {current_year + 2}. High refinancing risk if rates stay elevated."
                })
            elif len(maturities) >= 5:
                insights.append({
                    "type": "watch",
                    "label": "Debt Watch",
                    "text": f"{ticker} has {len(maturities)} separate debt maturities coming due within 2 years. Monitor refinancing activity."
                })

        # Upcoming earnings
        upcoming_earn = session.query(EarningsEvent).filter(
            EarningsEvent.earnings_date >= _d.today(),
            EarningsEvent.earnings_date <= _d.today() + _td(days=14)
        ).all()
        for e in upcoming_earn:
            est_str = f" - consensus EPS ${e.eps_estimate:.2f}" if e.eps_estimate else ""
            insights.append({
                "type": "watch",
                "label": "Earnings Upcoming",
                "text": f"{e.ticker} reports {e.earnings_date.strftime('%b %d')}{est_str}. Watch for guidance revision."
            })
        
        # High short interest flags - only top 3 most shorted, above 15% float
        from market_lens.database.models import Company
        high_short = session.query(Company).filter(
            Company.short_percent_float > 15,
            Company.active == True,
            Company.paused == False
        ).order_by(Company.short_percent_float.desc()).limit(3).all()
        for c in high_short:
            insights.append({
                "type": "watch",
                "label": "Elevated Short Interest",
                "text": f"{c.ticker} short float at {c.short_percent_float:.1f}% with {c.short_ratio:.1f} days to cover. Market skepticism is high - verify your thesis."
            })
        
        # Insider clusters
        try:
            from market_lens.analysis.insider_clusters import detect_insider_clusters
            clusters = detect_insider_clusters(lookback_days=60, min_insiders=2, min_transactions=2)
            for cl in clusters[:2]:
                insights.append({
                    "type": "positive",
                    "label": "Insider Buying Cluster",
                    "text": f"{cl['ticker']}: {cl['unique_insiders']} insiders bought shares in the last 60 days ({cl['total_transactions']} transactions). Strong internal conviction signal."
                })
        except Exception:
            pass

    finally:
        session.close()
    
    # Cap at 6 most important insights
    insights = insights[:6]

    if insights:
        for ins in insights:
            card_class = ins["type"]
            st.markdown(f"""
            <div class="insight-card {card_class}">
                <div class="label">{ins['label']}</div>
                <div class="text">{ins['text']}</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No flags today. Run Force Refresh to generate insights.")
    
    # Macro Pulse
    st.markdown("---")
    st.subheader("Macro Pulse")
    st.caption("Latest macro headlines across energy, geopolitics, finance, technology, and economy.")
    try:
        macro = _cached_macro_snapshot()
        if "error" in macro:
            st.info(f"Macro news unavailable: {macro['error']}")
        else:
            articles = macro.get("articles", [])[:6]
            if articles:
                for art in articles:
                    sentiment = art.get("sentiment_label", "neutral")
                    score = art.get("sentiment_score", 0.0)
                    color = "#2a9d5c" if sentiment == "positive" else "#d94f4f" if sentiment == "negative" else "#888888"
                    theme = art.get("theme", "").replace("_", " ").title()
                    pub = str(art.get("published_at", ""))[:10]
                    title = art.get("title", "")
                    url = art.get("url", "#")
                    source = art.get("source", "")
                    st.markdown(
                        f"<div class='insight-card' style='border-left: 4px solid {color}; margin-bottom: 8px'>"
                        f"<small style='color:{color}'>{theme} &nbsp;|&nbsp; {sentiment} ({score:+.2f})</small><br>"
                        f"<a href='{url}' target='_blank' style='color: inherit'>{title}</a><br>"
                        f"<small style='color:#888'>{source} &mdash; {pub}</small>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No macro news yet. Run Force Refresh to populate.")
    except Exception as e:
        st.caption(f"Macro news unavailable: {e}")
    
    # --- Summary metrics row ---
    st.markdown("---")
    session2 = _session()
    try:
        from market_lens.database.models import Company, EarningsEvent, DebtMaturity, CommitteeHearing
        from datetime import date as _d, timedelta as _td

        total_watched = session2.query(Company).filter_by(active=True, paused=False).count()
        upcoming_count = session2.query(EarningsEvent).filter(
            EarningsEvent.earnings_date >= _d.today(),
            EarningsEvent.earnings_date <= _d.today() + _td(days=30)
        ).count()
        current_year = _d.today().year
        debt_count = session2.query(DebtMaturity).filter(
            DebtMaturity.maturity_year <= current_year + 2
        ).count()
        hearing_count = session2.query(CommitteeHearing).filter(
            CommitteeHearing.hearing_date >= datetime.now()
        ).count()
    finally:
        session2.close()

    st.markdown(f"""
    <div class="metric-row">
        <div class="metric-tile"><div class="val">{total_watched}</div><div class="lbl">Watching</div></div>
        <div class="metric-tile"><div class="val">{upcoming_count}</div><div class="lbl">Earnings in 30d</div></div>
        <div class="metric-tile"><div class="val">{debt_count}</div><div class="lbl">Near-term maturities</div></div>
        <div class="metric-tile"><div class="val">{hearing_count}</div><div class="lbl">Upcoming hearings</div></div>
    </div>
    """, unsafe_allow_html=True)

# ----- Tab 2: My Watchlist -----
with tab2:
    st.subheader("My Watchlist")
    _render_quick_add("tab2")

    with engine.connect() as conn:
        df = pd.read_sql(
            text(
                """
            SELECT
                c.ticker,
                c.name,
                c.current_price,
                c.data_quality_flag,
                c.short_ratio,
                c.short_percent_float,
                s.lynch_score,
                s.recommendation_label,
                s.swing_label,
                s.score_date
            FROM companies c
            LEFT JOIN LATERAL (
                SELECT *
                FROM scores s2
                WHERE s2.ticker = c.ticker
                ORDER BY s2.score_date DESC
                LIMIT 1
            ) s ON true
            WHERE c.active = true
            ORDER BY c.ticker
            """
            ),
            conn,
        )

    if df.empty:
        st.info("No companies in watchlist yet. Use the quick add above.")
    else:
        df = df.rename(
            columns={
                "short_ratio": "days_to_cover",
                "short_percent_float": "short_%_float",
            }
        )
        if "short_%_float" in df.columns:
            df["short_%_float"] = df["short_%_float"].apply(
                lambda x: f"{x:.1f}%" if pd.notna(x) and x else "—"
            )
        if "days_to_cover" in df.columns:
            df["days_to_cover"] = df["days_to_cover"].apply(
                lambda x: f"{x:.1f}d" if pd.notna(x) and x else "—"
            )
        st.dataframe(df, width="stretch")

        col_rm_sel, col_rm_btn = st.columns([3, 1], vertical_alignment="bottom")
        with col_rm_sel:
            rm_ticker = st.selectbox(
                "Remove from watchlist", df["ticker"].tolist(), key="tab2_remove_select"
            )
        with col_rm_btn:
            if st.button("Remove", key="tab2_remove_btn") and rm_ticker:
                result = WatchlistManager().remove_ticker(rm_ticker)
                if result.get("status") == "not_found":
                    st.error(result.get("message"))
                else:
                    st.success(result.get("message"))
                    st.rerun()


# ----- Tab 3: Deep Dive -----
with tab3:
    st.subheader("Deep Dive")
    _render_quick_add("tab3")
    session = _session()
    companies = session.query(Company).filter(Company.active == True).all()
    session.close()
    tickers = [c.ticker for c in companies]
    if not tickers:
        st.info("No watchlist companies.")
    else:
        selected = st.selectbox("Select company", tickers, format_func=lambda t: next((c.name for c in companies if c.ticker == t), t))
        if selected:
            col_btn, col_status = st.columns([2, 3])
            with col_btn:
                if st.button("Run Full Analysis", key="tab3_run_analysis", type="primary"):
                    with st.spinner(f"Running full pipeline for {selected}..."):
                        try:
                            from market_lens.ingestion.prices import run_prices_ingestion
                            from market_lens.analysis.fundamentals import run_fundamentals
                            from market_lens.analysis.valuation import run_valuation
                            from market_lens.analysis.scoring import run_scoring
                            from market_lens.ingestion.edgar import run_edgar_ingestion
                            run_prices_ingestion([selected])
                            run_fundamentals([selected])
                            run_valuation([selected])
                            run_scoring([selected])
                            run_edgar_ingestion([selected])
                            st.session_state[f"analysis_ran_{selected}"] = True
                            col_status.success(f"Analysis complete for {selected}. Results updated below.")
                            st.rerun()
                        except Exception as e:
                            import traceback
                            col_status.error(f"Pipeline error: {e}")
                            with col_status.expander("Traceback"):
                                st.code(traceback.format_exc())

            with engine.connect() as conn:
                hist = pd.read_sql(text("SELECT date, open, high, low, close, volume FROM price_history WHERE ticker = :t ORDER BY date"), conn, params={"t": selected})

            if hist.empty and not st.session_state.get(f"analysis_ran_{selected}"):
                st.info(f"No data yet for {selected}. Click 'Run Full Analysis' to pull price history, fundamentals, and generate a Lynch score.")

            if not hist.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=hist["date"], y=hist["close"], name="Close", line=dict(color="blue")))
                hist["ma50"] = hist["close"].rolling(50).mean()
                hist["ma200"] = hist["close"].rolling(200).mean()
                fig.add_trace(go.Scatter(x=hist["date"], y=hist["ma50"], name="50 MA", line=dict(color="orange", dash="dash")))
                fig.add_trace(go.Scatter(x=hist["date"], y=hist["ma200"], name="200 MA", line=dict(color="gray", dash="dot")))
                fig.update_layout(title=f"{selected} - Price", xaxis_title="Date", yaxis_title="Price", height=400)
                st.plotly_chart(fig, width="stretch")
            with engine.connect() as conn:
                score = pd.read_sql(text("SELECT * FROM scores WHERE ticker = :t ORDER BY score_date DESC LIMIT 1"), conn, params={"t": selected})
            if not score.empty:
                row = score.iloc[0]
                st.metric("Lynch Score", row.get("lynch_score"), None)
                st.metric("Recommendation", row.get("recommendation_label"), None)
                lo, mi, hi = row.get("dcf_fair_value_low"), row.get("dcf_fair_value_mid"), row.get("dcf_fair_value_high")
                st.metric("Fair Value Low / Mid / High", f"{lo} / {mi} / {hi}" if pd.notna(lo) else "", None)
            company = next((c for c in companies if c.ticker == selected), None)
            if company and company.data_quality_flag == "incomplete":
                if company.instrument_type and "otc" in str(company.instrument_type).lower():
                    st.info("Limited data available - this is a foreign OTC-traded security. Core metrics may be incomplete.")
                else:
                    st.warning("[INCOMPLETE DATA] Some fundamental fields are missing for this ticker.")

# ----- Tab 4: Market Signals -----
with tab4:
    st.subheader("Screening Tool")
    st.caption("On-demand company analysis: resolve ticker, add to watchlist, run pipeline, and show Claude rationale.")
    screen_input = st.text_input("Enter ticker or company name", placeholder="e.g. AAPL or Apple")
    thesis_notes = st.text_area("Optional thesis / notes", value="", height=80)
    if st.button("Run analysis"):
        if not screen_input or not screen_input.strip():
            st.warning("Enter a ticker or company name.")
        else:
            with st.spinner("Resolving ticker and running pipeline..."):
                resolved_ticker = None
                try:
                    wl = WatchlistManager()
                    search_result = wl.search_ticker(screen_input.strip())
                    if search_result.get("error"):
                        st.error(search_result["error"])
                    elif not search_result.get("resolved_ticker"):
                        st.error("No match found. Check ticker symbol or try company name (FMP_API_KEY may be required for name search).")
                    elif search_result.get("resolved_ticker"):
                        resolved_ticker = search_result["resolved_ticker"]
                        matches = search_result.get("matches") or []
                        if matches:
                            first = matches[0]
                            st.caption(f"Resolved: {first.get('ticker')} "" {first.get('name')} ({first.get('exchange')}, {first.get('sector')})")
                except Exception as e:
                    st.error(f"Search failed: {e}")

                if resolved_ticker:
                    try:
                        add_result = wl.add_ticker(resolved_ticker, thesis_notes=thesis_notes.strip() or None, force=True)
                        if add_result.get("status") == "error":
                            st.error(add_result.get("error", "Add to watchlist failed."))
                            add_result = None
                        else:
                            st.info(add_result.get("message", f"{resolved_ticker} on watchlist."))
                    except Exception as e:
                        st.error(f"Add to watchlist failed: {e}")
                        add_result = None
                    if add_result and add_result.get("status") in ("added", "already_exists", "reactivated"):
                        try:
                            run_prices_ingestion([resolved_ticker])
                            run_fundamentals([resolved_ticker])
                            run_valuation([resolved_ticker])
                            run_scoring([resolved_ticker])
                        except Exception as e:
                            st.error(f"Pipeline failed: {e}")

                        sess = _session()
                        try:
                            company = sess.query(Company).filter(Company.ticker == resolved_ticker).first()
                            current_price = float(company.current_price) if company and company.current_price is not None else None
                        except Exception:
                            current_price = None
                        finally:
                            sess.close()

                        try:
                            card = generate_recommendation_card(resolved_ticker, current_price)
                        except Exception as e:
                            card = None
                            st.error(f"Recommendation engine failed (check ANTHROPIC_API_KEY): {e}")

                        if card:
                            st.success(f"Analysis complete: {card.ticker} "" {card.name}")

                            # Fetch full score row for richer targets (DCF band, comps, mean reversion)
                            with engine.connect() as conn:
                                score_row = pd.read_sql(
                                    text(
                                        "SELECT * FROM scores WHERE ticker = :t ORDER BY score_date DESC LIMIT 1"
                                    ),
                                    conn,
                                    params={"t": resolved_ticker},
                                )
                            dcf_lo = dcf_mid = dcf_hi = comps_target = mean_rev = None
                            if not score_row.empty:
                                r = score_row.iloc[0]
                                dcf_lo = r.get("dcf_fair_value_low")
                                dcf_mid = r.get("dcf_fair_value_mid")
                                dcf_hi = r.get("dcf_fair_value_high")
                                comps_target = r.get("comps_target")
                                mean_rev = r.get("mean_reversion_target")

                            current = card.current_price or 0.0
                            upside_to_dcf_hi = (
                                ((dcf_hi - current) / current * 100.0) if current and dcf_hi else None
                            )
                            downside_to_dcf_lo = (
                                ((current - dcf_lo) / current * 100.0) if current and dcf_lo else None
                            )

                            c1, c2, c3 = st.columns(3)
                            with c1:
                                st.metric(
                                    "Current Price",
                                    f"{card.current_price:.2f}" if card.current_price is not None else "",
                                )
                                if dcf_mid is not None:
                                    st.metric("DCF Mid Target", f"{dcf_mid:.2f}")
                            with c2:
                                st.metric("Lynch Score", card.lynch_score, None)
                                st.metric("Recommendation", card.recommendation_label or "", None)
                                if upside_to_dcf_hi is not None:
                                    st.metric("Upside to DCF High", f"{upside_to_dcf_hi:.1f}%")
                            with c3:
                                if dcf_lo is not None and dcf_hi is not None:
                                    st.metric(
                                        "DCF Fair Value Band",
                                        f"{dcf_lo:.2f} - {dcf_hi:.2f}",
                                    )
                                if comps_target is not None:
                                    st.metric("Comps Target", f"{comps_target:.2f}")
                                if mean_rev is not None:
                                    st.metric("Mean Reversion Target", f"{mean_rev:.2f}")
                                if downside_to_dcf_lo is not None:
                                    st.metric("Downside to DCF Low", f"{downside_to_dcf_lo:.1f}%")

                            if card.rationale_text:
                                st.subheader("Claude rationale")
                                st.write(card.rationale_text)
                        else:
                            st.warning("Pipeline ran; no recommendation card (missing score or ANTHROPIC_API_KEY).")

# ----- Tab 4: Market Signals -----
def _fetch_fred_series(series_id: str, limit: int = 60):
    """Fetch FRED series observations. Returns (dates, values) or (None, None) on failure."""
    if not FRED_API_KEY:
        return None, None
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            },
            timeout=15,
        )
        if r.status_code != 200:
            return None, None
        data = r.json()
        obs = data.get("observations") or []
        dates = [o["date"] for o in obs if o.get("value") != "."]
        values = [float(o["value"]) for o in obs if o.get("value") != "."]
        return (dates[::-1], values[::-1]) if dates else (None, None)
    except Exception:
        return None, None

with tab6:
    st.subheader("Macro Dashboard")
    st.caption("FRED indicators and macro intelligence. Data is live when FRED_API_KEY and NEWSAPI_KEY are set.")
    if not FRED_API_KEY:
        st.error("FRED_API_KEY is not set. Add it to .env to show macro charts and latest values.")
    else:
        series_config = [
            ("FEDFUNDS", "Fed Funds Rate (%)"),
            ("CPIAUCSL", "CPI All Urban"),
            ("T10Y2Y", "10Y""2Y Treasury Spread (%)"),
            ("UMCSENT", "U Mich Consumer Sentiment"),
        ]
        macro_snapshot = []
        for sid, label in series_config:
            dates, values = _fetch_fred_series(sid, 36)
            if dates and values:
                macro_snapshot.append(f"{label}: latest {values[-1]:.2f} (as of {dates[-1]})")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=dates, y=values, mode="lines+markers", name=label))
                fig.update_layout(title=label, xaxis_title="Date", height=220, margin=dict(t=40, b=40))
                st.plotly_chart(fig, width="stretch")
            else:
                st.warning(f"{label} ({sid}): No data returned. Check series ID or API rate limits.")
        if macro_snapshot:
            summary_prompt = "You are a concise macro analyst. In 2""3 short paragraphs, summarize what the current Fed funds rate, CPI, yield curve (10Y""2Y), and consumer sentiment imply for equities and recession risk. No disclaimers."
            if st.button("Summarize with Claude (Haiku)"):
                try:
                    snapshot_text = "\n".join(macro_snapshot)
                    summary = summarize_low_stakes(summary_prompt, snapshot_text, max_tokens=500)
                    st.subheader("Macro summary")
                    st.write(summary)
                except Exception as e:
                    st.error(f"Claude summary failed: {e}. Check ANTHROPIC_API_KEY.")

    # Market Intelligence "" NewsAPI + FinBERT + Claude Haiku
    st.subheader("Market Intelligence (last 24h)")
    st.caption(
        "Click to run a live macro scan across energy, geopolitics, finance, technology, and economy. Uses MarketAux + Claude Haiku."
    )
    if st.button("Refresh intelligence"):
        with st.spinner("Fetching macro news and running sentiment..."):
            try:
                from market_lens.processing.nlp import fetch_macro_news_snapshot
                snap = fetch_macro_news_snapshot()
            except Exception as e:
                st.error(f"Failed to fetch macro news snapshot: {e}")
                snap = None
        if snap:
            if snap.get("error"):
                st.error(f"Market intelligence unavailable: {snap['error']}")
            else:
                import json

                system_prompt = (
                    "You are a macro analyst. Based on these news headlines and their sentiment scores, "
                    "identify the most important macro developments an individual investor should be aware of today. "
                    "For each development specify: (1) which sector is most affected; "
                    "(2) whether the development is positive, negative, or neutral for equities in that sector; "
                    "(3) 2-3 sentences of reasoning tied to the headlines and sentiment. "
                    "Work with whatever headlines are available. Avoid generic caveats."
                )
                themes = snap.get("themes", {})
                compact = {
                    "from_datetime": snap.get("from_datetime"),
                    "themes": [
                        {
                            "theme": k,
                            "avg_sentiment": v.get("avg_sentiment"),
                            "examples": v.get("examples", []),
                            "count": len(v.get("articles", [])),
                        }
                        for k, v in themes.items()
                    ],
                }
                try:
                    user_content = json.dumps(compact, indent=2)
                    summary = summarize_low_stakes(system_prompt, user_content, max_tokens=600)
                    st.markdown(summary)
                except Exception as e:
                    st.error(f"Claude (Haiku) intelligence summary failed: {e}. Check ANTHROPIC_API_KEY.")

    # Recent Substack posts and watchlist crossovers
    st.markdown("---")
    st.subheader("Substack Intelligence")
    st.caption("Latest posts from tracked investment authors, and crossovers with your watchlist.")

    session_sb = _session()
    try:
        now_utc = datetime.now(timezone.utc)
        cutoff_recent = now_utc - timedelta(days=30)
        posts = (
            session_sb.query(SubstackPost, SubstackFeed)
            .join(SubstackFeed, SubstackPost.feed_id == SubstackFeed.id)
            .order_by(SubstackPost.published_date.desc().nullslast())
            .limit(50)
            .all()
        )
        cross_posts = [
            (p, f)
            for (p, f) in posts
            if p.watchlist_crossref_flag
            and p.published_date is not None
            and p.published_date >= cutoff_recent
        ]
        if cross_posts:
            st.markdown("**Watchlist crossovers (last 30 days)**")
            watchlist_set = {
                c.ticker
                for c in session_sb.query(Company).filter(Company.active == True).all()
            }
            for post, feed in cross_posts:
                extracted = post.extracted_tickers or []
                matched = [t for t in extracted if t in watchlist_set] or extracted
                if matched:
                    what = f"mentioned **{', '.join(matched)}**"
                else:
                    # Sector-based crossover: flag set by watchlist-relevant sectors, no tickers extracted
                    sectors = ", ".join((post.extracted_sectors or [])[:3])
                    what = f"covered **{sectors or 'watchlist-relevant themes'}**"
                st.markdown(
                    f"- {feed.author_name} {what} — {post.claude_one_sentence_thesis or post.title}"
                )
        else:
            st.caption("No Substack posts mentioning your watchlist in the last 30 days.")

        st.markdown("**Recent Substack posts**")
        if posts:
            for post, feed in posts:
                label = f"{feed.author_name}: {post.title}"
                with st.expander(label):
                    if post.published_date:
                        st.caption(f"Published: {post.published_date.isoformat()}")
                    if post.extracted_tickers:
                        st.write(
                            "Tickers: "
                            + ", ".join(
                                f"`{t}`" for t in (post.extracted_tickers or [])[:10]
                            )
                        )
                    if post.extracted_sectors:
                        st.write(
                            "Sectors: "
                            + ", ".join(
                                f"`{s}`" for s in (post.extracted_sectors or [])[:10]
                            )
                        )
                    if post.claude_one_sentence_thesis:
                        st.write(post.claude_one_sentence_thesis)
                    if post.summary:
                        st.caption((post.summary or "")[:400])
                    if post.post_url:
                        st.markdown(f"[Open post]({post.post_url})")
        else:
            st.caption("No Substack posts ingested yet. Scheduler will populate this view.")
    finally:
        session_sb.close()

    # Research Radar - external research mentions not yet on the watchlist
    st.markdown("---")
    st.subheader("Research Radar (last 60 days)")
    st.caption("Tickers mentioned by tracked Substack authors that aren't on your watchlist yet — a discovery feed, not a watchlist filter.")
    from datetime import date as _date

    session = _session()
    try:
        radar_cutoff = _date.today() - timedelta(days=60)
        radar_rows = (
            session.query(ResearchRadar)
            .filter(ResearchRadar.mention_date >= radar_cutoff)
            .all()
        )
        if radar_rows:
            # Group by ticker
            by_ticker: Dict[str, Dict[str, Any]] = {}
            for r in radar_rows:
                info = by_ticker.setdefault(
                    r.ticker,
                    {"ticker": r.ticker, "authors": set(), "entries": [], "added": r.added_to_watchlist},
                )
                info["authors"].add(r.mentioned_by)
                info["entries"].append(r)
                info["added"] = info["added"] or r.added_to_watchlist

            for ticker, info in sorted(by_ticker.items(), key=lambda kv: kv[0]):
                authors = sorted(info["authors"])
                consensus = len(authors) >= 3
                cols = st.columns([2, 4, 2])
                with cols[0]:
                    badge = " (Consensus signal)" if consensus else ""
                    st.markdown(f"**{ticker}**{badge}")
                    st.caption(f"Authors: {', '.join(authors)}")
                with cols[1]:
                    # Show the most recent thesis snippet
                    latest = sorted(info["entries"], key=lambda e: e.mention_date, reverse=True)[0]
                    st.write(latest.thesis_snippet or "")
                    st.caption(f"Last mentioned: {latest.mention_date.isoformat()}")
                with cols[2]:
                    label = "Added" if info["added"] else "Add to Watchlist"
                    disabled = info["added"]
                    if st.button(label, key=f"rr_add_{ticker}", disabled=disabled):
                        # Add ticker to watchlist with the research thesis
                        wl = WatchlistManager()
                        thesis = latest.thesis_snippet or "Added from Substack research radar."
                        try:
                            res = wl.add_ticker(ticker, thesis_notes=thesis, force=True)
                            if res.get("status") == "error":
                                st.error(res.get("error", "Add to watchlist failed."))
                            else:
                                # Mark all radar entries for this ticker as added
                                for r in radar_rows:
                                    if r.ticker == ticker:
                                        r.added_to_watchlist = True
                                session.commit()
                                st.success(res.get("message", f"{ticker} added to watchlist."))
                        except Exception as e:
                            st.error(f"Add to watchlist failed: {e}")
        else:
            if session.query(SubstackFeed).count() == 0:
                st.info(
                    "No Substack authors are being tracked yet — add one in the "
                    "System tab to start populating this feed."
                )
            else:
                st.info("No non-watchlist ticker mentions from tracked authors in the last 60 days.")
    finally:
        session.close()

# ----- Tab 5: Congress & Funds -----
with tab6:
    st.subheader("Weekly Sector Digest")
    col_daily, col_weekly = st.columns(2)
    with col_daily:
        if st.button("Run Briefing Now", key="tab5_run_briefing", type="primary"):
            with st.spinner("Running daily briefing..."):
                try:
                    from market_lens.ingestion.sector_scanner import run_daily_digest
                    run_daily_digest(slot="evening")
                    st.success("Briefing generated.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Briefing error: {e}")
    with col_weekly:
        if st.button("Generate Weekly Digest Now", key="tab5_run_weekly"):
            with st.spinner("Generating weekly digest (normally runs Saturday 8 PM)..."):
                try:
                    from market_lens.ingestion.sector_scanner import run_weekly_digest
                    run_weekly_digest()
                    st.success("Weekly digest generated.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Weekly digest error: {e}")

    session = _session()
    try:
        # Most recent daily briefing (morning or evening, whichever is newer)
        latest_daily = (
            session.query(WeeklyDigest)
            .filter(WeeklyDigest.digest_type == "daily")
            .order_by(WeeklyDigest.digest_date.desc(), WeeklyDigest.created_at.desc())
            .limit(1)
            .first()
        )
        if latest_daily and latest_daily.full_digest_text:
            st.markdown("#### Latest daily briefing")
            st.caption(f"{latest_daily.digest_date} ({latest_daily.digest_time or ''})")
            st.write(latest_daily.full_digest_text)

        # Most recent weekly digest. Every app startup's sector scan silently
        # inserts a placeholder row for today (see _create_weekly_digest_stub
        # in sector_scanner.py) — exclude it so a real digest from last
        # Saturday doesn't get buried under today's unclicked placeholder.
        WEEKLY_DIGEST_PLACEHOLDER = "Weekly sector digest placeholder. To be generated via Claude Haiku."
        latest_weekly = (
            session.query(WeeklyDigest)
            .filter(WeeklyDigest.digest_type == "weekly")
            .filter(WeeklyDigest.full_digest_text != WEEKLY_DIGEST_PLACEHOLDER)
            .order_by(WeeklyDigest.digest_date.desc())
            .limit(1)
            .first()
        )
        if latest_weekly and latest_weekly.full_digest_text:
            st.markdown("#### Latest weekly digest")
            st.caption(f"{latest_weekly.digest_date}")
            st.write(latest_weekly.full_digest_text)
        else:
            st.markdown("#### Latest weekly digest")
            st.caption("No real weekly digest generated yet.")
            st.write(
                "Real generation runs Saturday 8 PM via the scheduler, or click "
                "'Generate Weekly Digest Now' above to generate one on demand."
            )

        # Date picker for historical digests
        from datetime import date as _date
        hist_date = st.date_input("View historical digest", value=_date.today(), key="digest_date_picker")
        if hist_date:
            hist = (
                session.query(WeeklyDigest)
                .filter(WeeklyDigest.digest_date == hist_date)
                .order_by(WeeklyDigest.digest_type, WeeklyDigest.digest_time)
                .all()
            )
            if hist:
                for h in hist:
                    st.caption(f"{h.digest_type} "" {h.digest_time or '""'}")
                    st.write(h.full_digest_text or "(empty)")
            else:
                st.caption("No digest for this date.")

        st.markdown("---")
        st.subheader("Sector scan results")
        scans = (
            session.query(SectorScanResult)
            .order_by(SectorScanResult.scan_date.desc(), SectorScanResult.sector, SectorScanResult.rank_in_sector)
            .limit(200)
            .all()
        )
        if scans:
            df_sector = pd.DataFrame([
                {
                    "scan_date": s.scan_date.isoformat(),
                    "sector": s.sector,
                    "ticker": s.ticker,
                    "company_name": s.company_name,
                    "market_cap": s.market_cap,
                    "rank": s.rank_in_sector,
                    "week_return": s.week_return,
                    "hidden_giant": s.hidden_giant_flag,
                }
                for s in scans
            ])
            st.dataframe(df_sector, width="stretch")
        else:
            st.info("Sector scan runs every Saturday at 8pm ET. No results yet.")

        # (Research Radar moved to Market Signals tab)
    finally:
        session.close()

# ----- Tab 6: Macro & Sectors -----
with tab5:
    st.subheader("Congressional Trading Intelligence")
    st.caption("Disclosure data is for agent/Claude context: focus on sectors and convergence signals, not raw rows.")

    # Optional on-demand ingestion trigger
    session = _session()
    try:
        if st.button("Run House + Senate ingestion now"):
            with st.spinner("Running congressional disclosures ingestion..."):
                try:
                    ingest_house_disclosures()
                    ingest_senate_disclosures()
                    st.success("Congress ingestion complete. Reload this tab to see any new trades.")
                except Exception as e:
                    st.error(f"Congress ingestion failed: {e}")
    finally:
        session.close()

    # Compute aggregates for the intelligence layer
    try:
        activity = compute_recent_trading_activity(window_days=60)
        hearings_tl = get_congress_hearing_timeline(recent_days=30, upcoming_days=30)
        convergence = compute_convergence_signals(window_days=30)
    except Exception as e:
        st.error(f"Failed to compute congressional intelligence: {e}")
        activity = {"active_sectors": [], "cluster_trades": [], "total_trades": 0}
        hearings_tl = {
            "upcoming_hearings": [],
            "recent_hearings": [],
            "has_lobbying_data": False,
        }
        convergence = {"convergences": [], "has_lobbying_data": False}

    # Claude Haiku synthesis
    summarize = st.button("Refresh analysis")
    summary_text = None
    if summarize:
        try:
            snapshot = {
                "trades_window": {
                    "start": str(activity.get("window_start")),
                    "end": str(activity.get("window_end")),
                    "total_trades": activity.get("total_trades"),
                },
                "active_sectors": activity.get("active_sectors", []),
                "cluster_trades": activity.get("cluster_trades", []),
                "hearings": {
                    "upcoming": hearings_tl.get("upcoming_hearings", []),
                    "recent": hearings_tl.get("recent_hearings", []),
                },
                "convergences": convergence.get("convergences", []),
            }
            system_prompt = (
                "You are a macro/policy analyst. Given congressional trading, "
                "hearing, and lobbying activity, identify which sectors or companies "
                "are most likely to be affected by upcoming legislation or regulatory action. "
                "Return exactly 3 specific observations, each with 2""3 sentences of reasoning. "
                "Avoid generic caveats and refer to trades/hearings/lobbying patterns explicitly."
            )
            import json

            user_content = json.dumps(snapshot, default=str, indent=2)
            summary_text = summarize_low_stakes(system_prompt, user_content, max_tokens=500)
        except Exception as e:
            st.error(f"Claude (Haiku) summary failed: {e}. Check ANTHROPIC_API_KEY.")

    if summary_text:
        st.subheader("Claude summary (last 60 days)")
        st.write(summary_text)

    # Convergence signals (trades + lobbying + hearings)
    st.subheader("Convergence signals (trades + lobbying + hearings)")
    convergences = convergence.get("convergences") or []
    if convergences:
        for c in convergences:
            st.markdown(
                f"- **{c['sector']}** "" trades: {c['trade_count']}, "
                f"lobbying filings: {c['filings_count']}, hearings: {c['hearings_count']} "
                f"(window: last 30 days)"
            )
    else:
        if not convergence.get("has_lobbying_data"):
            st.warning(
                "No convergence signals detected in the last 30 days. "
                "Lobbying data may not be ingested yet; convergence signals are sector-level only for now."
            )
        else:
            st.info("No convergence signals detected in the last 30 days.")

    # Active sectors and cluster trades
    st.subheader("Active sectors (last 60 days)")
    active_sectors = activity.get("active_sectors") or []
    if active_sectors:
        sector_str = ", ".join(
            f"{s['sector']} ({s['trade_count']} trades)" for s in active_sectors
        )
        st.write(sector_str)
    else:
        if activity.get("total_trades", 0) == 0:
            st.warning(
                "No congressional trades in the database over the last 60 days. "
                "Use Force Refresh to pull disclosures from the House Clerk and Senate EFTS sources."
            )
        else:
            st.info("No sectors reached the 3-trade threshold in the last 60 days.")

    st.subheader("Cluster trades (same ticker, different members)")
    cluster_trades = activity.get("cluster_trades") or []
    if cluster_trades:
        df_clusters = pd.DataFrame(cluster_trades)
        st.dataframe(df_clusters, width="stretch")
    else:
        st.info("No cluster trades (2+ trades from different members in 60 days).")

    # Hearings timeline
    st.subheader("Upcoming committee hearings (next 30 days)")
    upcoming = hearings_tl.get("upcoming_hearings") or []
    if upcoming:
        df_upcoming = pd.DataFrame(upcoming)
        st.dataframe(df_upcoming, width="stretch")
    else:
        if not config.CONGRESS_API_KEY:
            st.error(
                "Hearings timeline unavailable: CONGRESS_API_KEY is not set. "
                "Set it in .env and run update_hearing_schedule to populate."
            )
        else:
            st.info("No upcoming hearings in the next 30 days.")

    st.subheader("Recent committee hearings (last 30 days)")
    recent = hearings_tl.get("recent_hearings") or []
    if recent:
        df_recent = pd.DataFrame(recent)
        st.dataframe(df_recent, width="stretch")
    else:
        st.info("No recorded hearings in the last 30 days.")

    # Raw tables for transparency
    session = _session()
    try:
        with st.expander("Raw congressional trades (last 60 days)"):
            cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).date()
            trades = (
                session.query(CongressTrade)
                .filter(CongressTrade.trade_date.isnot(None))
                .filter(CongressTrade.trade_date >= cutoff)
                .order_by(CongressTrade.disclosure_date.desc())
                .all()
            )
            if trades:
                df_congress = pd.DataFrame(
                    [
                        {
                            "trade_id": t.trade_id,
                            "member_id": t.member_id,
                            "ticker": t.ticker,
                            "company_name": t.company_name,
                            "type": t.transaction_type,
                            "trade_date": t.trade_date.isoformat() if t.trade_date else "",
                            "disclosure_date": t.disclosure_date.isoformat()
                            if t.disclosure_date
                            else "",
                            "days_to_disclose": t.days_to_disclose,
                            "source": t.source,
                        }
                        for t in trades
                    ]
                )
                st.dataframe(df_congress, width="stretch")
            else:
                st.caption("No trades in the last 60 days.")

        with st.expander("Senate PTR filings (last 90 days)"):
            cutoff_sen = (datetime.now(timezone.utc) - timedelta(days=90)).date()
            senate_rows = (
                session.query(CongressTrade)
                .filter(CongressTrade.source == "senate_efdsearch")
                .filter(CongressTrade.disclosure_date >= cutoff_sen)
                .order_by(CongressTrade.disclosure_date.desc())
                .all()
            )
            if senate_rows:
                df_senate = pd.DataFrame(
                    [
                        {
                            "member_id": t.member_id,
                            "disclosure_date": t.disclosure_date.isoformat()
                            if t.disclosure_date
                            else "",
                            "filing": t.company_name,
                        }
                        for t in senate_rows
                    ]
                )
                st.dataframe(df_senate, width="stretch")
            else:
                st.caption(
                    "No Senate PTR filings ingested in the last 90 days. "
                    "Run House + Senate ingestion above (Senate scraping requires Playwright). "
                    "If it stays empty after running, check the server console for a "
                    "'[Senate] Blocked...' or '[Senate] No consent...' line — senate.gov "
                    "sometimes blocks the request outright rather than returning no results."
                )

        with st.expander("Raw lobbying filings (last 60 days)"):
            from datetime import date as _date

            cutoff_ld = _date.today() - timedelta(days=60)
            lobby_rows = (
                session.query(LobbyingRegistration)
                .filter(LobbyingRegistration.filing_date >= cutoff_ld)
                .all()
            )
            if lobby_rows:
                df_lobby = pd.DataFrame(
                    [
                        {
                            "registration_id": r.registration_id,
                            "registrant_name": r.registrant_name,
                            "client_name": r.client_name,
                            "filing_date": r.filing_date.isoformat(),
                            "sector_keywords": r.sector_keywords,
                        }
                        for r in lobby_rows
                    ]
                )
                st.dataframe(df_lobby, width="stretch")
            else:
                st.caption(
                    "No lobbying registrations recorded in the last 60 days. "
                    "Lobbying data integration may not be configured yet."
                )

        committees = session.query(CommitteeSectorMap).all()
        with st.expander("Under the hood: committee""sector map (for agent context)"):
            if committees:
                df_com = pd.DataFrame(
                    [
                        {
                            "committee": c.committee_name,
                            "chamber": c.chamber,
                            "sectors": str(c.jurisdiction_sectors),
                        }
                        for c in committees
                    ]
                )
                st.dataframe(df_com, width="stretch")
            else:
                st.caption("No committee map. Run congress_tracker.seed_committee_sector_map() to populate.")
    finally:
        session.close()

# ----- Tab 7: System -----
with tab5:
    st.subheader("Tracked Funds")
    st.caption("Per-fund summaries and raw tables for sanity checks and agent/Claude context. Positions come from FMP 13F and ARK daily data when configured.")
    session = _session()
    try:
        if st.button("Run tracked funds ingestion now"):
            with st.spinner("Running tracked funds seeding + ingestion..."):
                try:
                    ensure_tracked_funds_seeded()
                    run_tracked_funds_ingestion()
                    st.success("Tracked funds ingestion complete. Reload this tab to see any new positions.")
                except Exception as e:
                    st.error(f"Tracked funds ingestion failed: {e}")
        funds = session.query(TrackedFund).filter_by(active=True).all()
        if not funds:
            st.warning("No active tracked funds. Run tracked_funds.ensure_tracked_funds_seeded() to add funds. FMP_API_KEY may be required for 13F data.")
        else:
            for f in funds:
                fund_positions = session.query(FundPosition).filter_by(fund_id=f.id).all()
                pos_count = len(fund_positions)
                top3 = sorted(fund_positions, key=lambda p: (p.market_value or 0), reverse=True)[:3]
                top3_str = ", ".join(
                    f"{p.ticker} ({p.market_value})" if p.market_value is not None else p.ticker
                    for p in top3
                ) or ""
                st.write(
                    f"**{f.name}** (CIK: {f.cik or ''})  -  {pos_count} positions. Top 3 by value: {top3_str}"
                )
            with st.expander("13F positions (full table)"):
                positions = (
                    session.query(FundPosition)
                    .join(TrackedFund, FundPosition.fund_id == TrackedFund.id)
                    .order_by(FundPosition.quarter.desc(), TrackedFund.name)
                    .limit(500)
                    .all()
                )
                if positions:
                    df_fp = pd.DataFrame([
                        {
                            "fund": next((x.name for x in funds if x.id == p.fund_id), ""),
                            "ticker": p.ticker,
                            "company": p.company_name,
                            "quarter": p.quarter,
                            "shares": p.shares,
                            "market_value": p.market_value,
                        }
                        for p in positions
                    ])
                    st.dataframe(df_fp, width="stretch")
                else:
                    st.caption("No 13F positions. FMP 13F ingestion may not be configured or returned no data for these funds.")
            with st.expander("Position deltas (quarter-over-quarter)"):
                deltas = session.query(FundPositionDelta).order_by(FundPositionDelta.quarter.desc()).limit(200).all()
                if deltas:
                    df_d = pd.DataFrame([
                        {"fund_id": d.fund_id, "ticker": d.ticker, "quarter": d.quarter, "change_type": d.change_type}
                        for d in deltas
                    ])
                    st.dataframe(df_d, width="stretch")
                else:
                    st.caption("No position deltas. Run tracked funds ingestion to populate.")
            with st.expander("ARK Invest "" Current 13F Holdings"):
                ark_fund = session.query(TrackedFund).filter(
                    TrackedFund.name.ilike("%ARK%")
                ).first()
                if ark_fund:
                    ark_positions = (
                        session.query(FundPosition)
                        .filter_by(fund_id=ark_fund.id)
                        .order_by(FundPosition.market_value.desc())
                        .limit(50)
                        .all()
                    )
                    if ark_positions:
                        df_ark = pd.DataFrame(
                            [
                                {
                                    "ticker": p.ticker,
                                    "company": p.company_name,
                                    "shares": f"{int(p.shares):,}" if p.shares else "",
                                    "market_value": f"${int(p.market_value):,}" if p.market_value else "",
                                    "weight_%": f"{p.weight_pct:.1f}%" if getattr(p, "weight_pct", None) else "",
                                    "quarter": p.quarter,
                                }
                                for p in ark_positions
                            ]
                        )
                        st.dataframe(df_ark, width="stretch")
                    else:
                        st.info("ARK 13F positions not yet loaded. Run tracked funds ingestion.")
                else:
                    st.info("ARK fund not found in tracked funds.")
    finally:
        session.close()

# ----- Tab 8: Agent Activity Feed, Supplier Registry, Leadership Events, Diagnostics -----
with tab7:
    st.subheader("Alert diagnostics")
    st.caption("Send a test Telegram and test email to verify delivery. Either live data (success) or a clear error is shown.")
    if st.button("Send test alert (Telegram + Email)"):
        tg_ok, tg_err = send_telegram("Market Lens test  -  Telegram OK")
        em_ok, em_err = send_email("Market Lens test", "Dashboard test email. If you see this, email alerts work.")
        if tg_ok:
            st.success("Telegram: sent.")
        else:
            st.error(f"Telegram: failed  -  {tg_err or 'unknown'}")
        if em_ok:
            st.success("Email: sent.")
        else:
            st.error(f"Email: failed  -  {em_err or 'unknown'}")
    st.divider()

    st.subheader("Agent Activity Feed")
    session = _session()
    try:
        cycles = (
            session.query(AgentCycleLog)
            .order_by(AgentCycleLog.cycle_at.desc())
            .limit(50)
            .all()
        )
        if not cycles:
            st.info("No agent cycles yet. Run the scheduler (agent.py) to populate.")
        else:
            for c in cycles:
                with st.expander(f"{c.ticker} @ {c.cycle_at.strftime('%Y-%m-%d %H:%M')} UTC | Material: {c.material_flag}"):
                    if c.synthesis_text:
                        st.write(c.synthesis_text)
                    if c.delta_trigger:
                        st.json(c.delta_trigger)
    finally:
        session.close()

    st.subheader("Add Substack Feed")
    new_feed_url = st.text_input(
        "Substack publication URL", placeholder="https://example.substack.com", key="substack_feed_url"
    )
    new_author = st.text_input(
        "Author name", placeholder="Author or publication name", key="substack_feed_author"
    )
    new_focus = st.text_input(
        "Thesis focus", placeholder="What this feed tends to cover", key="substack_feed_focus"
    )
    if st.button("Add feed and ingest now"):
        if not new_feed_url or not new_feed_url.strip():
            st.error("Please enter a Substack URL.")
        elif not new_author or not new_author.strip():
            st.error("Please enter an author name.")
        else:
            url = new_feed_url.strip().rstrip("/")
            rss_url = url + "/feed"
            session = _session()
            try:
                existing = (
                    session.query(SubstackFeed)
                    .filter(SubstackFeed.feed_url == url)
                    .first()
                )
                if existing:
                    st.info("Feed is already configured; running ingestion now.")
                    feed = existing
                else:
                    feed = SubstackFeed(
                        feed_url=url,
                        rss_url=rss_url,
                        author_name=new_author.strip(),
                        thesis_focus=new_focus.strip() or None,
                        active=True,
                    )
                    session.add(feed)
                    session.flush()
                with st.spinner("Ingesting Substack feed..."):
                    try:
                        run_substack_ingestion_for_single_feed(feed.id)
                        session.commit()
                        st.success("Feed ingested. New posts will appear in Substack Intelligence.")
                    except Exception as e:
                        session.rollback()
                        st.error(f"Substack ingestion failed: {e}")
            finally:
                session.close()
    st.subheader("Supplier Registry (reliability scores)")
    session = _session()
    try:
        suppliers = session.query(SupplierRegistry).order_by(SupplierRegistry.supplier_name).all()
        if not suppliers:
            st.info("No suppliers in registry. Supplier signals from 8-K/10-K will add entries.")
        else:
            for s in suppliers:
                default = int(s.reliability_score) if s.reliability_score is not None else 50
                col1, col2, col3 = st.columns([2, 1, 2])
                with col1:
                    st.text(s.supplier_name)
                with col2:
                    st.number_input(
                        "Score 0-100",
                        min_value=0,
                        max_value=100,
                        value=default,
                        key=f"supp_score_{s.id}",
                    )
                with col3:
                    if s.reliability_notes:
                        st.caption(s.reliability_notes[:100])
            if st.button("Save reliability scores"):
                for s in suppliers:
                    new_val = st.session_state.get(f"supp_score_{s.id}")
                    if new_val is not None and (s.reliability_score or 0) != new_val:
                        s.reliability_score = new_val
                session.commit()
                st.success("Saved.")
    finally:
        session.close()

    st.subheader("Leadership Events (departure badges)")
    session = _session()
    try:
        events = (
            session.query(LeadershipEvent)
            .order_by(LeadershipEvent.event_date.desc())
            .limit(100)
            .all()
        )
        if not events:
            st.info("No leadership events. Backfill 8-K Item 5.02 via leadership.run_leadership_backfill().")
        else:
            df_le = pd.DataFrame([
                {
                    "ticker": e.ticker,
                    "date": e.event_date.isoformat(),
                    "person": e.person_name,
                    "role": e.role,
                    "type": e.event_type.value if e.event_type else "",
                    "departure": e.departure_language_classified.value if e.departure_language_classified else "",
                }
                for e in events
            ])
            st.dataframe(df_le, width="stretch")
            st.caption("Departure badges: planned / abrupt / forced from 8-K Item 5.02 language.")
    finally:
        session.close()











