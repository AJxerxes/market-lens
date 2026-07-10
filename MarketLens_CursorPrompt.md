
MARKET LENS
Personal Investment Research & Pricing Platform
Cursor AI Master Build Prompt  |  Version 2.0  |  Active Agent Edition


1. What We Are Building
Market Lens is a personal investment research and pricing platform built for a single retail investor who thinks in the Peter Lynch framework: observe dominant, unglamorous businesses in everyday life, validate the observation with real financial data, price the opportunity, and hold with conviction. The platform is not a trading bot, a get-rich-quick tool, or a black box. It is a structured research assistant that mimics how a disciplined fundamental analyst would investigate a company — from first observation through to a buy, hold, or avoid recommendation — using only publicly available data sources and free or low-cost APIs.

The platform has two primary use modes:
•	Long-term equity research (Lynch-style): screen and research companies the user observes in daily life — the HID card readers on every university door, the Cintas trucks on every highway, the Sysco deliveries at every restaurant. The platform validates whether the moat the user observed is real and whether the current price makes it worth owning fractionally.
•	Swing and timing intelligence: for stocks already in the watchlist, surface early warning signals — unusual options flow, insider selling, technical breakdowns, sentiment shifts — so the user can make informed entry and exit decisions without needing real-time institutional data feeds.

Version 2.0 adds a third and critical capability:
•	Active Agent Brain: a persistent background process that runs continuously without user interaction. It reads news three times daily, monitors SEC EDGAR every 30 minutes, scans federal court dockets weekly, and synthesizes new information against prior conclusions to detect when a company's situation has materially changed. This is the difference between a passive dashboard and a system that thinks on your behalf while you are not looking at it.

Core design philosophy
The program should explain its reasoning in plain English at every step. Every score, every price target, every alert, every recommendation must come with a one-paragraph rationale the user can read and disagree with. The Agent Brain runs in the background and surfaces conclusions proactively — but the user makes every final decision. This is a thinking research partner, not an oracle and never a trading bot.

Deployment philosophy — local-first, cloud-portable
Market Lens runs locally on a Windows PC that stays on at home. This is the primary and default environment. However, the entire system must be architected so it can be migrated to a Linux cloud instance (DigitalOcean, AWS Lightsail, or similar) with zero code changes — only environment variable and process manager differences. This dual-instance portability is a hard design requirement, not an afterthought. See Section 3B for the full deployment specification.

2. How We Intend to Use It
The user is a retail investor operating under the following constraints and context:

Constraint / Context	Detail
Compute environment	Windows 10/11 PC running locally at home as the primary environment. Always-on home machine. Agent brain runs as a Windows background service via NSSM (Non-Sucking Service Manager — free). Cloud migration path preserved by design — see Section 3B.
User model	Single-user only. No authentication system. One watchlist, one set of API keys, one Telegram bot. Architecture must not prevent adding auth later but must not build it now.
Investment horizon	Primarily long-term holds (3-10 years) for Lynch-style conviction picks. Opportunistic swing trades (weeks to months) when signals align.
Target securities	US-listed equities, OTC ADRs of foreign companies (e.g. Assa Abloy ASAZY), ETFs for index and sector exposure, inverse ETFs for hedging. No mutual funds, no crypto.
Research philosophy	Peter Lynch: invest in what you observe, validate with fundamentals, ignore short-term noise, sell only when the thesis breaks — not when the price drops.
Data access	No Bloomberg terminal, no satellite data, no institutional alternative data. All sources must be free or low-cost public APIs. Edge comes from reading primary sources faster and more systematically than other retail investors.
Technical background	Graduate-level analytical skills. Comfortable with Python. Has worked with PostgreSQL and PyCharm. Beginner-to-intermediate on financial modeling. Needs the platform to explain calculations transparently.

3. System Architecture Overview
Build the platform as a modular Python application with a Streamlit dashboard frontend and a PostgreSQL database backend. Every module below is a separate Python file. The main dashboard imports and orchestrates them. Design for extensibility — new data sources and scoring modules should be addable without rewriting core logic.

3.1  Project Folder Structure
market_lens/
├── app.py                    # Streamlit dashboard entry point
├── agent.py                  # Agent Brain entry point — run as persistent background process
├── config.py                 # API keys, DB connection, user settings
├── database/
│   ├── models.py             # SQLAlchemy ORM models
│   ├── seed.py               # Initial watchlist seed data (Assa Abloy, Dolby, Sysco, JBHT)
│   └── watchlist.py          # Watchlist manager: add/remove/update any ticker dynamically at runtime
├── ingestion/
│   ├── edgar.py              # SEC EDGAR: 10-K, 10-Q, 8-K, Form 4, 13F
│   ├── leadership.py         # C-suite and board change tracker: 8-K Item 5.02 parser, tenure calculator, departure language classifier
│   ├── suppliers.py          # Supplier signal extractor: 10-K risk factor delta, earnings call keyword scan, ImportYeti customs data
│   ├── sector_scanner.py     # Weekly Saturday scan: all 11 GICS sectors, top 10 by market cap per sector, hidden giant detector
│   ├── anomaly.py            # IsolationForest anomaly detection on price/volume/sentiment time-series — the only ML component
│   ├── prices.py             # Stock prices via yfinance / Polygon
│   ├── options.py            # Layer 1: Tradier API raw chains + self-computed detection; Layer 2: Barchart free API; Layer 3: Market Chameleon scrape; cross-validates all three before alerting
│   ├── news.py               # News headlines and RSS feeds (3x daily)
│   ├── macro.py              # FRED API: rates, CPI, PMI
│   ├── court_dockets.py      # PACER federal court docket monitor
│   └── transcripts.py        # Earnings call transcript fetcher
├── processing/
│   ├── ocr.py                # PDF text extraction + Tesseract fallback
│   ├── nlp.py                # FinBERT sentiment on filings and news
│   ├── insider.py            # Form 4 parser: net buy/sell signals
│   └── institutional.py      # 13F change tracker
├── analysis/
│   ├── fundamentals.py       # Revenue growth, margins, FCF, debt ratios
│   ├── valuation.py          # DCF model, comps-based target, fair value range
│   ├── technicals.py         # MA, RSI, volume anomalies, support/resistance
│   └── scoring.py            # Weighted signal aggregator
├── agent/
│   ├── brain.py              # Core reasoning loop: perceive → compare → conclude
│   ├── memory.py             # Prior state store: last known scores and conclusions
│   ├── delta.py              # Change detector: is new info material to the thesis?
│   └── synthesizer.py        # Claude API: plain-English synthesis of what changed and why
├── alerts/
│   ├── watcher.py            # APScheduler job runner
│   └── notifier.py           # Telegram bot and email alerts
└── recommendation/
    └── engine.py             # Final Buy / Watch / Avoid / Short output + rationale

3B. Deployment Specification — Windows Local + Cloud Portable
Market Lens is designed to run on two environments without code changes. The application logic, database schema, scheduling, and agent brain are identical in both. Only the process manager and the .env file differ between environments.

Environment A — Windows Local (Primary)
This is the default and required deployment. The user runs Market Lens on a Windows 10 or 11 PC that stays powered on at home.

•	Python environment: use Python 3.11+ installed via python.org. Create a virtual environment in the project root: python -m venv venv. Activate with venv\Scripts\activate on Windows. All dependencies installed via pip install -r requirements.txt.
•	PostgreSQL: install PostgreSQL 15+ for Windows from postgresql.org. Use pgAdmin for database management. The user already has pgAdmin experience. Database name: market_lens. Connection string stored in .env as DATABASE_URL.
•	Running the dashboard: start Streamlit with: streamlit run app.py — this opens the dashboard in the browser at localhost:8501. The user opens this manually when they want to review the dashboard.
•	Running the agent brain as a Windows background service: use NSSM (Non-Sucking Service Manager) to register agent.py as a Windows Service that starts automatically on boot and restarts on failure. Install NSSM free from nssm.cc. Register with: nssm install MarketLensAgent python agent.py. This is the Windows equivalent of systemd on Linux — the agent brain runs continuously in the background regardless of whether the dashboard is open or any user is logged in.
•	Keeping the PC always on: configure Windows power settings to never sleep and never hibernate. Set display to turn off but keep the machine running. The agent brain will continue operating on schedule.
•	Logs: write all agent and ingestion logs to a logs/ directory in the project root. Use Python's rotating file handler (RotatingFileHandler) so logs do not grow unbounded. Cap each log file at 10MB with 5 backup files.

Environment B — Linux Cloud Instance (Migration Path)
When the user chooses to migrate to the cloud, the following changes apply. No application code changes. Only infrastructure differences.

•	Target: any Ubuntu 22.04 LTS VPS — DigitalOcean Droplet ($6/month), AWS Lightsail, or Hetzner (cheapest option at ~$4/month). Minimum 1GB RAM, 1 vCPU, 25GB SSD.
•	Process manager: replace NSSM with systemd. Create /etc/systemd/system/market-lens-agent.service unit file pointing to agent.py. Enable with: systemctl enable market-lens-agent. This is a direct functional equivalent of NSSM on Windows.
•	Dashboard access: run Streamlit behind an Nginx reverse proxy with HTTPS via Let's Encrypt. The user accesses the dashboard from any browser at their domain or IP. Alternatively, use an SSH tunnel for private access without exposing a public port.
•	Database: PostgreSQL installed on the same VPS instance. Same schema, same DATABASE_URL format in .env. No application code change.
•	Migration procedure: (1) export PostgreSQL database from Windows using pg_dump. (2) Copy project directory and .env to the VPS. (3) Restore database with pg_restore. (4) Register systemd service. (5) Verify agent brain resumes from last memory snapshot without re-running historical backfills.

What Makes the Code Environment-Agnostic
These are the hard rules Cursor must follow to ensure both environments work without code changes:

•	No Windows-specific path separators in code. Always use Python's pathlib.Path for all file paths — never hardcode backslashes. pathlib handles Windows and Linux transparently.
•	No hardcoded localhost assumptions. All connection strings come from .env variables. DATABASE_URL, REDIS_URL if added later, and all API base URLs must be configurable via environment variables.
•	No Windows-only libraries. Every dependency in requirements.txt must be installable on both Windows and Ubuntu Linux without modification.
•	Timezone handling: all internal timestamps stored as UTC in PostgreSQL (use TIMESTAMP WITH TIME ZONE columns). Only convert to Eastern Time for display in the Streamlit dashboard. Use the pytz library for conversion — never assume system timezone.
•	Process management abstraction: agent.py must be runnable as a plain Python script with: python agent.py. The process manager (NSSM on Windows, systemd on Linux) wraps it externally. agent.py itself has no OS-specific process management code.

