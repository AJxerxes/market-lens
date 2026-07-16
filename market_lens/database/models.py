"""
Market Lens Database Models
All DateTime columns use timezone-aware UTC timestamps.
All paths stored as strings (resolved from config at runtime).
Cross-platform compatible - no Windows-only types.
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Date, Text, JSON,
    Enum as SQLEnum, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy import func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()

# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------

class InstrumentType(enum.Enum):
    """Security instrument classification."""
    equity = "equity"
    otc_adr = "otc_adr"
    etf = "etf"
    inverse_etf = "inverse_etf"
    mutual_fund = "mutual_fund"


class DepartureClassification(enum.Enum):
    """Leadership departure language classification."""
    planned = "planned"
    abrupt = "abrupt"
    forced = "forced"


class EventType(enum.Enum):
    """Leadership event types."""
    appointed = "appointed"
    departed = "departed"
    interim = "interim"


class SignalType(enum.Enum):
    """Supplier signal types."""
    new_supplier_named = "new_supplier_named"
    supplier_removed = "supplier_removed"
    supplier_risk_language = "supplier_risk_language"
    customs_import_change = "customs_import_change"


class SignalSeverity(enum.Enum):
    """Supplier signal severity levels."""
    informational = "informational"
    watch = "watch"
    flag = "flag"


class RecommendationLabel(enum.Enum):
    """Investment recommendation labels."""
    strong_buy = "STRONG BUY"
    buy = "BUY"
    watch = "WATCH"
    avoid = "AVOID"


class SwingLabel(enum.Enum):
    """Swing timing labels."""
    setup_present = "SETUP PRESENT"
    monitor = "MONITOR"
    no_signal = "NO SIGNAL"


# -----------------------------------------------------------------------------
# Core Tables
# -----------------------------------------------------------------------------

class Company(Base):
    """Watchlist companies with dynamic instrument classification."""
    __tablename__ = "companies"
    
    ticker = Column(String(20), primary_key=True)
    name = Column(String(255), nullable=False)
    # Legal entity name used for customs, lobbying, and fund lookups
    legal_name = Column(String(255))
    sector = Column(String(100))
    exchange = Column(String(50))
    # Primary investor relations / earnings transcript page
    ir_transcript_url = Column(Text)
    instrument_type = Column(SQLEnum(InstrumentType), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    paused = Column(Boolean, default=False, nullable=False)
    watchlist_added_date = Column(DateTime(timezone=True), nullable=False)
    thesis_notes = Column(Text)
    local_currency = Column(String(10))  # For ADRs
    fx_series_id = Column(String(50))  # FRED series for FX rate
    # Current snapshot from yfinance (Phase 2)
    data_quality_flag = Column(String(20))  # 'complete' or 'incomplete'
    market_cap = Column(Float)
    trailing_pe = Column(Float)
    forward_pe = Column(Float)
    dividend_yield = Column(Float)
    revenue_growth = Column(Float)
    gross_margins = Column(Float)
    operating_margins = Column(Float)
    free_cash_flow = Column(Float)
    debt_to_equity = Column(Float)
    beta = Column(Float)
    short_ratio = Column(Float)           # days to cover (short interest / avg daily volume)
    short_percent_float = Column(Float)   # short interest as % of float
    industry = Column(String(255))
    long_name = Column(String(500))
    current_price = Column(Float)
    # Phase 4 computed metrics (from fundamentals.py)
    revenue_cagr_3y = Column(Float)
    gross_margin_trend = Column(String(20))  # improving, flat, deteriorating
    fcf_yield = Column(Float)
    debt_ebitda_ratio = Column(Float)
    dividend_streak_years = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), 
                       onupdate=lambda: datetime.now(timezone.utc))


class PriceHistory(Base):
    """Historical price data."""
    __tablename__ = "price_history"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float, nullable=False)
    volume = Column(Integer)
    adj_close = Column(Float)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        UniqueConstraint('ticker', 'date', name='uix_ticker_date'),
        Index('idx_price_ticker_date', 'ticker', 'date'),
    )


class Fundamentals(Base):
    """Quarterly fundamental data."""
    __tablename__ = "fundamentals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    period_end = Column(Date, nullable=False)
    revenue = Column(Float)
    gross_profit = Column(Float)
    operating_income = Column(Float)
    net_income = Column(Float)
    free_cash_flow = Column(Float)
    total_debt = Column(Float)
    ebitda = Column(Float)
    eps = Column(Float)
    pe_ratio = Column(Float)
    dividend_per_share = Column(Float)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        UniqueConstraint('ticker', 'period_end', name='uix_ticker_period'),
        Index('idx_fundamentals_ticker_period', 'ticker', 'period_end'),
    )


class Score(Base):
    """Computed Lynch and swing scores."""
    __tablename__ = "scores"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    score_date = Column(Date, nullable=False)
    lynch_score = Column(Float)
    swing_score = Column(Float)
    dcf_fair_value_low = Column(Float)
    dcf_fair_value_mid = Column(Float)
    dcf_fair_value_high = Column(Float)
    comps_target = Column(Float)
    mean_reversion_target = Column(Float)
    recommendation_label = Column(SQLEnum(RecommendationLabel))
    swing_label = Column(SQLEnum(SwingLabel))
    rationale_text = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_scores_ticker_date', 'ticker', 'score_date'),
    )


class ScoreOverride(Base):
    """Manual overrides for scoring inputs. When locked=True, scoring uses override_value."""
    __tablename__ = "score_override"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    field_name = Column(String(80), nullable=False)
    override_value = Column(Float, nullable=False)
    locked = Column(Boolean, default=True, nullable=False)
    override_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("ticker", "field_name", name="uix_score_override_ticker_field"),
        Index("idx_score_override_ticker", "ticker"),
    )


# -----------------------------------------------------------------------------
# EDGAR / SEC
# -----------------------------------------------------------------------------

class TickerCikMap(Base):
    """Ticker to CIK mapping from SEC company_tickers.json."""
    __tablename__ = "ticker_cik_map"

    ticker = Column(String(20), primary_key=True)
    cik = Column(String(10), nullable=False)  # zero-padded 10-digit
    company_name = Column(String(255))
    last_updated = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (Index("idx_cik_map_cik", "cik"),)


class EdgarFact(Base):
    """XBRL company facts (Revenues, NetIncomeLoss, etc.)."""
    __tablename__ = "edgar_facts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    tag = Column(String(100), nullable=False)  # e.g. Revenues, NetIncomeLoss
    period_end = Column(Date, nullable=False)
    value = Column(Float, nullable=False)
    fy = Column(Integer)  # fiscal year
    fp = Column(String(10))  # Q1, Q2, Q3, FY
    form = Column(String(20))  # 10-K, 10-Q
    filed = Column(Date)
    accession_number = Column(String(40))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("ticker", "tag", "period_end", name="uix_edgar_fact_ticker_tag_period"),
        Index("idx_edgar_facts_ticker_tag", "ticker", "tag"),
    )


class EdgarRssLastChecked(Base):
    """Last RSS poll time per CIK for 8-K feed."""
    __tablename__ = "edgar_rss_last_checked"

    cik = Column(String(10), primary_key=True)
    last_checked = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# -----------------------------------------------------------------------------
# Insider & Institutional
# -----------------------------------------------------------------------------

class InsiderTransaction(Base):
    """Form 4 insider transactions."""
    __tablename__ = "insider_transactions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    filing_date = Column(Date, nullable=False)
    insider_name = Column(String(255), nullable=False)
    insider_title = Column(String(255))
    transaction_type = Column(String(50))  # buy, sell, option_exercise
    shares = Column(Integer)
    price_per_share = Column(Float)
    total_value = Column(Float)
    source_filing = Column(String(255))  # EDGAR accession number
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_insider_ticker_date', 'ticker', 'filing_date'),
    )


# -----------------------------------------------------------------------------
# News & Sentiment
# -----------------------------------------------------------------------------

class NewsSentiment(Base):
    """News articles with FinBERT sentiment scores."""
    __tablename__ = "news_sentiment"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    article_date = Column(DateTime(timezone=True), nullable=False)
    headline = Column(Text, nullable=False)
    source = Column(String(255))
    url = Column(Text)
    sentiment_score = Column(Float)  # -1 to +1
    sentiment_label = Column(String(20))  # positive, neutral, negative
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_news_ticker_date', 'ticker', 'article_date'),
    )


# -----------------------------------------------------------------------------
# Options Flow
# -----------------------------------------------------------------------------

class OptionsSignal(Base):
    """Unusual options activity from three-source cross-validation."""
    __tablename__ = "options_signals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    signal_date = Column(Date, nullable=False)
    contract = Column(String(100))  # Option contract identifier
    source = Column(String(50), nullable=False)  # tradier, barchart, marketchameleon
    volume = Column(Integer)
    open_interest = Column(Integer)
    volume_oi_ratio = Column(Float)
    vs_20day_avg = Column(Float)  # Volume vs 20-day average
    flagged_unusual = Column(Boolean, default=False)
    cross_validated = Column(Boolean, default=False)  # True when 2+ sources agree
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_options_ticker_date', 'ticker', 'signal_date'),
        Index('idx_options_cross_validated', 'ticker', 'cross_validated', 'signal_date'),
    )


# -----------------------------------------------------------------------------
# Macro Data
# -----------------------------------------------------------------------------

class MacroData(Base):
    """FRED economic indicators."""
    __tablename__ = "macro_data"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    series_id = Column(String(50), nullable=False)  # FRED series ID
    date = Column(Date, nullable=False)
    value = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        UniqueConstraint('series_id', 'date', name='uix_series_date'),
        Index('idx_macro_series_date', 'series_id', 'date'),
    )


# -----------------------------------------------------------------------------
# Agent Brain
# -----------------------------------------------------------------------------

class AgentMemory(Base):
    """Prior state snapshots for delta detection."""
    __tablename__ = "agent_memory"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    snapshot_date = Column(DateTime(timezone=True), nullable=False)
    lynch_score = Column(Float)
    swing_score = Column(Float)
    sentiment_score = Column(Float)
    insider_net = Column(Float)
    recommendation_label = Column(String(50))
    thesis_summary = Column(Text)
    signal_history_90d = Column(JSON)  # Compressed 90-day event log
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_memory_ticker_date', 'ticker', 'snapshot_date'),
    )


class AgentCycleLog(Base):
    """Every agent brain reasoning cycle."""
    __tablename__ = "agent_cycle_log"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    cycle_at = Column(DateTime(timezone=True), nullable=False)
    delta_trigger = Column(JSON)  # What changed
    synthesis_text = Column(Text)  # Claude API output
    material_flag = Column(Boolean, default=False)
    alert_sent = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_cycle_ticker_time', 'ticker', 'cycle_at'),
    )


# -----------------------------------------------------------------------------
# Court Cases
# -----------------------------------------------------------------------------

class CourtCase(Base):
    """Federal court docket monitoring."""
    __tablename__ = "court_cases"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    case_number = Column(String(100), unique=True, nullable=False)
    court = Column(String(255))
    filed_date = Column(Date)
    plaintiff = Column(String(500))
    defendant = Column(String(500))
    case_type = Column(String(100))
    summary = Column(Text)
    source = Column(String(50))  # pacer or courtlistener
    pacer_needed = Column(Boolean, default=False)  # Manual flag only
    first_detected_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_court_ticker', 'ticker'),
    )


# -----------------------------------------------------------------------------
# Leadership Tracking
# -----------------------------------------------------------------------------

class LeadershipEvent(Base):
    """C-suite and board changes from 8-K Item 5.02."""
    __tablename__ = "leadership_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    person_name = Column(String(255), nullable=False)
    role = Column(String(100), nullable=False)
    event_type = Column(SQLEnum(EventType), nullable=False)
    event_date = Column(Date, nullable=False)
    tenure_days = Column(Integer)
    departure_language = Column(Text)
    departure_language_classified = Column(SQLEnum(DepartureClassification))
    equity_accelerated = Column(Boolean, default=False)
    source_filing = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_leadership_ticker_date', 'ticker', 'event_date'),
    )


class LeadershipVelocity(Base):
    """Rolling velocity tracker per role per company."""
    __tablename__ = "leadership_velocity"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    role = Column(String(100), nullable=False)
    change_count_12mo = Column(Integer, default=0)
    change_count_24mo = Column(Integer, default=0)
    avg_tenure_days = Column(Integer)
    instability_flag = Column(Boolean, default=False)
    last_updated = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        UniqueConstraint('ticker', 'role', name='uix_ticker_role'),
    )


# -----------------------------------------------------------------------------
# Supplier Intelligence
# -----------------------------------------------------------------------------

class RiskFactorDelta(Base):
    """10-K Risk Factors section year-over-year comparison (cosine similarity)."""
    __tablename__ = "risk_factor_delta"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    current_filing_date = Column(Date, nullable=False)
    prior_filing_date = Column(Date, nullable=False)
    current_risk_text = Column(Text)
    prior_risk_text = Column(Text)
    cosine_similarity = Column(Float)
    meaningful_change_flag = Column(Boolean, default=False)  # True when similarity < 0.85
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (Index("idx_risk_factor_ticker", "ticker"),)


class SupplierSignal(Base):
    """Detected supplier switches and risk signals."""
    __tablename__ = "supplier_signals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    detected_date = Column(Date, nullable=False)
    signal_type = Column(SQLEnum(SignalType), nullable=False)
    supplier_name = Column(String(255))
    source = Column(String(100))  # 10k_risk_factors, earnings_call, 8k_material_contract, importyeti
    prior_supplier_name = Column(String(255))
    context_text = Column(Text)
    severity = Column(SQLEnum(SignalSeverity), default=SignalSeverity.informational)
    agent_reviewed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_supplier_ticker_date', 'ticker', 'detected_date'),
    )


class SupplierRegistry(Base):
    """User-maintained supplier reliability assessments."""
    __tablename__ = "supplier_registry"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_name = Column(String(255), unique=True, nullable=False)
    reliability_score = Column(Integer)  # 0-100, NULL if not yet researched
    reliability_notes = Column(Text)
    financial_health_flag = Column(Boolean, default=False)
    concentration_risk_flag = Column(Boolean, default=False)
    last_researched_date = Column(Date)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                       onupdate=lambda: datetime.now(timezone.utc))


# -----------------------------------------------------------------------------
# Weekly Sector Scanner
# -----------------------------------------------------------------------------

class SectorScanResult(Base):
    """Saturday sector scan results."""
    __tablename__ = "sector_scan_results"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_date = Column(Date, nullable=False)
    sector = Column(String(100), nullable=False)
    ticker = Column(String(20), nullable=False)
    company_name = Column(String(255))
    market_cap = Column(Float)
    rank_in_sector = Column(Integer)
    price = Column(Float)
    week_return = Column(Float)
    month_return = Column(Float)
    ytd_return = Column(Float)
    pe_ratio = Column(Float)
    revenue_growth_yoy = Column(Float)
    analyst_consensus = Column(String(50))
    one_sentence_state = Column(Text)
    hidden_giant_flag = Column(Boolean, default=False)
    brand_awareness_ratio = Column(Float)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_sector_scan_date', 'scan_date', 'sector'),
    )


class WeeklyDigest(Base):
    """Daily (morning/evening) and weekly digest summaries."""
    __tablename__ = "weekly_digest"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    digest_date = Column(Date, nullable=False)
    digest_type = Column(String(20), default="weekly", nullable=False)  # 'daily' | 'weekly'
    digest_time = Column(String(20), nullable=True)  # 'morning' | 'evening' for daily
    full_digest_text = Column(Text)
    sector_summaries_json = Column(JSON)
    hidden_giants_json = Column(JSON)
    watchlist_suggestions_json = Column(JSON)
    delivered_telegram = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint("digest_date", "digest_type", "digest_time", name="uq_weekly_digest_date_type_time"),)


# -----------------------------------------------------------------------------
# Congressional Trading
# -----------------------------------------------------------------------------

class CongressMember(Base):
    """Congressional members tracking."""
    __tablename__ = "congress_members"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    member_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    chamber = Column(String(20))  # house, senate
    party = Column(String(50))
    state = Column(String(2))
    committees = Column(JSON)  # Array of committee names
    tracked = Column(Boolean, default=False)
    manually_tracked = Column(Boolean, default=False)
    trade_count_12mo = Column(Integer, default=0)
    trade_volume_12mo = Column(Float, default=0.0)
    top_sector = Column(String(100))
    last_updated = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CongressTrade(Base):
    """STOCK Act disclosures."""
    __tablename__ = "congress_trades"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(String(100), unique=True, nullable=False)
    member_id = Column(String(50), ForeignKey("congress_members.member_id"), nullable=False)
    ticker = Column(String(20))
    company_name = Column(String(255))
    sector = Column(String(100))
    transaction_type = Column(String(20))  # buy, sell
    amount_range_low = Column(Float)
    amount_range_high = Column(Float)
    trade_date = Column(Date, nullable=False)
    disclosure_date = Column(Date, nullable=False)
    days_to_disclose = Column(Integer)
    committee_correlated = Column(Boolean, default=False)
    matching_committees = Column(JSON)
    cluster_flag = Column(Boolean, default=False)
    source = Column(String(50))  # fmp, house_clerk, senate_efts
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        Index('idx_congress_trade_date', 'trade_date'),
        Index('idx_congress_member_ticker', 'member_id', 'ticker'),
    )


class CommitteeSectorMap(Base):
    """Committee jurisdiction mapping."""
    __tablename__ = "committee_sector_map"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    committee_name = Column(String(255), unique=True, nullable=False)
    chamber = Column(String(20))
    jurisdiction_sectors = Column(JSON)  # Array of GICS sectors


class DisclosureTimingProfile(Base):
    """Per-member disclosure timing patterns."""
    __tablename__ = "disclosure_timing_profile"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    member_id = Column(String(50), ForeignKey("congress_members.member_id"), unique=True, nullable=False)
    avg_days_to_disclose = Column(Float)
    stddev_days = Column(Float)
    min_days = Column(Integer)
    max_days = Column(Integer)
    last_30day_silence_flag = Column(Boolean, default=False)
    last_updated = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class LobbyingRegistration(Base):
    """Lobbying activity from LDA (Lobbying Disclosure Act) API."""
    __tablename__ = "lobbying_registrations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    registration_id = Column(String(100), unique=True, nullable=False)
    registrant_name = Column(String(255))
    client_name = Column(String(255))
    filing_date = Column(Date, nullable=False)
    covered_officials = Column(JSON)
    sector_keywords = Column(JSON)
    # Raw lobbying_activities array from LDA API
    lobbying_activities = Column(JSON)
    committee_match = Column(Boolean, default=False)
    flagged = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CommitteeHearing(Base):
    """Congressional hearing calendar."""
    __tablename__ = "committee_hearings"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    hearing_id = Column(String(100), unique=True, nullable=False)
    committee_name = Column(String(255), nullable=False)
    chamber = Column(String(20))
    hearing_date = Column(DateTime(timezone=True), nullable=False)
    # Optional subject/summary field from Congress.gov
    subject = Column(Text)
    hearing_title = Column(Text)
    topic_keywords = Column(JSON)
    # Sector relevance mapping (structured)
    sector_relevance = Column(JSON)
    relevant_sectors = Column(JSON)
    relevant_watchlist_tickers = Column(JSON)
    member_watch_window_triggered = Column(Boolean, default=False)
    alerted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CongressBill(Base):
    """Bill tracking for sector impact."""
    __tablename__ = "congress_bills"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bill_id = Column(String(100), unique=True, nullable=False)
    bill_number = Column(String(50), nullable=False)
    title = Column(Text)
    introduced_date = Column(Date)
    last_action_date = Column(Date)
    last_action_type = Column(String(255))
    relevant_committees = Column(JSON)
    relevant_sectors = Column(JSON)
    relevant_watchlist_tickers = Column(JSON)
    status = Column(String(100))
    alerted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# -----------------------------------------------------------------------------
# Tracked Funds & 13F Positions
# -----------------------------------------------------------------------------


class TrackedFund(Base):
    """High-conviction thematic or hedge funds tracked by Market Lens."""
    __tablename__ = "tracked_funds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False)
    cik = Column(String(20), unique=True, nullable=True)
    fund_type = Column(String(50))  # e.g. hedge_fund, thematic, etf_family
    thesis_notes = Column(Text)  # Plain-English description of the fund's thesis
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class FundPosition(Base):
    """Quarterly 13F positions for tracked funds."""
    __tablename__ = "fund_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fund_id = Column(Integer, ForeignKey("tracked_funds.id"), nullable=False)
    ticker = Column(String(20), nullable=False)
    company_name = Column(String(255))
    quarter = Column(String(10), nullable=False)  # e.g. '2025Q4'
    shares = Column(Float)
    market_value = Column(Float)  # dollar value reported in 13F
    weight_pct = Column(Float)  # position weight within fund, if computed
    form_type = Column(String(20), default="13F-HR")
    accession_number = Column(String(40))  # EDGAR accession
    as_of_date = Column(Date)  # period end date
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_fund_positions_fund_quarter", "fund_id", "quarter"),
    )


class FundPositionDelta(Base):
    """Quarter-over-quarter changes in fund positions."""
    __tablename__ = "fund_position_delta"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fund_id = Column(Integer, ForeignKey("tracked_funds.id"), nullable=False)
    ticker = Column(String(20), nullable=False)
    quarter = Column(String(10), nullable=False)  # current quarter
    previous_quarter = Column(String(10))
    change_type = Column(String(20))  # added, exited, increased, decreased
    size_change_pct = Column(Float)  # percent change vs prior quarter
    direction_changed = Column(Boolean, default=False)  # e.g. long to zero, or options direction flip
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_fund_delta_fund_quarter", "fund_id", "quarter"),
    )


class FundAnalysisLog(Base):
    """Claude synthesis logs for tracked funds and convergence analysis."""
    __tablename__ = "fund_analysis_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fund_id = Column(Integer, ForeignKey("tracked_funds.id"), nullable=True)
    ticker = Column(String(20), nullable=True)
    quarter = Column(String(10), nullable=True)
    analysis_type = Column(String(50))  # e.g. 'position_change', 'convergence'
    context_json = Column(JSON)  # structured input passed to Claude
    synthesis_text = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# -----------------------------------------------------------------------------
# Substack research feeds & radar
# -----------------------------------------------------------------------------


class SubstackFeed(Base):
    """Substack investment research feeds tracked by Market Lens."""
    __tablename__ = "substack_feeds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    feed_url = Column(String(500), unique=True, nullable=False)
    rss_url = Column(String(500), unique=True, nullable=False)
    author_name = Column(String(255), nullable=False)
    thesis_focus = Column(Text)
    active = Column(Boolean, default=True, nullable=False)
    last_fetched = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SubstackPost(Base):
    """Individual Substack posts with extracted tickers/sectors and thesis."""
    __tablename__ = "substack_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    feed_id = Column(Integer, ForeignKey("substack_feeds.id"), nullable=False)
    title = Column(Text, nullable=False)
    summary = Column(Text)
    published_date = Column(DateTime(timezone=True))
    post_url = Column(String(1000), unique=True, nullable=False)
    extracted_tickers = Column(JSON)
    extracted_sectors = Column(JSON)
    claude_one_sentence_thesis = Column(Text)
    watchlist_crossref_flag = Column(Boolean, default=False)
    processed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_substack_posts_feed_date", "feed_id", "published_date"),
    )


class ResearchRadar(Base):
    """Tickers mentioned by external research but not yet on the watchlist."""
    __tablename__ = "research_radar"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), nullable=False)
    mentioned_by = Column(String(255), nullable=False)
    mention_date = Column(Date, nullable=False)
    thesis_snippet = Column(Text)
    added_to_watchlist = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_research_radar_ticker_date", "ticker", "mention_date"),
    )


class AgentSynthesisLog(Base):
    """Lightweight log for external-signal-driven synthesis triggers (e.g. Substack mentions)."""
    __tablename__ = "agent_synthesis_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=True)
    trigger_type = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_agent_synth_ticker_time", "ticker", "created_at"),
    )


class ArkDailyTrade(Base):
    """Parsed daily ARK Invest trade history."""
    __tablename__ = "ark_daily_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False)
    fund_name = Column(String(100), nullable=False)
    ticker = Column(String(20), nullable=False)
    company_name = Column(String(255))
    direction = Column(String(10))  # buy, sell
    shares = Column(Float)
    notional_value = Column(Float)
    large_trade_flag = Column(Boolean, default=False)  # > $10M
    raw_source_url = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class EarningsEvent(Base):
    __tablename__ = "earnings_events"

    id = Column(Integer, primary_key=True)
    ticker = Column(String, nullable=False, index=True)
    company_name = Column(String)
    earnings_date = Column(Date, nullable=False)
    fiscal_quarter = Column(String)       # e.g. "Q1 2026"
    fiscal_year = Column(Integer)
    eps_estimate = Column(Float)          # analyst consensus estimate
    eps_actual = Column(Float)            # filled after earnings release
    revenue_estimate = Column(Float)
    revenue_actual = Column(Float)
    surprise_pct = Column(Float)          # (actual - estimate) / abs(estimate) * 100
    beat = Column(Boolean)                # True if beat, False if miss, None if pending
    confirmed = Column(Boolean, default=False)  # True if date is confirmed not estimated
    source = Column(String, default="yfinance")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("ticker", "earnings_date", "fiscal_quarter", name="uq_earnings_event"),
    )


class DebtMaturity(Base):
    __tablename__ = "debt_maturities"

    id = Column(Integer, primary_key=True)
    ticker = Column(String, nullable=False, index=True)
    maturity_year = Column(Integer, nullable=False)
    amount_millions = Column(Float)
    label = Column(String)
    source = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("ticker", "maturity_year", name="uq_debt_maturity"),
    )