3C. Dynamic Watchlist — Any Ticker, Any Time
Market Lens is not hardcoded to any specific list of companies. The four seed companies (Assa Abloy ASAZY, Dolby DLB, Sysco SYY, J.B. Hunt JBHT) exist only to populate the database for initial testing and validation. At any point after that, the user can add or remove any ticker — US-listed equities, OTC ADRs, ETFs, inverse ETFs, index funds, or mutual funds — and the entire platform immediately begins tracking it with the same depth it applies to the seed companies. This is a core product requirement, not an optional feature.

Supported Ticker Types
Ticker Type	Examples	Special Handling Notes
US exchange-listed equities	DLB, SYY, JBHT, CTAS, FAST, CPRT, VRSN	Full feature support. All modules apply: fundamentals, valuation, leadership, suppliers, options flow, court dockets, insider tracking.
OTC ADRs — foreign companies	ASAZY (Assa Abloy), SIEGY (Siemens), NSRGY (Nestle), ASML (Netherlands)	yfinance data may be incomplete or patchy. Data quality flag shown prominently on dashboard card. FX rate pulled from FRED for local-currency display alongside USD. Options flow modules degrade gracefully to N/A if no exchange data available.
ETFs — broad and sector	SPY, QQQ, XLF, XLE, TLT, IWM, GLD	No fundamentals scoring. No insider tracking. No supplier module. Leadership module disabled. Dashboard shows price chart, technical signals, and options flow only. Useful for tracking index exposure and sector swing setups.
Inverse ETFs	SQQQ, SPXS, SRTY, SOXS	Same as ETFs above. Dashboard prominently displays decay warning: inverse ETFs are for short-term positioning only — not long-term holds.
Mutual funds	VTSAX, FXAIX	NAV price tracking only. No options, no fundamentals, no leadership, no insider tracking. Flag clearly as mutual fund — no short selling possible. Return metrics and dividend history displayed.
Fund tickers via ticker search	Any fund ticker the user provides	Market Lens auto-classifies the instrument type on add. If classification is uncertain, prompt the user to confirm before proceeding with data ingestion.

How Adding Any Ticker Works — End to End
When the user types any company name, ticker symbol, or fund name into the Add to Watchlist field in the dashboard, the following sequence executes automatically:

•	If the user types a company name (e.g. 'Cintas' or 'Assa Abloy') rather than a ticker, run a search using yfinance's search functionality and return the top 3 matches with their tickers for the user to confirm. If the user types a ticker directly, validate it against yfinance and Alpha Vantage. If both return no data, surface an error and do not add. Step 1 — Ticker search and validation:
•	Classify as equity, OTC ADR, ETF, inverse ETF, or mutual fund based on the metadata returned. Store in companies.instrument_type. This classification governs which modules run. Show the classification to the user and allow manual override before confirming the add. Step 2 — Instrument type auto-classification:
•	Before completing the add, show a text field: 'Why are you watching this? (Optional — your Lynch observation)'. This is the thesis_notes field. Pre-populate with a prompt like: 'What did you observe about this company in real life that made you look it up?' The user can fill it in now or later from the dashboard. Step 3 — Thesis note prompt:
•	Queue a background job immediately to pull 5 years of price history, last 4 quarterly filings (equities only), last 3 years of 8-K leadership filings (equities only), and last 90 days of Form 4 insider transactions (equities only). The ticker appears in the watchlist immediately with a loading indicator — the user does not wait for the backfill to complete. Step 4 — Historical backfill:
•	The new ticker is registered in agent_memory with a blank prior state snapshot. The agent brain picks it up on its next scheduled cycle automatically. No restart of agent.py required. Step 5 — Agent brain auto-registration:
•	Once historical backfill completes, scoring.py runs automatically and generates the first Lynch score and swing score. The dashboard status updates from loading to the score label. Step 6 — First score computation:

Thesis Notes — The Lynch Observation Field
Every ticker on the watchlist has a thesis_notes free text field. This is where the user records why they added the company — the personal observation that triggered the research. This field is passed to the Claude API synthesis prompt on every agent brain reasoning cycle. Every materiality judgment the brain makes is grounded in the original thesis, not generic analysis. A court case against Dolby is reasoned about differently when the thesis note says 'licensing moat dependent on royalty enforcement' versus a generic note. This field makes every agent brain output personal and specific.

Removing or Pausing a Ticker
Removing a ticker sets active = false in the companies table. No historical data is deleted. All scores, filings, sentiment records, supplier signals, leadership events, and agent synthesis logs are retained permanently. The agent brain stops monitoring inactive tickers immediately. Reactivating a ticker resumes full monitoring from the last memory snapshot without re-running historical backfills. A separate paused state allows the user to temporarily stop monitoring without removing the thesis note and history.

4. Data Sources and APIs to Implement
All sources below are free unless marked [PAID]. Implement them in the order listed — the first four are the highest priority and cover 80% of the analytical value.

Source	What It Provides	Implementation Notes
SEC EDGAR REST API	10-K, 10-Q, 8-K filings; Form 4 insider transactions; 13F institutional holdings	Free, no API key. Base URL: data.sec.gov. Set User-Agent header to your email per EDGAR policy. Poll every 30 min during market hours.
yfinance (Python lib)	Historical prices, P/E, EPS, dividend history, market cap, beta	Free. pip install yfinance. Use for all price history and basic fundamentals. Cache results in PostgreSQL to avoid repeat calls.
FRED API	Fed funds rate, CPI, unemployment, PMI, yield curve data	Free API key from fred.stlouisfed.org. Pull weekly. Store in macro_data table. Used to contextualize valuations and sector risk.
NewsAPI.org	News headlines from 80,000+ sources filtered by company ticker or name	Free tier: 100 requests/day. Paid tier for production. Feed into FinBERT sentiment pipeline. Store sentiment score per article per company.
Tradier API (options chains — free)	Raw options chain data including volume, open interest, Greeks, and IV for every watchlist ticker	Free developer tier at developer.tradier.com. Market Lens computes unusual volume detection itself: flag any contract where (today volume / open interest) > 0.5 AND volume exceeds 3x the 20-day average. This is Layer 1 of a three-source cross-validation system. Requires free Tradier developer account.
Barchart API (options flow — free tier)	Unusual options activity feed sourced directly from exchange data, returned as structured JSON	Free API tier at barchart.com/cmdtyview/cmdty-data/barchart-api. This is a real structured API endpoint, not a scrape. Use as Layer 2 cross-validation against Tradier-computed signals. An alert is only elevated when both Tradier detection and Barchart flag the same ticker on the same day.
Market Chameleon (options flow — scrape)	High-quality unusual options activity report sourced directly from exchange feeds at marketchameleon.com/Reports/OptionsActivityReport	No official API — scrape with BeautifulSoup. Data quality is high enough to justify the scraping approach. Use as Layer 3 confirmation only for high-conviction signals. Fire a swing alert only when at least two of the three sources (Tradier, Barchart, Market Chameleon) agree a ticker has unusual activity. This cross-validation eliminates most false positives.
WhaleStream API [PAID — optional upgrade]	Real-time sweep detection, dark pool prints, and consolidated institutional options flow direct from OPRA exchange feed	Only add if the three-layer free stack proves insufficient during testing. Real-time options data, dark pool delayed 15 minutes per exchange rules. Do not implement until Phases 1-14 are complete and you have validated the free layer performance.
Unusual Whales API [PAID — last resort]	Unusual options volume, dark pool flow, congressional trading	~$50/month. Last resort only. The three free layers (Tradier + Barchart + Market Chameleon) cover the same signals programmatically with full transparency into detection logic. Add only if you identify a specific signal gap the free stack cannot cover.
Alpha Vantage	Earnings calendar, income statement, balance sheet, cash flow	Free tier: 25 requests/day. Use for structured financial statement data to supplement yfinance. Good for historical quarterly breakdowns.
Polygon.io [PAID optional]	Real-time and historical tick data, options chains, news	Free tier limited. Paid from $29/month. Add only if you want intraday price data. Not required for Lynch-style long-term research.
Seeking Alpha RSS / IR pages	Earnings call transcripts	Scrape transcript text from company investor relations pages. Feed into FinBERT and keyword analysis. No official API — use BeautifulSoup.
SEC EDGAR 8-K Item 5.02	Director and officer appointment and departure disclosures — every C-suite change at a public company must be filed within 4 business days	Already covered by the EDGAR RSS feed in edgar.py. leadership.py specifically filters for Item 5.02 filings, parses the departure language, and computes tenure from the prior appointment filing. Classify departure language into three buckets: planned (retirement, succession), abrupt (effective immediately, no reason given), and forced (board-initiated, activist pressure visible in prior proxy filings).
ImportYeti (trade data — free)	U.S. Customs import manifests showing which companies are importing from which suppliers, with shipment volumes and frequencies	Free at importyeti.com. No official API — scrape search results by company name. If a watchlist company stops receiving shipments from a known supplier and a new supplier name appears in manifests, this is a supplier switch signal that predates any 10-K disclosure. Particularly powerful for manufacturers and distributors. Panjiva is the paid institutional version of the same data — ImportYeti covers the same U.S. Customs records for free.
PACER (federal courts) [PAID per page]	Federal civil and bankruptcy case filings against watchlist companies	pacer.uscourts.gov. Charged per page (~$0.10). CRITICAL INSTRUCTION: PACER is the fallback of last resort. court_dockets.py must always attempt CourtListener first. Only call PACER if and only if CourtListener returns zero results for a specific case number or the filing is confirmed to not exist in the CourtListener database. Never call PACER in bulk or on a schedule — only on-demand for specific missing cases. Most relevant for patent-heavy companies like Dolby. Implement a pacer_needed flag in the cases table — set it only when CourtListener explicitly fails.
House Clerk STOCK Act disclosures (free)	All House member periodic transaction reports — every stock trade over $1,000 filed within 45 days of transaction	Official government XML feed at disclosures.house.gov/FinancialDisclosure. Free, no API key. This is the primary source Quiver Quantitative, Capitol Trades, and every other tracker uses. Parse XML directly. Supplement with Financial Modeling Prep free tier (financialmodelingprep.com) which returns pre-parsed JSON for both House and Senate trades — faster to implement, cross-validate against official source.
Senate STOCK Act disclosures (free)	All Senate member periodic transaction reports	Official Senate Electronic Financial Transaction System (EFTS) at efts.senate.gov. Free JSON API. Same logic as House — parse official feed, cross-validate with FMP free tier.
Congress.gov API (free)	Committee assignments and membership for all current members of Congress	api.congress.gov — free API key. Required for the committee cross-reference module: identify which committees each trading member sits on or chairs, and correlate with the sectors they are trading in.
Financial Modeling Prep — congressional trades (free tier)	Pre-parsed JSON endpoint for both Senate and House STOCK Act trade disclosures	Free tier at financialmodelingprep.com. Endpoints: /api/v4/senate-disclosure and /api/v4/house-disclosure. Returns structured JSON with member name, ticker, transaction type, amount range, trade date, and disclosure date. Use as the primary ingestion layer — faster than parsing raw government XML. Cross-check against official feeds for any high-signal trades before alerting.

4B. The Agent Brain — Active Reasoning Loop
The Agent Brain is a separate persistent process (agent.py) that runs independently of the Streamlit dashboard. It does not wait for the user to open the app. It perceives new information on a schedule, compares it against what it concluded previously, and determines whether anything has materially changed. Think of it as the part of the platform that keeps paying attention when you are not.

How the Agent Brain Loop Works
The brain runs one continuous loop on a schedule. Each cycle has four steps:

Step 1 — Perceive
Ingest all new data since the last cycle. This includes: news pulled three times daily (9am, 12pm, 5pm ET), EDGAR RSS feed checked every 30 minutes for new 8-K and Form 4 filings, court docket scan run once daily per watchlist company, options flow checked every 15 minutes during market hours, and macro data (FRED) refreshed weekly. All new data is written to the database with an ingested_at timestamp.

Step 2 — Compare
For each watchlist company, the delta.py module compares the current state of all signals against the last stored snapshot in memory.py. It asks: has the news sentiment score shifted by more than 0.15 since yesterday? Has a new court case been opened? Has an 8-K been filed since the last cycle? Has insider net buy score flipped from positive to negative? Has the Lynch score moved by 5+ points? These are delta triggers, not raw thresholds.

Step 3 — Reason (pattern-aware, not just event-aware)
When a delta is detected, the brain calls the Claude API (synthesizer.py) with four inputs, not two. Input 1: the user's original thesis note in plain English — why they own this stock. Input 2: the prior state snapshot as structured JSON. Input 3: all new data that triggered the delta. Input 4 (the critical upgrade): a 90-day compressed signal history for this company — a structured summary of every material event, sentiment shift, score change, insider transaction, and court filing logged in the past 90 days alongside what the stock price did during that same period. This fourth input is what separates pattern reasoning from event reaction. The prompt explicitly instructs the brain to ask: does today's signal fit a pattern visible in the last 90 days, or is it an isolated event? A single insider sale is noise. Three insider sales across three months while revenue growth is decelerating is a pattern. The brain should identify and name patterns, not just evaluate individual events.

Step 4 — Notify
If the synthesis concludes the change is material, the brain sends a proactive Telegram alert to the user with the plain-English reasoning paragraph, the specific data that triggered it, and a direct link to the company dashboard card. If it is noise, the brain logs it internally but does not alert — protecting the user from alert fatigue.

News Reading Schedule — Three Times Daily
Time (ET)	What Is Read	Why This Window
9:00 AM	Overnight news, pre-market SEC filings, earnings releases from prior day after-hours	Sets context before market open. Catches any 8-K or earnings drop that happened overnight.
12:00 PM	Breaking news since open, any 8-K or Form 4 filed during morning session, options flow anomalies	Midday check catches fast-moving developments. Earnings guidance updates often drop mid-morning.
5:00 PM	Post-close earnings releases, after-hours SEC filings, end-of-day sentiment summary	Most earnings releases drop 4-5pm ET. This is the highest-value window for the platform to catch before the next trading day.

Court Docket Monitoring — What to Watch For
Court dockets are one of the most underused public data sources in retail investing. A new lawsuit or regulatory action filed against a company often appears in federal court records days or weeks before it becomes news. The agent brain monitors for:

•	New civil complaints naming a watchlist company as defendant — especially patent infringement, securities fraud (which precedes class action suits), antitrust, or contract disputes above $10M.
•	Bankruptcy filings by major customers or suppliers of watchlist companies — a major Sysco customer chain filing Chapter 11 is a revenue risk signal.
•	Regulatory enforcement actions from the SEC, FTC, or DOJ — these often appear on PACER before press releases.
•	Patent inter partes review (IPR) petitions at the USPTO PTAB — directly relevant to Dolby given their licensing-dependent business model. USPTO PTAB has its own free search API at developer.uspto.gov.

Implementation note for court_dockets.py — this is a hard rule, not a preference: CourtListener is always called first on every scan cycle. PACER is never called on a schedule. PACER is only called manually and on-demand when a specific case number has been identified through CourtListener or another source, and the full docket text is needed but is not available in the CourtListener mirror. The cases table has a pacer_needed boolean column — it is set to true only by explicit manual review, never by automated logic. This prevents unexpected PACER charges.

Leadership Instability Detection
Abnormal C-suite and board turnover is one of the most reliable early warning signals in investing. The GE example is the textbook case — between 2017 and 2021, the company cycled through CEOs, CFOs, and division heads while each individual press release had a plausible explanation. The pattern across all of them together was the real signal: the board had lost confidence in its own strategy, not just its people. Market Lens tracks this at the pattern level, not the individual event level.

leadership.py monitors every 8-K Item 5.02 filing (director and officer changes) for all watchlist companies. Every C-suite event is logged in leadership_events with tenure calculated from the prior appointment filing. The agent brain then applies pattern detection via leadership_velocity:

•	Two or more changes in the same C-suite role within 18 months triggers an instability flag regardless of the stated departure reasons.
•	Departure language is classified into three buckets: planned (retirement, planned succession, multi-quarter notice), abrupt (effective immediately, no reason stated, short tenure under 18 months), and forced (activist investor visible in prior proxy, board-initiated language, equity vesting accelerated post-departure).
•	Equity acceleration check: when an executive departs, check their Form 4 filing in the 30 days following departure. Accelerated vesting of unvested equity is a strong signal of a negotiated exit rather than a voluntary one — companies do not accelerate vesting for clean voluntary departures.
•	Board composition changes: track proxy statement (DEF 14A) filings for new director appointments. An activist investor joining the board — identifiable by cross-referencing director names against known activist fund principals — is a leading indicator of forced CEO turnover, not a lagging one.
•	Interim role flag: an interim title on any C-suite role beyond 90 days is a red flag. Planned transitions have successors ready. Extended interim periods signal the board cannot agree on direction.

What the agent brain does with leadership signals
When an instability flag is set in leadership_velocity, the brain calls the synthesizer with the full event history, the tenure calculations, the departure language classifications, and the current Lynch score. It then reasons: is this a company executing a planned succession (Microsoft 2014, Apple 2011) or a company in organizational distress (GE 2017-2021, Boeing 2019-2020)? The distinction is in the pattern and the language, not the individual events. The synthesis paragraph tells the user which pattern the data resembles and what to watch next.

Supplier Intelligence and Switch Detection
Supplier switching is one of the most undertracked signals in retail investing. When a company quietly changes a critical component supplier, it often signals margin pressure, quality problems, geopolitical risk response, or financial distress at the incumbent supplier — any of which can affect the company you hold. None of this appears in a stock screener. It appears in filings, transcripts, and customs records if you read for it systematically.

Where supplier intelligence actually hides:
•	The cosine similarity analysis in nlp.py already flags when the Risk Factors section changes meaningfully between annual filings. suppliers.py goes one level deeper — it extracts named suppliers from the Risk Factors section and tracks which supplier names appear, disappear, or change in concentration language from one year to the next. A supplier name disappearing from risk disclosures does not mean the risk went away — it may mean the relationship changed. 10-K Risk Factors year-over-year delta:
•	FinBERT sentiment alone will not catch supplier switching language. suppliers.py applies a separate keyword extraction pass on every earnings call transcript looking for operationally specific phrases: 'transitioning our supply base', 'qualifying a new supplier', 'dual sourcing', 'single source', 'supply chain diversification', 'moving away from', 'new manufacturing partner', 'strategic sourcing'. When these phrases appear, the context sentence is stored in supplier_signals for agent brain review. Earnings call transcript keyword scan:
•	Large supplier agreements and terminations may trigger an 8-K material contract disclosure. The EDGAR RSS feed already captures these — suppliers.py filters 8-K full text for contract-related language and flags those involving supply, manufacturing, sourcing, or procurement terms. 8-K material contracts:
•	U.S. Customs import manifests are public record. ImportYeti provides free search of these records by company name. If a manufacturer watchlist company stops receiving shipments from a known supplier and a new supplier name begins appearing in manifests, this is a supplier switch signal that predates any SEC filing by weeks or months. Scrape ImportYeti for each manufacturing or distribution company on the watchlist on a monthly schedule. Compare the active supplier list to the prior month and flag new entrants and departures. ImportYeti customs data:

The supplier reliability registry:
When a supplier switch or new supplier is detected, the agent brain does not just flag it — it triggers a secondary research task. The new supplier name is added to the supplier_registry table and the brain generates a research prompt using the Claude API: given the supplier name, the industry context, and the switching company, research the supplier's financial health, geographic concentration risk, any known quality issues, and whether other major customers have recently reduced reliance on them. The output is a reliability assessment stored in the registry that gets factored into the watchlist company's Lynch score going forward.

•	A supplier with known financial distress (high debt, recent credit rating downgrade, own leadership instability) increases the supply chain risk component of the Lynch score for every company that uses them.
•	Geographic concentration risk: a supplier based entirely in one country or one region adds geopolitical risk that the agent brain should flag, especially in the current environment of tariff volatility and export controls.
•	The supplier_registry is user-maintained and persistent — once you research a supplier and assign a reliability score, that assessment is retained across all future analyses involving that supplier across all watchlist companies.

5. OCR and Document Processing Pipeline
SEC filings arrive in two forms: machine-readable HTML/XML (most post-2010 filings) and scanned PDFs (older filings and some proxy statements). The processing pipeline must handle both gracefully.

Processing order — always try in this sequence:
•	Try the EDGAR company facts API first (data.sec.gov/api/xbrl/companyfacts/). This returns pre-parsed JSON of all financial line items. Fastest and most reliable for post-2009 filings. Step 1 — EDGAR structured data:
•	If the filing is a PDF with embedded text layers, extract with pdfplumber. This handles most modern 10-K and 10-Q PDFs cleanly without OCR. Step 2 — pdfplumber / PyMuPDF:
•	Fallback for scanned PDFs. Use pytesseract with preprocessing (grayscale, threshold, deskew via OpenCV). Accuracy is ~92-95% on clean scans. Sufficient for text extraction — not sufficient for table parsing. Step 3 — Tesseract OCR:
•	For financial tables in scanned documents where Tesseract fails. Only invoke on demand, not in automated batch runs, to control cost. Step 4 — AWS Textract or Google Document AI [PAID]:

For Form 4 insider transactions specifically: EDGAR returns these as structured XML. Parse directly using Python's xml.etree.ElementTree. Do not use OCR for Form 4s — it is unnecessary.

4C. Weekly Sector Scanner — Every Saturday
Every Saturday, Market Lens runs a full market-wide scan across all 11 GICS sectors. This is not a watchlist feature — it scans the entire market regardless of what the user currently tracks. The purpose is twofold: give the user a weekly pulse on where the market is and what is moving, and surface companies the user has never heard of but should be watching — the Westlake Financial problem, meaning dominant businesses hiding in plain sight that almost no retail investor knows by name despite interacting with their products or services constantly.

The 11 GICS Sectors
The scan covers all 11 Global Industry Classification Standard sectors without exception: Information Technology, Health Care, Financials, Consumer Discretionary, Communication Services, Industrials, Consumer Staples, Energy, Utilities, Real Estate, and Materials.

What the Scanner Does Per Sector
•	Pull the 10 largest companies by current market cap in each sector using yfinance sector filtering supplemented by Financial Modeling Prep's sector endpoint. For each of the 10, compute: current price, 1-week return, 1-month return, YTD return, P/E ratio, revenue growth last reported quarter YoY, and analyst consensus if available. Store in sector_scan_results with the scan date. Step 1 — Top 10 by market cap:
•	Pass each company's metrics to the Claude API with a brief prompt: given these metrics and the current macro environment (pulled from macro_data table), write one sentence on where this company stands right now. Not a buy/sell call — a plain-English state of play. Step 2 — Current state assessment:
•	After the top 10 by market cap, run a second pass to find companies that simultaneously meet: market cap above $5 billion, revenue above $2 billion, a consumer-facing or B2B2C business model, and a low brand awareness proxy score. The brand awareness proxy is computed as: Google Trends interest score for the company name divided by market cap in billions. A company with $40B market cap and near-zero public search interest is a hidden giant candidate. Flag these for the weekly digest. Step 3 — Hidden giant detection:
•	After all 110 entries are scored (11 sectors × 10 companies), the Claude API generates a Saturday digest: one sentence on the state of each sector, the top 3 hidden giants found, and a short list of companies worth adding to the watchlist for deeper research. Delivered via Telegram Saturday evening and stored in the Weekly Digest dashboard tab. Step 4 — Weekly digest generation:

Hidden Giant Detection — What This Should Find
The hidden giant detector is calibrated specifically for companies that are enormous in scale but invisible in casual conversation. Examples of the kind of companies this feature should surface:

•	Westlake Financial — one of the largest US auto lenders, primarily subprime. Millions of Americans have Westlake auto loans. Almost no one knows the company name by sight.
•	Cintas — $80B+ market cap, uniform and workwear services for over 1 million businesses. Their trucks are on every highway. Most people cannot name the company.
•	Fastenal — $45B+ market cap, industrial fasteners and supplies for construction and manufacturing. Everywhere in the physical economy. Zero consumer brand recognition.
•	Copart — $50B+ market cap, dominant online vehicle auction platform for salvage and used cars. Processes millions of vehicles per year. Unknown outside the auto industry.
•	Verisk Analytics — $35B+ market cap, data analytics for insurance and energy. Every major insurer uses their data. Zero public name recognition.

Sector Scanner Database Tables
•	sector_scan_results: scan_date, sector, ticker, company_name, market_cap, rank_in_sector, price, week_return, month_return, ytd_return, pe_ratio, revenue_growth_yoy, analyst_consensus, one_sentence_state, hidden_giant_flag, brand_awareness_ratio
•	weekly_digest: digest_date, full_digest_text, sector_summaries_json, hidden_giants_json, watchlist_suggestions_json, delivered_telegram (boolean)

4D. Congressional Trading Tracker
Members of Congress are legally required under the STOCK Act of 2012 to publicly disclose any stock trade exceeding $1,000 within 45 days of the transaction. This is fully public data. Market Lens ingests it, identifies the 50 most active traders in Congress, cross-references their committee assignments, and surfaces the most important pattern: when a member who sits on a committee with oversight over a sector makes a trade in that sector, that is information worth noting immediately.

Where the Data Comes From — How Quiver Quantitative Does It
Quiver Quantitative, Capitol Trades, and every congressional trade tracker pull from the same two official government sources. The House Clerk disclosure portal at disclosures.house.gov and the Senate Electronic Financial Transaction System at efts.senate.gov. Both are free. Market Lens uses the Financial Modeling Prep free API as the primary ingestion layer because it returns pre-parsed structured JSON for both chambers — much faster to implement than parsing raw government XML directly. The official government feeds are used as the verification fallback for any high-signal trade before alerting. Committee assignment data comes from the Congress.gov API which requires a free API key.

The Top 50 Active Traders List
On first run, congress_tracker.py pulls all available historical disclosures and computes a trading frequency score for every member: total trades in the past 12 months, total disclosed volume using the midpoint of amount ranges, and sector concentration percentage. Rank all 535 members by trading frequency and designate the top 50 as actively tracked. This list updates monthly.

•	The top 50 tracked members trigger immediate Telegram alerts on every new disclosure. All 535 members have their trades logged in the database regardless of tracked status.
•	The user can manually add any member to the tracked list regardless of trading frequency — for example, a specific committee chair whose policy domain overlaps with watchlist companies.

The Committee-Trade Correlation — The Core Signal
For every trade by a tracked member, congress_tracker.py runs a committee cross-reference:

•	Pull the trading member's current committee assignments from the Congress.gov API.
•	Identify the GICS sector of the traded company via yfinance or the sector_scan_results table.
•	Check the committee_sector_map lookup table to see if any of the member's committees have oversight jurisdiction over that sector.
•	If yes, flag the trade as committee-correlated — the most important classification in the entire congressional tracker. The alert explicitly names the committee, the sector, and the trade.
•	If three or more members from the same committee trade the same sector within a 30-day window, flag as a cluster trade — the highest-priority signal. This is the pattern that preceded multiple notable market events in recent years.

Committee-to-sector jurisdiction map (hardcoded, user-extensible)
Senate Banking → Financials, Real Estate. Senate Armed Services → Defense, Aerospace, Industrials. House/Senate Energy and Commerce → Energy, Utilities, Health Care. Senate Finance → Health Care, Insurance, Financials. House/Senate Intelligence → Information Technology, Cybersecurity, Communications. Senate Agriculture → Consumer Staples, Materials. House Transportation → Industrials, Logistics. This map is stored in the committee_sector_map table and the user can add custom mappings as needed.

Congressional Tracker Alerts
•	New trade by tracked member — Telegram within 4 hours of FMP update: member name, ticker, buy or sell, amount range, days since trade date, committee correlation flag.
•	Committee-correlated trade — Telegram immediately: '[Member] sits on [Committee] which oversees [Sector]. They just [bought/sold] [Ticker].'
•	Cluster trade — Telegram + email immediately: '3+ members of [Committee] traded [Sector] in the past 30 days.'
•	Build a disclosure_timing_profile for each tracked member — their average days-to-disclose and standard deviation computed from all historical filings. If a member who typically files within 5 days goes 20+ days silent, flag it. That silence likely means a trade has been made but not yet disclosed. This turns the gap into a signal rather than a blind spot. Disclosure timing profile per member:
•	Congress.gov publishes all upcoming committee hearings and legislative markups in advance. When a committee with oversight over a sector schedules a significant hearing or markup, every member of that committee becomes a watch candidate for a trade in the following 2-4 weeks — before any disclosure is filed. congress_tracker.py monitors the Congress.gov hearing schedule and cross-references it against tracked members' committee assignments. This is the single most powerful way to get ahead of the disclosure window. Committee hearing calendar — the leading indicator:
•	The Senate Lobbying Disclosure Act database at lda.senate.gov shows which companies are actively lobbying which congressional offices in real time. When a company registers new lobbying activity targeting a specific committee, that is a leading indicator of upcoming legislative action and potential correlated trades. Scrape lda.senate.gov for new registrations weekly and cross-reference against the committee_sector_map. Lobbying registration monitoring:
•	When a significant floor vote happens on legislation affecting a specific sector, flag every tracked member who voted on it as being in a 30-day watch window. A member who votes on healthcare legislation and then goes quiet on disclosures for three weeks is the highest-priority watch case in the entire congressional tracker. Post-vote trade watch window:

Beating the Disclosure Time Gap — Forward-Looking Signals
The 45-day disclosure window — and the reality that many members pay the $200 fine and file even later — means the trade disclosure itself is almost never actionable in real time. The price move has usually already happened. The correct approach is to stop waiting for the disclosure and start reading the upstream signals that precede it. Market Lens uses three forward-looking layers to close this gap:

•	Committee hearing schedules are published publicly on congress.gov days or weeks in advance. congress_tracker.py monitors the hearing calendar via the Congress.gov API and flags any hearing whose stated topic overlaps with a watchlist company sector. A Senate Armed Services Committee hearing on semiconductor supply chain security is a materially relevant event for any semiconductor company on the watchlist — before any trade is disclosed. Hearing calendar alerts fire the day a relevant hearing is scheduled, not when a trade is later disclosed. Layer 1 — Congressional hearing calendar:
•	When legislation that would materially affect a sector is introduced or advances through committee markup, that event is public on congress.gov in real time. The members on that committee knew about it before it was public. congress_tracker.py monitors bill activity filtered by the same committee_sector_map used for trade correlation. A healthcare pricing bill advancing through Senate Finance is a forward signal for health insurance and pharmaceutical sectors — flagged immediately on introduction, not when member trades surface weeks later. Layer 2 — Bill introduction and markup tracking:
•	The most powerful forward signal is when unusual options activity in a sector coincides with committee action on that sector. When the Senate Finance Committee schedules a drug pricing markup and the options flow module simultaneously detects unusual call buying in health insurance stocks, those two signals together — neither explainable by earnings or news — constitute a composite signal more meaningful than either alone. The agent brain synthesis prompt explicitly checks for this cross-module coincidence on every cycle. Layer 3 — Options flow and congressional signal cross-reference:

The right mental model for congressional data
Disclosure data is most valuable as a historical pattern builder, not a real-time signal. Over 12-24 months of data collection, Market Lens builds a map of which members consistently trade ahead of specific committee actions. Once that map exists, the committee hearing calendar becomes the real leading indicator and the eventual disclosure becomes confirmation of a pattern already identified. The goal is to be watching the right sectors before the disclosure, not reacting to it after.

Congressional Tracker Database Tables
•	congress_members: member_id, name, chamber, party, state, committees (JSON array), tracked, manually_tracked, trade_count_12mo, trade_volume_12mo, top_sector, last_updated
•	congress_trades: trade_id, member_id, ticker, company_name, sector, transaction_type, amount_range_low, amount_range_high, trade_date, disclosure_date, days_to_disclose, committee_correlated, matching_committees (JSON array), cluster_flag, source
•	committee_sector_map: committee_name, chamber, jurisdiction_sectors (JSON array) — hardcoded and user-extensible
•	disclosure_timing_profile: member_id, avg_days_to_disclose, stddev_days, min_days, max_days, last_30day_silence_flag, last_updated — per-member historical disclosure timing profile used to detect likely undisclosed trades
•	lobbying_registrations: registration_id, registrant_name, client_name, filing_date, covered_officials (JSON), sector_keywords, committee_match (boolean), flagged — scraped from lda.senate.gov, cross-referenced against committee_sector_map
•	committee_hearings: hearing_id, committee_name, chamber, hearing_date, subject, sector_relevance (JSON), member_watch_window_triggered (boolean) — populated from Congress.gov hearing schedule API
•	congress_hearings: hearing_id, committee_name, chamber, hearing_date, hearing_title, topic_keywords (JSON array), relevant_sectors (JSON array), relevant_watchlist_tickers (JSON array), alerted (boolean) — forward-looking calendar monitoring table
•	congress_bills: bill_id, bill_number, title, introduced_date, last_action_date, last_action_type, relevant_committees (JSON array), relevant_sectors (JSON array), relevant_watchlist_tickers (JSON array), status, alerted (boolean)

6. Analysis Modules — Logic and Calculations
6.1  Fundamentals Module
Compute the following for every company in the watchlist on a quarterly schedule. Store all values in the database with timestamp so trends are trackable over time.

•	Revenue growth: 1Y, 3Y, and 5Y CAGR. Flag if 3Y CAGR is below 3% (stagnation signal).
•	Gross margin trend: compare current vs 3-year average. Declining gross margin is an early warning of competitive pressure.
•	Free cash flow yield: FCF per share divided by current price. Above 4% is generally attractive.
•	Net debt / EBITDA: flag anything above 3x as elevated leverage.
•	P/E vs own 5-year average: if current P/E is more than 20% below the 5-year average, flag as potentially undervalued. This was the Dolby signal.
•	P/E vs sector median: pull sector peers using yfinance sector classification. Compare to median.
•	Payout ratio: for dividend-paying stocks, flag if above 75% (sustainability concern).
•	Dividend growth streak: consecutive years of dividend increases. Weight this positively in the long-term hold score.

6.2  Valuation Module — Price Target Calculation
This is where the $170 or $226 type targets come from. Implement three methods and output a range, not a single number. Never present false precision.

Method 1 — Discounted Cash Flow (DCF)
Inputs: trailing twelve-month free cash flow, user-adjustable growth rate (default: 3-year revenue CAGR), discount rate (default: 10%), terminal growth rate (default: 3%), projection period (default: 10 years). Output: intrinsic value per share. Display sensitivity table showing how fair value changes if growth rate ±2% and discount rate ±1%. This prevents overconfidence in a single number.

Method 2 — Comparable Company (Comps)
Pull 5 sector peers using yfinance. Compute median P/E and EV/EBITDA for the peer group. Apply median multiple to the subject company's EPS and EBITDA. Output implied price from each multiple. Average the two for a comps-based target.

Method 3 — Historical Multiple Mean Reversion
Compute the company's own 5-year average P/E. If current P/E is below that average, the mean reversion target = 5-year average P/E multiplied by current EPS. This is the most intuitive signal for a range-bound undervalued stock. This is exactly the signal present on Dolby right now.

Final output: a fair value range defined as [lowest of three methods, highest of three methods]. Label the current price relative to this range: BELOW RANGE / WITHIN RANGE / ABOVE RANGE. Do not output a single price target.

6.3  Technical Signals Module
Used for swing timing and entry/exit decisions on stocks already in the watchlist. Not used for long-term hold scoring.

•	50-day and 200-day simple moving average: flag golden cross (50 crosses above 200, bullish) and death cross (50 crosses below 200, bearish).
•	RSI (14-period): below 30 = oversold / potential entry. Above 70 = overbought / potential exit or short candidate.
•	Volume anomaly: flag any session where volume exceeds 2x the 20-day average. These are the sessions that precede major moves.
•	Support and resistance: compute rolling 52-week high and low. Flag when price approaches within 3% of either level.
•	options.py runs three independent checks and only flags a signal when at least two of three sources agree. Layer 1 (Tradier): pull raw options chain, compute volume-to-open-interest ratio and compare to 20-day average volume — flag contracts where ratio exceeds 0.5 and volume exceeds 3x the 20-day average. Layer 2 (Barchart free API): query the Barchart unusual activity endpoint for the same ticker and check if it independently flags unusual activity on the same day. Layer 3 (Market Chameleon scrape): scrape the unusual options activity report at marketchameleon.com/Reports/OptionsActivityReport using BeautifulSoup and check for the same ticker. Cross-validation rule: a swing alert is only generated when at least two of three sources flag the same ticker on the same day. Store each source result independently in the database so you can audit which sources fired on each signal. Unusual options volume — three-source cross-validation:

6.4  Insider and Institutional Signal Module
This is the most underrated signal available to retail investors. Parse Form 4 filings from EDGAR in real time.

•	Net insider score: for each company, sum all open market buys and sells by insiders over the trailing 90 days. A net buy score (more shares purchased than sold, excluding option exercises) is a positive signal. Flag cluster buying — when 3 or more distinct insiders buy within a 30-day window.
•	13F institutional change: compare the two most recent 13F filings for major holders. Flag if a top-10 holder reduced position by more than 10% in a single quarter.
•	Form 4 alert: trigger an immediate Telegram notification when any C-suite insider (CEO, CFO, COO, President) files a Form 4 for an open-market purchase or sale above $100,000.

6.5  NLP Sentiment Module
Use FinBERT (financial domain BERT, available free on HuggingFace as ProsusAI/finbert) for all text analysis. Do not use general-purpose sentiment models — they perform poorly on financial language.

•	Earnings call transcript analysis: score each paragraph of the transcript as positive, neutral, or negative. Flag paragraphs where management language shifts from prior quarter. Watch specifically for new mentions of: headwinds, challenged, uncertainty, softness, delayed, cautious.
•	News sentiment score: compute a 7-day rolling average sentiment score per company from news headlines. A score dropping below -0.3 on a -1 to +1 scale is a flag worth investigating.
•	10-K year-over-year language delta: compare the Risk Factors section of the most recent 10-K to the prior year using cosine similarity. A low similarity score means management added meaningfully new risk disclosures — investigate what changed.

7. Scoring Engine and Recommendation Output
The scoring engine aggregates all signals into two separate scores depending on the investment mode. Weights are adjustable by the user in config.py.

7.1  Long-Term Hold Score (Lynch Mode)
Signal	Default Weight	Rationale
Revenue growth (3Y CAGR)	18%	Core health of business
FCF yield vs sector	13%	Capital efficiency
P/E vs own 5Y average	13%	Historical valuation context
Insider net buy score	13%	Skin in the game signal
Gross margin trend	10%	Competitive moat indicator
Dividend growth streak	8%	Management capital discipline
Debt / EBITDA ratio	8%	Balance sheet safety
Leadership stability score	10%	C-suite and board velocity — penalizes abnormal turnover pattern
Supplier chain risk score	7%	Flags critical supplier switches, concentration risk, unreliable registry suppliers
News sentiment (30-day)	0%	Narrative risk check — informational only, not scored to avoid noise dominance

Score range: 0-100. Output label: STRONG BUY (80+) / BUY (65-79) / WATCH (45-64) / AVOID (<45).

7.2  Swing / Timing Score
Uses technical signals, options flow, and short-term sentiment. Weights: RSI position 25%, unusual options volume 25%, volume anomaly 20%, insider activity 90-day 15%, news sentiment 7-day 15%.

Output: SETUP PRESENT / MONITOR / NO SIGNAL. Never output a directional call (long or short) from the score alone — the user must confirm with fundamental context before acting.

7.3  Recommendation Engine — Plain English Output
For every company on the watchlist, the engine generates a structured recommendation card. Use Claude Sonnet 4.6 (claude-sonnet-4-6) for full recommendation card generation and agent brain synthesis — quality here directly affects investment decisions. Use Claude Haiku 4.5 (claude-haiku-4-5-20251001) for all high-frequency lower-stakes calls: sector digest one-liners, alert formatting, supplier summaries, congressional trade context paragraphs. Pass all computed metrics as structured JSON in the system prompt and ask the model to write a specific, non-generic rationale. This model routing keeps monthly API costs under $8 for a personal single-watchlist platform.

•	Company name, ticker, current price, fair value range
•	Long-term score (0-100) with label
•	Swing setup score with label
•	One-paragraph plain English rationale (Claude API generated)
•	Thesis break conditions: the specific, concrete events that would cause the user to sell — not price drops, but business events (e.g. 'Assa Abloy loses a major government access contract' or 'Dolby loses Apple Music licensing')
•	Last updated timestamp and data freshness indicator

8. Alerting System
Use APScheduler for scheduled jobs and a Telegram bot for real-time push notifications. The Telegram bot takes under an hour to set up via BotFather and is free. Alerts should be brief — one to two lines maximum — with a link to the full dashboard card for context.

Alert Type	Trigger Condition	Delivery
Form 4 filed	Any C-suite insider files within 2 business days	Telegram + email, immediate
8-K material event	Any 8-K filed for watchlist company	Telegram, immediate
Unusual options volume	At least 2 of 3 sources (Tradier, Barchart, Market Chameleon) flag same ticker on same day	Telegram, during market hours
Price RSI extreme	RSI crosses below 30 or above 70	Telegram, end of day
Earnings approaching	Earnings date within 7 calendar days	Email, once per company
Score change	Long-term score moves by 10+ points in one week	Email, weekly digest
News sentiment drop	7-day rolling sentiment drops below -0.3	Telegram, end of day
Leadership instability flag	2+ C-suite changes in same role within 18 months, OR abrupt/forced departure classification on CEO or CFO	Telegram + email, immediate — one of the highest-priority alerts in the system
Equity acceleration post-departure	Form 4 filed within 30 days of executive departure showing accelerated vesting	Telegram, immediate
Activist joins board	New director appointment cross-matches known activist fund principals	Telegram + email, immediate
Supplier switch detected	New supplier name appears in 10-K risk factors, earnings transcript keyword scan, or ImportYeti manifests	Telegram, same day — with supplier name and source for user to begin reliability research
Supplier reliability risk	A supplier in the registry with a low reliability score is detected as a critical supplier for a watchlist company	Telegram + email, immediate
New court case detected	CourtListener or PACER returns a new case filing for a watchlist company	Telegram + email, same day
PTAB petition filed	New inter partes review petition filed at USPTO against a watchlist company's patent	Telegram, immediate — especially critical for Dolby
Congressional trade — tracked member	New STOCK Act disclosure filed by any of the top 50 tracked members	Telegram within 4 hours of FMP update
Congressional trade — committee correlated	Tracked member trades a sector where they sit on the oversight committee	Telegram immediately with committee name and sector named explicitly
Congressional cluster trade	3+ members of same committee trade same sector within 30 days	Telegram + email immediately — highest priority congressional signal
Weekly sector digest ready	Saturday scan complete across all 11 GICS sectors	Telegram Saturday evening with hidden giants and watchlist suggestions
Agent noise log	Brain ran a cycle but concluded the new info was not material	No alert sent — logged internally only to prevent alert fatigue

9. Dashboard UI — Streamlit Specification
Build a single-page Streamlit dashboard with four tabs. Keep the UI clean — data-forward, no unnecessary decoration. The user is making financial decisions from this screen, not admiring design.

•	Table of all tracked companies with current price, fair value range, long-term score, swing score, last agent brain activity timestamp, last signal, and a color-coded status dot. Clicking a row opens the full recommendation card. Tab 1 — Watchlist Overview:
•	Dropdown to select any watchlist company. Displays: price chart with moving averages, fundamental trend charts (revenue, margins, FCF over 8 quarters), DCF sensitivity table, comps table, insider activity log, recent Form 4 filings, news sentiment timeline, and the full recommendation card with plain-English rationale. Tab 2 — Company Deep Dive:
•	Input any ticker not on the watchlist to run a one-time analysis. Output is the same recommendation card format. This is the entry point for new Lynch-style observations the user wants to quickly validate. Tab 3 — Screening Tool:
•	FRED data visualization: Fed funds rate, CPI, yield curve, PMI. Context panel explaining how current macro environment affects the scoring weights — e.g. high interest rates compress growth stock multiples, which should increase the discount rate in DCF calculations. Tab 4 — Macro Dashboard:
•	Displays the most recent Saturday scan. Shows the state-of-play for all 11 GICS sectors, the top 10 companies per sector with their weekly performance metrics, and the Hidden Giants section prominently at the top — the companies flagged as large but low awareness. Includes a one-click 'Add to Watchlist' button on any discovered company. Historical digests accessible via a date picker. Tab 5 — Weekly Sector Digest:
•	Two sub-views. First: the Top 50 Tracked Members leaderboard showing each member's trade count, total volume, top sector, and committee assignments. Second: a live trade feed showing all recent congressional disclosures with committee correlation flags highlighted in a distinct color. Filter by chamber, party, committee, sector, or date range. Any trade flagged as committee-correlated or cluster is pinned to the top of the feed regardless of date. Tab 6 — Congressional Trading:
•	Reverse-chronological feed of every reasoning cycle the agent brain completed. Each entry shows: which company triggered it, what data changed (the delta), the full synthesis paragraph the brain generated, whether it was flagged as material, and whether an alert was sent. This tab is the transparency layer — the user can always audit what the brain was thinking and why it did or did not alert. Also shows the next scheduled perception cycle for each data source. Tab 5 — Agent Brain Activity Log:

10. PostgreSQL Database Schema
Use SQLAlchemy ORM. Key tables are listed below. Use the existing PostgreSQL instance already set up in the user's environment.

•	companies: ticker, name, sector, exchange, instrument_type (equity/otc_adr/etf/inverse_etf/mutual_fund), active (boolean), paused (boolean), watchlist_added_date, thesis_notes, local_currency (for ADRs), fx_series_id (FRED series for FX rate if ADR)
•	price_history: ticker, date, open, high, low, close, volume, adj_close
•	fundamentals: ticker, period_end, revenue, gross_profit, operating_income, net_income, free_cash_flow, total_debt, ebitda, eps, pe_ratio, dividend_per_share
•	scores: ticker, score_date, lynch_score, swing_score, dcf_fair_value_low, dcf_fair_value_high, comps_target, mean_reversion_target, recommendation_label, rationale_text
•	insider_transactions: ticker, filing_date, insider_name, insider_title, transaction_type, shares, price_per_share, total_value
•	news_sentiment: ticker, article_date, headline, source, sentiment_score, sentiment_label
•	options_signals: ticker, signal_date, contract, source (tradier/barchart/marketchameleon), volume, open_interest, volume_oi_ratio, vs_20day_avg, flagged_unusual, cross_validated (boolean set to true when 2+ sources agree) — store each source result independently for full auditability
•	macro_data: series_id, date, value (generic table for all FRED series)
•	agent_memory: ticker, snapshot_date, lynch_score, swing_score, sentiment_score, insider_net, recommendation_label, thesis_summary — stores the prior state the brain compares against on every cycle
•	court_cases: ticker, case_number, court, filed_date, plaintiff, defendant, case_type, summary, source (pacer or courtlistener), first_detected_at — deduplicated by case_number so each case is only processed once
•	leadership_events: ticker, person_name, role, event_type (appointed/departed/interim), event_date, tenure_days, departure_language, departure_language_classified (planned/abrupt/forced), equity_accelerated (boolean parsed from Form 4 post-departure), source_filing — every C-suite and board change logged with tenure and classified departure language
•	leadership_velocity: ticker, role, change_count_12mo, change_count_24mo, avg_tenure_days, instability_flag (boolean set when 2+ changes in same role within 18 months), last_updated — rolling velocity tracker per role per company
•	supplier_signals: ticker, detected_date, signal_type (new_supplier_named/supplier_removed/supplier_risk_language/customs_import_change), supplier_name, source (10k_risk_factors/earnings_call/8k_material_contract/importyeti), prior_supplier_name, context_text, severity (informational/watch/flag), agent_reviewed
•	supplier_registry: supplier_name, reliability_score (0-100), reliability_notes, financial_health_flag, concentration_risk_flag, last_researched_date — the user-maintained registry of known suppliers across all watchlist companies with reliability assessments

11. Tech Stack and Dependencies
Component	Library / Tool
Dashboard UI	streamlit
Data manipulation	pandas, numpy
Options flow (Layer 1 — free)	Tradier API (developer.tradier.com) — raw options chains; unusual volume computed by Market Lens
Options flow (Layer 2 — free)	Barchart free API (barchart.com/cmdtyview) — structured JSON unusual activity feed, cross-validates Tradier signals
Options flow (Layer 3 — free scrape)	Market Chameleon (marketchameleon.com) — high-quality exchange-sourced unusual activity, scraped via BeautifulSoup
Options flow (paid upgrade — optional)	WhaleStream API — real-time sweep detection; only add if free three-layer stack proves insufficient
SEC EDGAR	requests + custom EDGAR parser (edgar.py)
PDF text extraction	pdfplumber, PyMuPDF (fitz)
OCR fallback	pytesseract, opencv-python
NLP sentiment	transformers (HuggingFace), torch (ProsusAI/finbert)
Macro data	fredapi
Database ORM	sqlalchemy, psycopg2
Scheduling	APScheduler
Alerts	python-telegram-bot, smtplib
Charting	plotly
AI-generated rationale + agent synthesis	anthropic (Claude API, claude-sonnet-4-20250514)
Dynamic watchlist management	watchlist.py — add/remove/pause any ticker at runtime with auto-classification and historical backfill
Windows background service	NSSM (Non-Sucking Service Manager) — free tool to run agent.py as a Windows Service on boot
File paths (cross-platform)	pathlib.Path — all file references use pathlib, never hardcoded backslashes
Timezone handling	pytz — all internal timestamps stored as UTC, converted to ET for display only
Supplier intelligence	suppliers.py: pdfplumber + keyword extractor for 10-K/transcript; ImportYeti scrape via BeautifulSoup; supplier_registry PostgreSQL table
USPTO PTAB patent monitoring	developer.uspto.gov REST API (free)
HTTP requests / scraping	requests, BeautifulSoup4
XML parsing (Form 4)	xml.etree.ElementTree (stdlib)
Environment variables	python-dotenv

12. Recommended Build Order for Cursor
Build in this sequence. Each phase should be independently runnable and testable before moving to the next. Do not skip phases.

•	Set up PostgreSQL schema (models.py) on Windows using pgAdmin. Implement config.py with .env variables. Build watchlist.py with full add/remove/pause/reactivate and instrument type auto-classification. Seed the watchlist with Assa Abloy (ASAZY), Dolby (DLB), Sysco (SYY), and J.B. Hunt (JBHT). Verify all four tickers classify correctly. Set up NSSM on the Windows machine — register a test script as a Windows Service to confirm the process management setup works before agent.py exists. Phase 1 — Foundation:
•	Implement prices.py using yfinance. Pull 5 years of price history and current fundamentals for all watchlist companies. Store in database. Verify data integrity. Phase 2 — Price and Fundamentals Ingestion:
•	Implement edgar.py. Pull last 4 10-Q filings per company using the EDGAR company facts API. Parse Form 4 filings for the last 90 days. Verify insider transaction parsing on a known company. Phase 3 — EDGAR Ingestion:
•	Implement fundamentals.py and valuation.py. Run DCF, comps, and mean reversion models on Dolby first as a test case since we have context on that company. Verify the fair value range is reasonable. Phase 4 — Fundamentals Analysis and Valuation:
•	Implement scoring.py. Compute lynch_score and swing_score for all watchlist companies. Verify weights sum to 100% and scores are in expected ranges. Phase 5 — Scoring Engine:
•	Implement nlp.py. Download FinBERT model locally. Run sentiment on last 30 days of news for each watchlist company. Store in news_sentiment table. Phase 6 — NLP Pipeline:
•	Implement app.py with all four Streamlit tabs. Wire all data from the database. Add Plotly charts for price history and fundamental trends. Phase 7 — Dashboard:
•	Implement watcher.py and notifier.py. Set up Telegram bot. Test Form 4 alert on a recent real filing to verify end-to-end delivery. Phase 8 — Alerts:
•	Implement recommendation/engine.py. Wire Claude API to generate plain-English rationale paragraphs from structured score data. Test on all four seed companies. Phase 9 — Claude API Rationale:
•	Implement ocr.py last since it is only needed for older or scanned filings. Test on one historical 10-K PDF. Add as a fallback in the EDGAR ingestion flow. Phase 10 — OCR Pipeline:
•	Implement agent/memory.py and agent/delta.py. Wire them to read from the existing database. Test the delta detection logic by manually inserting a score change and verifying the system correctly identifies it as a meaningful shift. Phase 11 — Agent Brain Core:
•	Implement agent/synthesizer.py using the Claude API. Write the system prompt carefully — it must include the original thesis text, the prior state snapshot, and the new triggering data. Test the output quality on a real Dolby 8-K filing to verify the reasoning paragraph is specific and not generic. Phase 12 — Agent Synthesizer:
•	Implement court_dockets.py using CourtListener API. Test on Dolby (known active litigation) to verify case detection works. Add PACER fallback. Wire into the agent brain perception loop. Phase 13 — Court Docket Monitor:
•	Wire all agent modules into agent.py with APScheduler. Set the three-times-daily news cadence, 30-minute EDGAR polling, and daily court scan. Run the full loop for 24 hours on the seed watchlist and verify alerts are firing correctly without false positives. Phase 14 — Agent Scheduling and Full Loop:
•	Implement leadership.py. Backfill all 8-K Item 5.02 filings for the last 3 years for all seed watchlist companies. Compute tenure and classify departure language using the three-bucket system (planned, abrupt, forced). Validate by testing against GE's historical 2017-2021 filings — the pattern detection must correctly flag that period as organizational distress, not routine succession. Phase 15 — Leadership Instability Tracker:
•	Implement suppliers.py. Run the 10-K risk factor keyword extraction and earnings transcript supplier phrase scan on all seed companies. Test ImportYeti scraping on Sysco as the most supply-chain-exposed seed company. Initialize the supplier_registry table. Wire both leadership.py and suppliers.py into the agent brain delta detection and scoring engine. Phase 16 — Supplier Intelligence:
•	Add a fifth tab to the Streamlit dashboard: Agent Activity Log. Shows a reverse-chronological feed of every synthesis the brain ran, what triggered it, what it concluded, and whether an alert was sent. Include a dedicated Supplier Registry sub-view where the user can review, edit, and update reliability scores for detected suppliers across all watchlist companies. Phase 17 — Agent Brain Dashboard Tab:
•	Implement sector_scanner.py with APScheduler Saturday 8pm ET job. Build the hidden giant detector using the brand awareness proxy. Implement Claude API weekly digest generation and Telegram delivery. Add Tab 5 (Weekly Sector Digest) to the Streamlit dashboard. Validate by running the first scan manually and confirming all 11 GICS sectors return results, the hidden giant detection flags recognizable examples like Fastenal or Copart, and the digest is generated, stored, and delivered correctly. Phase 18 — Weekly Sector Scanner:
•	Implement congress_tracker.py. Ingest historical disclosures from the FMP free API. Compute the top 50 active traders by frequency and volume. Pull committee assignments from the Congress.gov API. Build and populate the committee_sector_map lookup table with the hardcoded jurisdiction map. Validate the committee-trade correlation logic by testing against known historical examples — members of the House Intelligence Committee trading semiconductor companies before export control announcements in 2022 is a good validation case. Add Tab 6 (Congressional Trading) to the Streamlit dashboard with the trade feed and committee correlation highlighting. Phase 19 — Congressional Trading Tracker:

12B. Pattern Intelligence Architecture — What to Build Now vs Later
Market Lens is designed to recognize patterns without the user having to explicitly define them. This section draws a clear line between what is implemented now using the Claude API as a pattern reasoner (no ML training required), and what should be added later using lightweight classical machine learning once the data infrastructure is mature.

Phase 1 — Claude API as Pattern Reasoner (Build Now)
The most practical and immediately valuable form of pattern recognition in Market Lens does not require training a machine learning model. It requires feeding the Claude API enough structured historical context that it can reason across patterns, not just evaluate individual events. This is the 90-day signal history input described in the agent brain Step 3 above.

•	The 90-day compressed signal history is a structured JSON object appended to every synthesis prompt. It contains: a list of all scored events in the past 90 days for the company (each event has a type, date, severity, and a one-line description), the stock price at 30-day intervals over the same period, and any prior synthesis conclusions the brain reached. This gives the model enough historical context to say 'this is the third insider sale in 90 days while revenue guidance was cut — that is a deteriorating pattern, not an isolated event.'
•	The congressional pattern prompt works the same way. For each of the top 50 tracked members, synthesizer.py maintains a rolling 18-month trade history alongside their committee activity calendar. Every time a new trade is disclosed, the synthesis prompt includes the full trade history and asks: does this member have a demonstrated pattern of trading ahead of specific committee actions? If yes, describe the pattern and name the most recent example. This is the tool that transforms disclosure data from a lagging indicator into a pattern map.
•	Cross-module coincidence detection is implemented in delta.py as explicit rule logic, not ML. Examples of cross-module patterns that delta.py checks on every cycle: unusual options flow AND congressional committee hearing scheduled in same sector within 7 days; insider net buy score turning positive AND Lynch score improving AND news sentiment recovering simultaneously; leadership departure AND revenue miss in the same 30-day window; court case filed AND options put volume spiking AND short interest rising within the same week. When two or more of these coincide, the synthesis prompt is flagged as requiring a deeper cross-signal analysis pass.

Phase 2 — Classical ML Anomaly Detection (Add After 12 Months of Data)
Once Market Lens has accumulated at least 12 months of structured signal data across all watchlist companies and the weekly sector scans, lightweight classical machine learning models can be added to detect patterns that no explicit rule would catch. These are not neural networks. They run comfortably on a home Windows PC. They require no ML expertise to implement correctly with scikit-learn.

•	scikit-learn's IsolationForest identifies data points that are statistically anomalous relative to the full dataset — companies behaving unlike their sector peers, weeks where multiple unrelated signals all move in the same direction, or congressional members whose trading patterns are statistical outliers versus their colleagues. This model has no parameters to tune and requires no labeled training data. It is the right starting point for unsupervised pattern detection. Add this in a new analysis module called anomaly.py after 12 months of sector scan data is accumulated. Isolation Forest for anomaly detection:
•	Compute pairwise correlations between Lynch score changes, sentiment shifts, insider activity, and subsequent price performance across all watchlist companies over rolling 90-day windows. When a correlation that was previously near zero becomes strongly positive or negative — for example, sentiment shifts in a specific sector now predicting price moves 2 weeks later — flag it as an emergent pattern worth monitoring. This is standard pandas/numpy work, not ML, but it produces ML-quality insights from structured data. Rolling correlation matrices:
•	After 12 months of congressional trade data, compute the average return of stocks purchased by each tracked member in the 30, 60, and 90 days following disclosure. Members whose disclosed purchases consistently outperform the sector benchmark are the highest-value tracking targets — their historical alpha suggests genuine informational advantage. Sort the top 50 tracked members by this attribution score quarterly and reprioritize alerts accordingly. Congressional trade return attribution:

What Market Lens does not need — and why
Deep learning, neural networks, large custom-trained models, and real-time inference pipelines are not appropriate for this system at any stage. The signal volume is too low (a few hundred events per day across a 20-50 company watchlist) for deep learning to add value over classical methods. The Claude API already handles the reasoning layer that deep learning is typically applied to. The goal is a transparent, auditable system where every pattern the platform identifies can be explained in plain English — black-box neural networks work against that goal. If a pattern cannot be explained in a sentence, it should not drive an alert.

13. Important Notes for Cursor

This platform is for personal research only, not automated trading. It produces recommendations for the user to evaluate — it does not execute any trades. Never add any trade execution functionality unless explicitly requested.

•	All API keys must be stored in a .env file and loaded via python-dotenv. Never hardcode keys in source files.
•	The EDGAR User-Agent header is required by SEC policy. Set it to a real email address in config.py. Requests without a valid User-Agent will be rate-limited or blocked.
•	FinBERT is a large model (~440MB). Download it once and cache locally. Do not re-download on every run.
•	yfinance data for OTC stocks like ASAZY may be incomplete. Flag data quality issues in the dashboard rather than silently failing.
•	The Claude API call for rationale generation should include the full computed metrics as a structured JSON object in the system prompt so the model has all context to write a specific, non-generic rationale.
•	All scheduled jobs must handle failures gracefully with retry logic and error logging. A failed EDGAR pull should not crash the entire scheduler.
•	For fractional investment context: the platform should never suggest position sizing as a fixed dollar amount. It should express conviction as a score only. The user determines position size based on their own capital constraints.
•	The Claude API has no free tier — all usage is billed per token. However, at current pricing, a personal single-watchlist platform costs $2-8 per month total if model routing is done correctly. The rule is: use Claude Haiku 4.5 for all high-frequency, lower-stakes calls (weekly sector digest one-sentence summaries, congressional trade alert formatting, supplier research summaries, news sentiment context). Use Claude Sonnet 4.6 only for full agent brain synthesis calls — the deep multi-signal reasoning where output quality is directly tied to investment decisions. Never use Opus for any automated call in this platform. This hybrid routing keeps costs minimal while preserving quality where it actually matters. Claude API model routing — use two models, not one:
•	Add scikit-learn's IsolationForest algorithm in a new anomaly.py module. This detects statistically unusual movements in price, volume, and sentiment time-series data that fall outside patterns without requiring you to define explicit thresholds. It requires no labeled training data, no model retraining, and about 20 lines of code. Train it on the historical price and volume data already in the database. This handles the pattern recognition use case that would otherwise require a full ML pipeline. It is the only machine learning component Market Lens needs — everything else is handled by rule-based detection and Claude API reasoning. IsolationForest anomaly detection — the only ML component needed:
•	Test the NSSM Windows Service registration in Phase 1 before any other phase. If the agent brain cannot survive a Windows reboot and restart automatically, the always-on requirement is not met.
•	The dynamic watchlist add flow must handle company name search, not just ticker symbols. Most users think in company names, not tickers. If the user types 'Cintas' the platform must find CTAS, show it for confirmation, and proceed.
•	The Claude API synthesis prompt in synthesizer.py is the most critical prompt in the entire system. It must include: (1) the user's original thesis note for the company in plain English, (2) the prior state snapshot as structured JSON, (3) all new data that triggered the delta, and (4) an explicit instruction to distinguish between noise and material thesis changes. Spend time on this prompt — it determines the quality of every proactive alert.
•	Alert fatigue is a real risk. The brain must have a minimum silence window — do not send more than two Telegram alerts per company per day unless a genuinely critical event occurs such as a new lawsuit, a missed earnings, or a CEO departure. Log everything, but alert sparingly.
•	Market Chameleon is scraped via BeautifulSoup, not an official API. Write the scraper defensively — if the HTML structure changes and parsing fails, log the failure and skip that layer for the cycle rather than crashing. The cross-validation logic requires only 2 of 3 sources to agree, so a failed scrape degrades gracefully to a Tradier + Barchart two-source check.
•	Leadership departure language classification must be conservative — when in doubt, classify as abrupt rather than planned. A false positive on an instability flag that the user reviews and dismisses is far less harmful than a missed forced departure that goes undetected. Cache and never re-classify already-classified departure events.
•	The supplier_registry reliability score is always a human judgment call. The agent brain surfaces the supplier and generates a research summary, but never auto-populates a reliability score from sentiment alone. Supplier reliability involves operational context that cannot be fully assessed from public filings text.
•	ImportYeti scraping runs monthly only. Customs manifest data updates with a lag and daily scraping adds no informational value while unnecessarily increasing request volume to a free service.
•	When the agent brain detects a new supplier in ImportYeti manifests that does not exist in the supplier_registry, it adds it with a reliability_score of NULL and flags it for user review. The dashboard must surface unreviewed supplier entries prominently so the user knows research is needed.

Appendix A — Exact API Endpoints for Every Integration
This appendix gives Cursor the precise endpoints, parameters, headers, and response structures for every API Market Lens calls. Do not guess at endpoint formats — use exactly what is specified here.

A1. SEC EDGAR — No API Key Required
•	Set header: User-Agent: MarketLens your@email.com — replace with your real email. SEC will rate-limit or block requests without this. Rate limit: max 10 requests per second. User-Agent header REQUIRED on every request:
•	GET https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&ticker=DLB&type=&dateb=&owner=include&count=10&search_text=&output=atom — parse the CIK from the response. Alternatively use the company tickers JSON: GET https://www.sec.gov/files/company_tickers.json — returns a full mapping of all tickers to CIK numbers. Cache this file locally and refresh weekly. Get company CIK from ticker:
•	GET https://data.sec.gov/submissions/CIK##########.json — replace ########## with zero-padded 10-digit CIK (e.g. CIK0000320193 for Apple). Returns JSON with filings.recent containing parallel arrays: accessionNumber, filingDate, form, primaryDocument. Filter form array for '10-K', '10-Q', '8-K', '4' to get the filing types Market Lens needs. Get all recent filings for a company:
•	GET https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json — returns all reported financial facts for a company in structured JSON under facts.us-gaap. Key tags: Revenues, NetIncomeLoss, OperatingCashFlow, EarningsPerShareBasic, CommonStockDividendsPaidPerShare, LongTermDebt, GrossProfit. Each tag contains a units object with USD array of {end, val, accn, fy, fp, form, filed} entries. Get structured XBRL financial data:
•	Construct URL as: https://www.sec.gov/Archives/edgar/data/{CIK}/{accessionNumber_no_dashes}/{primaryDocument} — replace accession number dashes with nothing (e.g. 0001193125-23-272336 becomes 0001193125232723360). For Form 4 XML: same pattern — the primaryDocument will end in .xml. Parse with xml.etree.ElementTree. Get a specific filing document:
•	GET https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={CIK}&type=8-K&dateb=&owner=include&count=10&search_text=&output=atom — returns Atom RSS feed of most recent 8-K filings for a company. Poll every 30 minutes. Also available for Form 4: replace type=8-K with type=4. EDGAR RSS feed for real-time filings:

A2. Congress.gov API — Key Required (free)
•	https://api.congress.gov/v3/ — append api_key={CONGRESS_API_KEY} to every request as a query parameter. Default returns JSON. Rate limit: 5000 requests per hour. Base URL:
•	GET https://api.congress.gov/v3/member?currentMember=true&limit=250&api_key={KEY} — returns paginated list. Use offset parameter for pagination (offset=0, offset=250, offset=500 etc). Each member object contains: bioguideId, name, partyName, state, district (House only), terms array. The bioguideId is the unique identifier used in all other member endpoints. Get all current members of Congress:
•	GET https://api.congress.gov/v3/member/{bioguideId}/committee-assignment?api_key={KEY} — returns all committees the member currently serves on. Each entry has: committee.name, committee.chamber, committee.systemCode. Store systemCode as the committee identifier. Get committee assignments for a member:
•	GET https://api.congress.gov/v3/committee-meeting/{congress}/{chamber}?api_key={KEY} — replace {congress} with current congress number (119 for 2025-2026), {chamber} with house or senate. Filter by fromDateTime and toDateTime query params for the coming 30 days. Returns meetings with: title, date, chamber, committees array. Meeting type values: 'Hearing', 'Markup', 'Meeting'. Markups are the highest-value signal for trading correlation. Get upcoming committee hearings:
•	GET https://api.congress.gov/v3/bill/{congress}/{billType}/{billNumber}/actions?api_key={KEY} — returns all actions including floor votes. Use to identify which members voted on legislation affecting tracked sectors. Get votes for a specific bill:

A3. Financial Modeling Prep — Key Required (free tier)
•	https://financialmodelingprep.com/api/ — append apikey={FMP_API_KEY} to every request. Free tier: 250 requests per day. Upgrade available. Base URL:
•	GET https://financialmodelingprep.com/api/v4/senate-disclosure?page=0&apikey={KEY} — returns array of trades. Each object: disclosureDate, transactionDate, senator, ticker, assetName, assetType, type (Purchase/Sale/Exchange), amount (range string like '$1,001 - $15,000'), comment. Paginate with page=1, page=2 etc. Pull new page=0 every 4 hours to catch fresh disclosures. Senate STOCK Act disclosures:
•	GET https://financialmodelingprep.com/api/v4/house-disclosure?page=0&apikey={KEY} — identical structure to Senate endpoint. Representative field instead of senator. House STOCK Act disclosures:
•	GET https://financialmodelingprep.com/api/v4/historical/shares_float?symbol={TICKER}&apikey={KEY} — returns short interest percentage and float shares history. Store in fundamentals table. Display on company card as supplementary context, not scored. Short interest data:
•	GET https://financialmodelingprep.com/api/v3/sector-performance?apikey={KEY} — returns current performance by GICS sector. Use in weekly sector scanner to provide sector-level context alongside company-level data. Sector performance:

A4. FRED API — Key Required (free)
•	https://api.stlouisfed.org/fred/ — append api_key={FRED_API_KEY}&file_type=json to every request. Base URL:
•	GET https://api.stlouisfed.org/fred/series/observations?series_id={SERIES_ID}&api_key={KEY}&file_type=json&sort_order=desc&limit=52 — returns last 52 observations. Key series IDs for Market Lens: FEDFUNDS (Federal Funds Rate), CPIAUCSL (CPI), UNRATE (Unemployment), UMCSENT (Consumer Sentiment), PMI (Manufacturing PMI — use series MANEMP as proxy), T10Y2Y (10Y-2Y yield curve spread — the recession indicator), DFF (daily Fed funds effective rate), DEXUSEU (USD/EUR), DEXUSNZ (USD/SEK does not exist — use ECB for SEK, see below). Get a data series:
•	FRED does not have USD/SEK. Use the ECB Data Portal instead: GET https://data-api.ecb.europa.eu/service/data/EXR/D.SEK.EUR.SP00.A?format=jsondata — returns daily EUR/SEK. Combine with FRED DEXUSEU (USD/EUR) to compute USD/SEK. Store in macro_data table with series_id='USDSEKCALC'. USD/SEK for Assa Abloy:

A5. NewsAPI — Key Required (free tier)
•	https://newsapi.org/v2/ — pass apiKey={NEWSAPI_KEY} as query parameter or Authorization header. Base URL:
•	GET https://newsapi.org/v2/everything?q={COMPANY_NAME}&from={DATE}&sortBy=publishedAt&language=en&pageSize=20&apiKey={KEY} — use company name in quotes for precision (e.g. q=%22Dolby+Laboratories%22). Use from parameter set to yesterday's date. Returns articles array with: title, description, url, publishedAt, source.name. Feed title + description into FinBERT for sentiment scoring. Free tier: 100 requests per day total across all calls — batch all watchlist companies into one daily pull at 9am ET. Search news by company:

A6. Barchart — Key Required (free tier)
•	barchart.com/cmdtyview/cmdty-data/barchart-api — requires account creation at barchart.com to obtain free API key. Free API documentation:
•	GET https://marketdata.thebarchart.com/options/unusual-activity/{TICKER}?apikey={KEY} — returns options contracts flagged as unusual by Barchart's own detection. Use as Layer 2 cross-validation against yfinance-computed Layer 1. If Barchart endpoint format differs from above after account creation, check the Barchart API documentation at barchart.com/cmdtyview for the exact current endpoint path — endpoint paths on this API have changed in past versions. Unusual options activity:

A7. yfinance — No Key, No Account
•	import yfinance as yf — ticker = yf.Ticker('DLB') — options_dates = ticker.options — chain = ticker.option_chain(options_dates[0]) — chain.calls and chain.puts return DataFrames with columns: contractSymbol, strike, lastPrice, bid, ask, change, percentChange, volume, openInterest, impliedVolatility. Compute unusual volume ratio as: volume / openInterest. Flag where ratio > 0.5 AND volume > 3x the 20-day average volume for that contract. Cache raw chain data daily in options_signals table. Options chain:
•	ticker.history(period='5y') for price history. ticker.info for current fundamentals dict — key fields: marketCap, trailingPE, forwardPE, dividendYield, revenueGrowth, grossMargins, freeCashflow, debtToEquity, sector, industry, longName, exchange. ticker.financials for income statement. ticker.quarterly_financials for quarterly breakdown. ticker.balance_sheet and ticker.cashflow also available. Price and fundamentals:
•	For tickers where ticker.info returns empty or None for key fields like marketCap or trailingPE, set data_quality_flag='incomplete' in the companies table and display a warning on the dashboard card. Do not compute scores on incomplete data — show N/A instead. OTC/ADR data quality flag:

A8. CourtListener — No Key Required
•	https://www.courtlistener.com/api/rest/v3/ — no authentication required for basic use. Optional account at courtlistener.com for higher rate limits. Base URL:
•	GET https://www.courtlistener.com/api/rest/v3/dockets/?q={COMPANY_NAME}&order_by=date_filed&format=json — returns paginated docket list. Each docket has: id, case_name, court, date_filed, date_terminated, docket_number, pacer_case_id. Filter for date_filed greater than last_checked timestamp. Store docket_number as the unique deduplication key in court_cases table. Search for cases by company name:
•	GET https://www.courtlistener.com/api/rest/v3/docket-entries/?docket={DOCKET_ID}&format=json — returns filings within a case. Use to check for recent activity on known open cases. Get entries for a specific docket:

A9. Senate LDA Lobbying Database — No Key, Scraped
•	https://lda.senate.gov/api/v1/filings/?filing_type=registration&registrant_name={COMPANY_NAME}&format=json — this is an actual REST API, not just a scrape. Returns JSON of lobbying registrations. Key fields: registrant.name, client.name, filing_date, lobbying_activities array (each has general_issue_code and description). Cross-reference general_issue_code against sector keywords to determine sector relevance. Search URL:

A10. House Clerk and Senate EFTS — No Key, Public Feeds
•	GET https://disclosures.house.gov/FinancialDisclosure/ViewMemberSearchResult — POST request with form data: LastName, FilingYear, State. Returns HTML — scrape with BeautifulSoup to extract disclosure links. However, FMP (A3 above) is the recommended primary ingestion layer — use House Clerk only for verification of specific high-signal trades. House disclosures search:
•	GET https://efts.senate.gov/LATEST/search-index?q={SENATOR_NAME}&dateRange=custom&fromDate={DATE}&toDate={DATE}&results_count=100 — returns JSON search results of Senate financial disclosures. Again, FMP is the primary layer — use Senate EFTS only for cross-validation. Senate EFTS:


Market Lens  |  Personal Investment Research Platform  |  Build v2.0 Agent Edition  |  March 2026
