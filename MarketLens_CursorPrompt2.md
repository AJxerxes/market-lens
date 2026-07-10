MARKET LENS
Complete Build Handoff — Phases 2 through 20
Session State as of March 2026  |  Windows 11 Local Deployment


Current Session State
Hand this document to Cursor at the start of every new session. It contains the complete build sequence from Phase 2 onwards, all stack corrections, all environment details, and the exact instructions for every remaining module. Do not re-upload the full Market Lens specification document — this handoff replaces it for build purposes.

At session start, also paste the latest session summary (the "Market Lens – Session Summary" that Cursor generates at the end of each session). Between this document and that summary, Cursor has full context every time.

Environment — Confirmed Working
Field	Value
Project root	C:\Users\User\.cursor\worktrees\Market_Lens\avi
Python venv	.\venv\Scripts\python.exe
Database	PostgreSQL — market_lens — localhost:5432 — user: postgres / password: postgres
Seed companies	ASAZY, DLB, SYY, JBHT — all loaded with agent_memory snapshots
Phase 1 status	COMPLETE — database created, seed run, watchlist list verified
NSSM	Install from nssm.cc to register agent.py as a Windows Service — not yet done

Windows-Specific Rules — Apply to Every Module
-	ASCII only: Never use Unicode characters in print statements or log output. Use [OK], [ERROR], [SKIP], [WARN] instead of symbols. Windows cp1252 encoding will crash on Unicode arrows, checkmarks, or box characters.
-	Foreign key flush: Whenever inserting a parent row followed immediately by a child row in the same session, call session.flush() after adding the parent before adding the child. Prevents FK violation errors on PostgreSQL.
-	File paths: Use pathlib.Path for every file reference. Never hardcode backslashes. pathlib handles Windows and Linux transparently.
-	Timestamps: Store all timestamps as UTC in PostgreSQL (TIMESTAMP WITH TIME ZONE columns). Convert to Eastern Time for display only, using pytz. Never assume system timezone.

Stack Corrections — Apply Before Writing Any Module
The following APIs have been removed or replaced since the original spec was written. Every module must use the corrected stack below.

Original	Replacement / Status
Tradier API (options Layer 1)	REMOVED — Nigerian F1 visa holders cannot open a brokerage account. Replaced by yfinance ticker.option_chain()
Barchart OnDemand (options Layer 2)	REMOVED — paid enterprise product, requires custom sales contract. Replaced by Unusual Whales public feed scrape
Market Chameleon (options Layer 3)	REMOVED — requires premium account to scrape. Replaced by Nasdaq unusual options page scrape
ImportYeti (supplier customs)	REMOVED — CAPTCHA + email 2FA blocks automation. Replaced by US Census usatrade.census.gov + Panjiva free preview
Seeking Alpha (transcripts)	REMOVED — blocks scraping. Replaced by company IR pages stored in ir_transcript_url field + earningscall.biz fallback
CourtListener v3 API	UPGRADED to v4 — base URL is now courtlistener.com/api/rest/v4/
LDA Senate (lda.senate.gov)	DOMAIN CHANGING — build against lda.gov/api/v1/ from day one. Old domain shuts down June 2026
USPTO developer.uspto.gov	DECOMMISSIONED Jan 6 2026 — new base URL is api.data.gov/USPTO/PTAB/v3/

Corrected Options Flow Stack
-	Layer 1 — yfinance (primary): ticker.option_chain(expiry_date) returns calls and puts DataFrames with volume, openInterest, impliedVolatility, strike. Compute unusual volume: flag contracts where (volume / openInterest) > 0.5 AND volume > 3x the 20-day rolling average for that contract. Run every 15 minutes during market hours.
-	Layer 2 — Unusual Whales public feed: Scrape https://unusualwhales.com/flow with BeautifulSoup. No account required for public page. Parse the flow table for ticker, contract type, strike, expiry, volume, premium. Run every 30 minutes during market hours. Degrade gracefully if blocked.
-	Layer 3 — Nasdaq unusual options: Scrape https://www.nasdaq.com/market-activity/options with BeautifulSoup. Find the options activity table, extract ticker, volume, open interest. No account required.
-	Cross-validation rule: Fire a swing alert only when at least 2 of 3 sources flag the same ticker on the same day. Store each source result independently in options_signals table. Set cross_validated = true only when 2+ sources agree.

.env File — Complete Key Reference
All keys are already set in the .env file. This section documents what each key is used for so every module knows which variable to load.

Variable	Used In
ANTHROPIC_API_KEY	agent/synthesizer.py, recommendation/engine.py, sector_scanner.py — Claude Sonnet for synthesis, Claude Haiku for fast calls
CLAUDE_SYNTHESIS_MODEL=claude-sonnet-4-6	All deep reasoning synthesis calls in synthesizer.py
CLAUDE_FAST_MODEL=claude-haiku-4-5-20251001	Sector digest summaries, alert formatting, congressional trade context
FRED_API_KEY	ingestion/macro.py — rates, CPI, yield curve, USD/EUR for ADR FX
NEWSAPI_KEY	ingestion/news.py — headlines 3x daily for FinBERT sentiment
ALPHA_VANTAGE_API_KEY	ingestion/edgar.py fallback, earnings calendar supplement
CONGRESS_API_KEY	ingestion/congress_tracker.py — member list, committee assignments, hearing schedule
USPTO_API_KEY	ingestion/court_dockets.py PTAB section — IPR petition monitoring
COURTLISTENER_TOKEN	ingestion/court_dockets.py — Authorization: Token header on every request
FMP_API_KEY	ingestion/congress_tracker.py (primary trade feed), ingestion/tracked_funds.py (13F), analysis/fundamentals.py (ratios, peers)
TELEGRAM_BOT_TOKEN	alerts/notifier.py — all Telegram push alerts
TELEGRAM_CHAT_ID	alerts/notifier.py — the user's personal chat ID for delivery
SMTP_HOST=smtp.aol.com	alerts/notifier.py — email alerts via AOL SMTP
SMTP_PORT=587	alerts/notifier.py — TLS port
SMTP_USER=omniaj@aol.com	alerts/notifier.py — sender address
SMTP_PASSWORD	alerts/notifier.py — AOL app password (not main account password)
ALERT_EMAIL_TO	alerts/notifier.py — recipient address for email alerts
EDGAR_USER_AGENT=MarketLens omniaj@aol.com	ingestion/edgar.py — required header on every SEC EDGAR request
DATABASE_URL	All modules via config.py — postgresql://postgres:postgres@localhost:5432/market_lens

Build Sequence — Phases 2 through 20
Phase 1 is complete. Execute phases in order. Do not start the next phase until the current phase passes its validation checkpoint. Each phase has a specific test that must pass before moving on.

Phase 2	Price and Fundamentals Ingestion	NEXT

What to build
-	File: ingestion/prices.py
-	Purpose: Pull 5 years of price history and current fundamentals for every active company in the watchlist using yfinance.

Exact implementation
-	Price history: yf.Ticker(ticker).history(period='5y') — store all rows in price_history table: ticker, date, open, high, low, close, volume. Use upsert on (ticker, date) so re-runs do not duplicate rows.
-	Current fundamentals: yf.Ticker(ticker).info — extract and store in fundamentals table: market_cap, trailing_pe, forward_pe, dividend_yield, revenue_growth, gross_margins, operating_margins, free_cashflow, debt_to_equity, beta, sector, industry, long_name, exchange. If any field returns None, store NULL and set data_quality_flag='incomplete' on the companies row.
-	Quarterly financials: yf.Ticker(ticker).quarterly_financials — store last 8 quarters of revenue, gross_profit, operating_income, net_income in fundamentals table with period_end date column.
-	OTC handling: ASAZY will return incomplete data. When market_cap or trailing_pe is None, log [WARN] ASAZY: incomplete data, set flag, and continue. Never error out on missing fields.
-	Instrument type gating: ETFs and mutual funds skip the quarterly financials pull. Only run full fundamentals on instrument_type = 'equity' or 'otc_adr'.

Validation checkpoint
Run prices.py manually on all 4 seed tickers. Open pgAdmin and confirm: price_history has rows for ASAZY, DLB, SYY, JBHT. Fundamentals table has at least market_cap populated for DLB, SYY, JBHT. ASAZY shows data_quality_flag = 'incomplete' if yfinance returns None for key fields. Do not start Phase 3 until all 4 tickers have price history rows in the database.

After Phase 2 passes validation, add a temporary verify.py script: a minimal Streamlit page showing a table of all companies with current price, market cap, and data quality flag, plus a raw Plotly price chart per ticker. Run with: streamlit run verify.py. This is a diagnostic tool only — delete it when app.py is built in Phase 7.

Phase 3	EDGAR Ingestion	PENDING

What to build
-	File: ingestion/edgar.py
-	Purpose: Pull SEC filings for all watchlist equity companies — 10-Q, 10-K, 8-K, Form 4, DEF 14A.

Exact implementation
-	Session setup: Create a requests.Session() object. Set header: {'User-Agent': 'MarketLens omniaj@aol.com'} on the session. Every EDGAR request inherits this header automatically. Rate limit: max 10 requests per second — add a 0.1 second sleep between requests.
-	Step 1 — CIK lookup: GET https://www.sec.gov/files/company_tickers.json — download once, cache in database as ticker_cik_map table: ticker, cik (zero-padded 10-digit string), company_name. Refresh weekly. This is the only correct way to resolve ticker to CIK.
-	Step 2 — Filing list: GET https://data.sec.gov/submissions/CIK{10-digit-cik}.json — returns recent filings in parallel arrays: accessionNumber, filingDate, form, primaryDocument. Filter form array for '10-K', '10-Q', '8-K', '4', 'DEF 14A'. If company has more than 1000 filings, the response includes a files array pointing to older filing batches — follow these for full backfill.
-	Step 3 — Financial data: GET https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json — returns all XBRL facts. Navigate to facts.us-gaap.{TagName}.units.USD array for each metric. Key tags: Revenues, NetIncomeLoss, GrossProfit, OperatingIncomeLoss, EarningsPerShareBasic, CommonStockDividendsPaidPerShare, LongTermDebt, NetCashProvidedByUsedInOperatingActivities. Each array entry has: end (period end date), val, accn, fy, fp (Q1/Q2/Q3/FY), form, filed. Store in edgar_facts table with (ticker, tag, period_end) as unique key.
-	Step 4 — Form 4 parsing: Form 4 filings are structured XML. Download the primaryDocument for each Form 4 accession. Parse with xml.etree.ElementTree. Key fields: periodOfReport, reportingOwner/reportingOwnerId/rptOwnerName, nonDerivativeTable/nonDerivativeTransaction/transactionAmounts/transactionShares, transactionPricePerShare, transactionAcquiredDisposedCode (A=acquired, D=disposed). Store in insider_transactions table.
-	Step 5 — RSS polling for real-time: GET https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count=10&search_text=&output=atom — poll every 30 minutes using feedparser library. Compare feed updated timestamp against last_checked in database. Process only entries newer than last_checked.
-	Bulk ZIP for initial backfill: For the first run, download https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip — extract only the CIK JSON files for watchlist companies. Do not load the entire ZIP into memory. Switch to individual API calls for ongoing monitoring after backfill completes.

Validation checkpoint
After running edgar.py on all 4 seed companies: confirm edgar_facts table has Revenues and NetIncomeLoss rows for DLB and SYY. Confirm at least one Form 4 exists in insider_transactions for any seed company in the past 90 days. Confirm the RSS poll runs without errors and last_checked is updated after each cycle.

Phase 4	Fundamentals Analysis and Valuation	PENDING

What to build
-	Files: analysis/fundamentals.py and analysis/valuation.py

Exact implementation — fundamentals.py
-	Revenue CAGR: Compute 1Y, 3Y, and 5Y revenue CAGR from edgar_facts Revenues array. Formula: (end_value / start_value) ^ (1 / years) - 1.
-	Gross margin trend: Gross margin = GrossProfit / Revenues per quarter. Store last 8 quarters and compute trend direction (improving/flat/deteriorating).
-	FCF yield: Free cash flow = NetCashProvidedByUsedInOperatingActivities minus capital expenditures (from NetCashProvidedByUsedInInvestingActivities — use the capex line item if available, otherwise use the full investing cash flow as a proxy). FCF yield = FCF / market_cap.
-	Debt/EBITDA: LongTermDebt / (OperatingIncomeLoss + depreciation proxy). Store in fundamentals table.
-	Dividend streak: Count consecutive years of dividend increases from CommonStockDividendsPaidPerShare history. Store as dividend_streak_years.

Exact implementation — valuation.py — three methods, one range
-	Method 1 — DCF: Use trailing 12-month FCF as base. Apply 3 growth rate scenarios (bear: -2%, base: consensus or revenue CAGR, bull: +2%). Discount rate = risk-free rate (10Y Treasury from FRED T10Y2Y) + equity risk premium (5.5% default). Terminal value at year 10 using Gordon Growth Model. Output: bear/base/bull fair value per share. Store all three in scores table.
-	Method 2 — Comps: Pull sector peer P/E and EV/EBITDA medians from FMP: GET https://financialmodelingprep.com/api/v4/sector_price_earning_ratio?date={TODAY}&exchange=NYSE&apikey={KEY}. Apply sector median P/E to company EPS. Apply sector median EV/EBITDA to company EBITDA. Average the two outputs for the comps fair value.
-	Method 3 — Mean reversion: Pull company's own 5-year average P/E from trailing_pe history in fundamentals table. Apply to current EPS. This is the Dolby signal — when current P/E is significantly below 5-year average, mean reversion suggests upside.
-	Fair value range: Output is not a single price target. Output is: low (most conservative of three methods), mid (average), high (most optimistic). Display as a range on the dashboard card.

Validation checkpoint
Run both modules on DLB first. Verify: revenue CAGR is computed and not NaN. DCF outputs three distinct fair values (bear < base < bull). Comps method returns a value. Mean reversion fair value is higher than current price (consistent with DLB being below its 5Y average P/E as of March 2026). Fair value range displays as three numbers.

Phase 5	Scoring Engine	PENDING

What to build
-	File: analysis/scoring.py

Lynch Score weights — must sum to 100%
Signal	Weight
Revenue growth (3Y CAGR)	18%
FCF yield vs sector	13%
P/E vs own 5Y average	13%
Insider net buy score	13%
Gross margin trend	10%
Dividend growth streak	8%
Debt / EBITDA	8%
Leadership stability score	10%
Supplier chain risk score	7%
News sentiment	0% (displayed, not scored)

-	Output labels: STRONG BUY (80-100), BUY (65-79), WATCH (45-64), AVOID (below 45).
-	Swing Score weights: RSI 25%, unusual options cross-validated 25%, volume anomaly 20%, insider 90-day activity 15%, news 7-day sentiment 15%. Output: SETUP PRESENT / MONITOR / NO SIGNAL.
-	Score override table: Build a score_override table with columns: ticker, field_name, override_value, locked (boolean), override_reason, created_at. When locked = true, scoring.py uses the manual override value instead of the computed value. Dashboard shows a visible [OVERRIDE] indicator on any locked field.

Validation checkpoint
Run scoring.py on all 4 seed companies. Verify all Lynch scores are between 0 and 100. Verify weights sum to exactly 100%. Verify ASAZY and DLB produce different scores (not identical default values). Confirm score_override table exists and the locked field works correctly by manually setting one field and re-running.

Phase 6	NLP Pipeline	PENDING

What to build
-	File: processing/nlp.py

Exact implementation
-	FinBERT setup: from transformers import pipeline — sentiment_pipeline = pipeline('sentiment-analysis', model='ProsusAI/finbert') — download once, cache locally in a models/ directory in the project root. Model is approximately 440MB. Never re-download on every run — check if the model directory exists before downloading.
-	News sentiment: For each company, pull the last 30 days of news from NewsAPI: GET https://newsapi.org/v2/everything?q={COMPANY_NAME}&from={DATE}&sortBy=publishedAt&language=en&pageSize=20&apiKey={KEY}. Feed each article's title + description through FinBERT. Store result in news_sentiment table: ticker, article_date, source, headline, sentiment_label (positive/negative/neutral), sentiment_score (-1 to 1). Free tier is 100 requests per day total — batch all companies in one daily pull at 9am ET, not per-company calls throughout the day.
-	10-K Risk Factor delta: For each new 10-K filing detected in edgar.py, extract the Risk Factors section text. Compare against prior year Risk Factors using cosine similarity (from sklearn.metrics.pairwise import cosine_similarity with TF-IDF vectors). A cosine similarity below 0.85 means meaningful change — flag for agent brain review. Store both the current and prior risk factor text in a risk_factor_delta table.
-	Supplier keyword scan: Run a separate keyword extraction pass on every earnings transcript (from IR pages or earningscall.biz). Search for: 'transitioning our supply base', 'qualifying a new supplier', 'dual sourcing', 'single source', 'supply chain diversification', 'moving away from', 'new manufacturing partner'. When found, store the context sentence in supplier_signals table.

Validation checkpoint
Download FinBERT and confirm the models/ directory is populated. Run sentiment on 5 DLB news articles and verify the output is positive/negative/neutral with a score, not an error. Run the 10-K risk factor delta on DLB's last two annual filings and confirm a similarity score is produced.

Phase 7	Streamlit Dashboard — First GUI	PENDING

What to build
-	File: app.py
-	Run command: streamlit run app.py — opens at localhost:8501 in the browser

Tab structure — build all tabs in Phase 7, populate with real data as later phases complete
-	Tab 1 — Watchlist Overview: Table of all active companies: ticker, name, current price, fair value range (low-mid-high), Lynch score with label, swing score label, data quality flag, last agent brain activity timestamp. Color-code Lynch score: green for BUY/STRONG BUY, yellow for WATCH, red for AVOID. Clicking a row navigates to Tab 2 filtered to that company.
-	Tab 2 — Company Deep Dive: Dropdown to select any watchlist company. Show: Plotly price chart with 50MA and 200MA overlaid, fundamental trend charts (revenue, gross margin, FCF over 8 quarters), DCF sensitivity table (bear/base/bull), comps table with peer P/E median, insider activity log (last 10 Form 4 filings), news sentiment timeline (30-day rolling chart), full recommendation card with Lynch score breakdown and Claude-generated rationale paragraph. Show [INCOMPLETE DATA] banner for OTC tickers with missing fields.
-	Tab 3 — Screening Tool: Single text input: enter any ticker or company name. On submit, run the full analysis pipeline on demand and display the same recommendation card format as Tab 2. This is the entry point for new Lynch observations. Add a 'Add to Watchlist' button on the output card.
-	Tab 4 — Macro Dashboard: FRED data charts: Fed funds rate (FEDFUNDS), CPI year-over-year (CPIAUCSL), yield curve spread 10Y-2Y (T10Y2Y — negative = inversion = recession signal), consumer sentiment (UMCSENT). Add a context panel: one sentence from Claude Haiku explaining how the current macro reading affects the scoring environment.
-	Tab 5 — Weekly Sector Digest: Placeholder in Phase 7 — populated in Phase 18. Show 'Sector scan runs every Saturday — check back after first Saturday run.'
-	Tab 6 — Congressional Trading: Placeholder in Phase 7 — populated in Phase 19.
-	Tab 7 — Tracked Funds: Placeholder in Phase 7 — populated in Phase 20.
-	Tab 8 — Agent Activity Log: Placeholder in Phase 7 — populated in Phase 17.

Validation checkpoint
Run streamlit run app.py and confirm the browser opens at localhost:8501. All 8 tabs must be visible and clickable. Tab 1 must show all 4 seed companies. Tab 2 must show a price chart for DLB. Tabs 5-8 show placeholder messages. No Python errors in the terminal during normal navigation.

Phase 8	Alerts — Telegram and Email	PENDING

What to build
-	Files: alerts/watcher.py and alerts/notifier.py

Telegram setup
-	Bot: t.me/M_lens_bot — token stored as TELEGRAM_BOT_TOKEN in .env
-	Send a message: import telegram — bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN) — await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message) — use python-telegram-bot library.
-	Message format: Keep all Telegram alerts to 3 lines maximum. Line 1: alert type and ticker in caps. Line 2: the specific signal that fired. Line 3: link to dashboard card (DASHBOARD_BASE_URL from .env + /company/ + ticker).

Email setup — AOL SMTP
-	Settings: Host: smtp.aol.com, Port: 587, TLS: starttls(). User: omniaj@aol.com. Password: SMTP_PASSWORD from .env (this is the AOL app password, not the main account password).
-	Implementation: Use Python stdlib smtplib — no extra library. server = smtplib.SMTP('smtp.aol.com', 587) — server.starttls() — server.login(SMTP_USER, SMTP_PASSWORD) — server.sendmail(from, to, message).

Alert types and delivery channels
Alert Type	Channel
Form 4 filed (C-suite insider)	Telegram + email, immediate
8-K material event	Telegram, immediate
Unusual options cross-validated	Telegram, during market hours only
RSI extreme (<30 or >70)	Telegram, end of day
Earnings approaching (7 days)	Email only
Lynch score change >10 points	Email, weekly digest
News sentiment drop below -0.3	Telegram, end of day
Leadership instability flag	Telegram + email, immediate
Equity acceleration post-departure	Telegram, immediate
Activist joins board	Telegram + email, immediate
Supplier switch detected	Telegram, same day
New court case detected	Telegram + email, same day
PTAB petition filed	Telegram, immediate — bypasses daily cap for Dolby
Congressional trade — tracked member	Telegram within 4 hours of FMP update
Congressional trade — committee correlated	Telegram immediately, names committee and sector explicitly
Congressional cluster trade	Telegram + email immediately — highest priority
Weekly sector digest ready	Telegram Saturday evening
Tracked fund position change >$50M	Telegram immediately with synthesis paragraph
Fund convergence signal	Telegram + email immediately
Agent noise log	No alert — logged internally only

-	Daily cap: Maximum 2 Telegram alerts per company per day. Exceptions that bypass the cap: new lawsuit filed, PTAB institution decision, CEO or CFO departure, missed earnings, congressional cluster trade. Log all suppressed alerts to alerts_log with suppressed=true.

Validation checkpoint
Send a test Telegram message to TELEGRAM_CHAT_ID and confirm it arrives at t.me/M_lens_bot. Send a test email to ALERT_EMAIL_TO via AOL SMTP and confirm delivery. Both must work before wiring any real alert triggers.

Phase 9	Claude API Rationale Generation	PENDING

What to build
-	File: recommendation/engine.py

Model routing — critical for cost control
-	Claude Sonnet (claude-sonnet-4-6): Use for full recommendation card rationale generation and all agent brain synthesis calls. These are the high-stakes outputs where quality matters.
-	Claude Haiku (claude-haiku-4-5-20251001): Use for all high-frequency lower-stakes calls: sector digest one-line summaries, congressional trade alert formatting, supplier research summaries, macro context one-liners on Tab 4.
-	Never use Opus: Too expensive for any automated call in this platform.

Recommendation card generation prompt structure
Pass all computed metrics as a structured JSON object in the system prompt. The user message should be a one-line instruction only. Never put the metrics in the user message — put them in the system prompt so the model has full context before it generates.
system: You are a research analyst for a personal investment platform. The user follows a Peter Lynch observation-based investment philosophy. Given the following metrics for {COMPANY_NAME} ({TICKER}), write a 2-3 sentence rationale explaining the recommendation in plain English. Be specific — reference actual numbers. Do not be generic. Thesis note from the user: {thesis_notes}. Metrics: {json.dumps(metrics_dict)}
user: Generate the recommendation rationale.
-	Synthesis prompt must be dynamically generated: The weights and signals in the system prompt must come from the actual current config values, not hardcoded text. If weights change in config.py, the prompt updates automatically.

Validation checkpoint
Run engine.py on DLB. The output rationale must reference Dolby specifically — mention licensing, P/E vs historical average, or a specific metric. If the output says 'this company shows strong fundamentals' with no specific numbers, the prompt needs more structure. Re-run on all 4 seed companies and confirm each rationale is distinct and ticker-specific.

Phase 10	OCR Pipeline	PENDING

What to build
-	File: processing/ocr.py
-	Purpose: Fallback for older or scanned SEC filings that do not have embedded text layers. Most modern filings do not need this — it is a last resort.

Four-step pipeline
-	Step 1 — EDGAR structured JSON: Always try the EDGAR XBRL companyfacts API first. If it returns the needed data, skip all OCR steps entirely.
-	Step 2 — pdfplumber: If the filing is a PDF with an embedded text layer, extract with pdfplumber. Handles most modern 10-K and 10-Q PDFs cleanly. import pdfplumber — with pdfplumber.open(pdf_path) as pdf: text = ''.join([page.extract_text() for page in pdf.pages])
-	Step 3 — Tesseract OCR: Fallback for scanned PDFs. Preprocess with OpenCV: convert to grayscale, apply threshold, deskew. Then: pytesseract.image_to_string(preprocessed_image). Accuracy approximately 92-95% on clean scans.
-	Step 4 — AWS Textract or Google Document AI (paid, on-demand only): Only invoke manually for financial tables in scanned documents where Tesseract fails on critical data. Never run in automated batch jobs.
-	Form 4 XML: Form 4 filings are structured XML — never use OCR on them. Parse directly with xml.etree.ElementTree.

Validation checkpoint
Test ocr.py on one historical Dolby 10-K PDF from EDGAR. Confirm pdfplumber extracts readable text. Confirm the EDGAR JSON step correctly skips OCR when structured data is available. This phase is complete when ocr.py is wired as a fallback in edgar.py and the four-step cascade works end to end.

Phase 11	Agent Brain Core — Memory and Delta	PENDING

What to build
-	Files: agent/memory.py and agent/delta.py

memory.py — state snapshot system
-	Purpose: Store a compressed snapshot of the current state of all signals for each watchlist company. The snapshot is what the agent compares new data against to detect changes.
-	Snapshot structure: For each company store a JSON object in the agent_memory table: lynch_score, swing_score, last_sentiment_score, last_insider_net_buy_score, last_court_case_count, last_form4_date, last_8k_date, last_leadership_event, price_7d_ago, signal_history_90d (compressed array of last 90 days of events). Update the snapshot after every synthesis cycle.
-	90-day signal history: This is the most important context input for the agent brain. Every time a notable event fires (sentiment drop, insider buy, court case, options spike, leadership change), append a compact entry to signal_history_90d: {date, type, description, severity}. Cap the array at 90 entries. This history is passed to every synthesis call so the model can reason across patterns, not just isolated events.

delta.py — change detection
-	Purpose: Compare current signal values against the stored snapshot and identify what has meaningfully changed since the last synthesis cycle.
-	Delta triggers to check on every cycle: News sentiment shifted by more than 0.15 since yesterday. New court case opened. New 8-K filed since last cycle. Insider net buy score flipped positive to negative or negative to positive. Lynch score moved 5 or more points. New Form 4 filed by C-suite insider. Options cross-validated signal fired. RSI crossed 30 or 70. Leadership event detected. Supplier switch keyword found in new filing.
-	Cross-module coincidence detection: delta.py also checks for combinations that are more significant than individual signals: unusual options AND congressional committee hearing in same sector within 7 days; insider net buy turning positive AND Lynch score improving AND sentiment recovering simultaneously; leadership departure AND revenue miss in same 30-day window; court case filed AND put volume spiking AND short interest rising within same week. When two or more coincide, flag the synthesis call as requiring a deep cross-signal analysis pass.

Validation checkpoint
Manually insert a score change for DLB in the database (change lynch_score by 10 points). Run delta.py and confirm it detects the change and returns a delta object with the changed field identified. Run it again without changes and confirm it returns an empty delta (no false positives).

Phase 12	Agent Synthesizer	PENDING

What to build
-	File: agent/synthesizer.py

This is the most critical prompt in the entire system
The synthesis prompt must include four things simultaneously: (1) the user's original thesis note for why they are watching this company, (2) the prior state snapshot from agent_memory, (3) the new triggering delta data from delta.py, (4) an explicit instruction to distinguish between noise and material changes. If any of these four are missing, the output will be generic and useless.

system: You are the reasoning engine for a personal investment research platform. The user follows a Peter Lynch observation-based philosophy.

ORIGINAL THESIS: {company.thesis_notes}
PRIOR STATE (last synthesis): {json.dumps(prior_snapshot)}
NEW TRIGGERING DATA: {json.dumps(delta_data)}
90-DAY SIGNAL HISTORY: {json.dumps(signal_history_90d)}
CURRENT MACRO ENVIRONMENT: {macro_summary}

Determine: is this new data MATERIAL to the investment thesis, or is it NOISE?
Material = directly affects the thesis reason for holding or avoiding this company.
Noise = routine market movement, minor news, immaterial filing.

If MATERIAL: write 2-3 sentences explaining exactly what changed and why it matters
to the thesis. Reference specific numbers. Do not be generic.
If NOISE: respond with exactly the string 'NOISE' and nothing else.

-	Noise handling: If the model returns 'NOISE', log the cycle to agent_synthesis_log with was_material=false and send no alert. Never send a Telegram message for a NOISE conclusion.
-	Alert fatigue rule: Maximum 2 Telegram alerts per company per day. Exceptions that bypass the cap are hardcoded in notifier.py: new lawsuit, PTAB institution decision, CEO or CFO departure, congressional cluster trade.

Validation checkpoint
Run synthesizer.py on a real Dolby 8-K filing from EDGAR. The output must mention Dolby by name, reference the specific 8-K content, and relate it to the thesis (licensing revenue, Atmos adoption, or patent enforcement). A generic output like 'this filing may affect the company's financial position' means the prompt needs more structure. Do not proceed to Phase 13 until the synthesis output is specific and thesis-grounded.

Phase 13	Court Docket Monitor	PENDING

What to build
-	File: ingestion/court_dockets.py

CourtListener REST API v4 — confirmed endpoints
-	Authentication: Every request must include header: Authorization: Token 1321846b5fd52166a6f0633fac895cbf078fd0cf — set on a requests.Session() object so all calls inherit it.
-	Search dockets by company: GET https://www.courtlistener.com/api/rest/v4/dockets/?q={COMPANY_NAME}&order_by=date_filed&format=json — filter for date_filed greater than last_checked. Store docket_number as unique deduplication key in court_cases table.
-	Get entries for a known docket: GET https://www.courtlistener.com/api/rest/v4/docket-entries/?docket={DOCKET_ID}&format=json — check for new entries on known open cases weekly.
-	PTAB via USPTO ODP — new endpoints: Base URL: https://api.data.gov/USPTO/PTAB/v3/ — append api_key={USPTO_API_KEY}. Search by patent owner: POST /trials/search with body {patentOwnerName: COMPANY, trialType: IPR, dateRangeField: filingDate, startDate: LAST_CHECKED}. Get trial documents: GET /trials/{trialNumber}/documents. Full text decision search: POST /decisions/search with body {searchText: COMPANY_NAME, dateRangeField: decisionDate, startDate: DATE}. Run daily for Dolby specifically.
-	PACER hard rule: CourtListener runs on every cycle. PACER is never called on a schedule. PACER is only called when a specific case_number is known AND CourtListener does not have the full docket text for that case. Set pacer_needed = true in the court_cases table manually. Never set it automatically.
-	Priority cases for Dolby: A PTAB institution decision (PTAB decides the challenge has merit) bypasses all daily alert caps and fires immediately as a Telegram + email alert. This is the highest-severity IP event possible for a licensing-dependent company.

Phase 14	Agent Scheduling and Full Loop	PENDING

What to build
-	File: agent.py (main entry point for the agent brain as a Windows Service)

APScheduler job schedule
Job	Schedule
News pull + sentiment	3x daily: 9am, 12pm, 5pm ET
EDGAR RSS poll (8-K and Form 4)	Every 30 minutes during market hours (9:30am - 4pm ET weekdays)
Options flow check (yfinance + Unusual Whales + Nasdaq)	Every 15 minutes during market hours
FRED macro data refresh	Weekly, Sunday 6am ET
Court docket scan (CourtListener)	Daily, 8am ET
PTAB scan (USPTO ODP)	Daily, 8am ET
Agent brain perception + synthesis cycle	Every 30 minutes — triggered after each ingestion job completes
Sector scanner	Weekly, Saturday 8pm ET
Congressional trade poll (FMP)	Every 4 hours
Lobbying registration scan (lda.gov)	Weekly, Monday 9am ET
13F quarterly pull (tracked funds)	Feb 14, May 15, Aug 14, Nov 14 annually
ARK daily trades scrape	Daily, 6pm ET
Leadership backfill scan	Daily, 7am ET
ImportYeti / Census customs data	Monthly, first Saturday of month

-	Timezone handling: All APScheduler jobs use UTC internally. Convert to ET only for display. Use pytz for all conversions. Never use local system timezone.
-	Holiday handling: Market hours jobs (options, EDGAR RSS) must check if today is a US market holiday before running. Maintain a list of NYSE holidays in config.py and skip market-hours jobs on those days.
-	Failure handling: Every job must have a try/except wrapper. Failures log to loguru with [ERROR] prefix and retry once after 5 minutes. After 3 consecutive failures on the same job, send a Telegram alert: [SYSTEM] {job_name} has failed 3 consecutive times.
-	NSSM registration: After agent.py is confirmed working, register it as a Windows Service: nssm install MarketLensAgent {full_path_to_venv_python} {full_path_to_agent.py}. Set startup type to Automatic. Test by rebooting the machine and confirming the agent brain resumes without manual intervention.

Validation checkpoint
Run the full agent loop for 24 hours on the 4 seed companies. At the end of 24 hours verify: at least 3 news cycles completed, EDGAR RSS polled at least 16 times, options flow checked at least 26 times during market hours, at least one synthesis cycle ran for each company, no unhandled exceptions in the logs, no false positive alerts fired. Register with NSSM and reboot — confirm the agent resumes automatically.

Phase 15	Leadership Instability Tracker	PENDING

What to build
-	File: ingestion/leadership.py

Exact implementation
-	8-K Item 5.02 filter: In edgar.py's filing list, filter for 8-K filings where the items array contains '5.02'. These are director and officer change disclosures. Parse the primaryDocument HTML for: departure reason language, effective date, officer name and title.
-	Tenure calculation: For each detected departure, find the prior appointment filing for the same role using the leadership_events table history. Tenure = departure_date minus appointment_date in days.
-	Departure language classification — three buckets: PLANNED: contains words 'retirement', 'retire', 'planned transition', 'effective [date 60+ days away]', 'succession'. ABRUPT: contains 'effective immediately', 'effective [date within 7 days]', no reason stated, tenure under 18 months. FORCED: activist investor visible in prior proxy DEF 14A, board-initiated language, or equity vesting accelerated in a Form 4 filed within 30 days of departure.
-	Instability flag trigger: Set instability_flag = true in leadership_velocity table when: 2 or more changes in the same C-suite role within 18 months, OR any CEO or CFO departure classified as ABRUPT or FORCED.
-	Equity acceleration check: After any C-suite departure, watch for Form 4 filings from that person in the following 30 days. If shares listed as A (acquired) with a transaction type of vesting acceleration or similar, set equity_accelerated = true on the leadership_events row.
-	Board composition — activist detection: On each new DEF 14A proxy filing, extract new director names. Cross-reference against a hardcoded list of known activist fund principals in config.py (Starboard Value, Elliott, Carl Icahn, ValueAct, etc). If a match is found, fire an immediate Telegram + email alert.

Validation checkpoint
Backfill GE's 8-K Item 5.02 filings from 2017 to 2021. Run the instability detection. It MUST flag the 2017-2021 period as organizational distress, not routine succession. If it does not, the departure language classification thresholds need adjustment before proceeding. This is the acceptance test for the entire leadership module.

Phase 16	Supplier Intelligence	PENDING

What to build
-	File: ingestion/suppliers.py

Four detection layers
-	Layer 1 — 10-K Risk Factors delta: Already computed in nlp.py cosine similarity. suppliers.py goes deeper: extract named supplier entities from the Risk Factors text using basic NLP entity extraction (look for capitalized company names appearing near words like 'supplier', 'vendor', 'manufacturer', 'source'). Track which supplier names appear, disappear, or change in concentration language year over year.
-	Layer 2 — Earnings transcript keyword scan: Already wired in nlp.py. Phrases to detect: 'transitioning our supply base', 'qualifying a new supplier', 'dual sourcing', 'single source', 'supply chain diversification', 'moving away from', 'new manufacturing partner', 'strategic sourcing partner'. Store context sentence in supplier_signals.
-	Layer 3 — 8-K material contracts: Filter 8-K full text for contract-related language involving supply, manufacturing, sourcing, or procurement terms. Large supplier agreements may trigger an 8-K Item 1.01 material agreement disclosure.
-	Layer 4 — Customs data (US Census / Panjiva): Primary: scrape usatrade.census.gov for import data by company legal name. Secondary: scrape panjiva.com/search?q={LEGAL_NAME} for supplier names and shipment frequency. Compare current month supplier list against prior month. Flag new entrants and departures in supplier_signals. Run monthly only.
-	Supplier registry: When a new supplier is detected by any layer, add to supplier_registry with reliability_score = NULL. The agent brain generates a research summary using Claude Haiku. The user assigns the final reliability score manually via the dashboard. Never auto-assign a reliability score.
-	Dashboard surfacing: Unreviewed supplier_registry entries (reliability_score = NULL) must be prominently flagged in Tab 8 (Agent Activity Log / Supplier Registry sub-view). The user should never be able to miss a new supplier requiring review.

Phase 17	Agent Brain Dashboard Tab	PENDING

What to build
-	Location: New Tab 8 in app.py — Agent Activity Log

Tab 8 sub-views
-	Sub-view 1 — Agent Activity Feed: Reverse-chronological table of every synthesis cycle the brain ran. Columns: timestamp, company, trigger description, materiality (MATERIAL / NOISE), synthesis paragraph (expandable), alert sent (yes/no). Filter by company, date range, materiality. This gives full transparency into what the brain is thinking.
-	Sub-view 2 — Supplier Registry: Table of all entries in supplier_registry. Columns: supplier_name, detected_from (company ticker), detection_source (which layer found it), reliability_score (editable inline), reliability_notes (editable inline), financial_health_flag, last_researched_date. Unreviewed entries (NULL score) shown in red at the top. User can click any row to update the score directly in the dashboard.
-	Sub-view 3 — Leadership Events: Table of all leadership_events with departure classification badges. Filter by company and classification type. Shows tenure in days, departure language excerpt, equity acceleration flag.

Phase 18	Weekly Sector Scanner	PENDING

What to build
-	File: ingestion/sector_scanner.py

Saturday 8pm ET job
-	Step 1 — Top 10 per sector: For each of the 11 GICS sectors (IT, Healthcare, Financials, Consumer Discretionary, Communication Services, Industrials, Consumer Staples, Energy, Utilities, Real Estate, Materials): use FMP sector endpoint GET https://financialmodelingprep.com/api/v3/stock-screener?sector={SECTOR}&marketCapMoreThan=5000000000&limit=10&sort=marketCap&apikey={KEY} to get top 10 by market cap. For each company compute: current price, 1-week return, 1-month return, YTD return, P/E from yfinance.info, revenue growth last quarter YoY.
-	Step 2 — One-sentence state: Pass each company's metrics to Claude Haiku: 'In one sentence, describe where {COMPANY} stands right now given these metrics: {metrics}. Be specific, not generic.' Store in sector_scan_results.one_sentence_state.
-	Step 3 — Hidden giant detection: After the top 10 by market cap per sector, run a second pass for companies meeting: market_cap > 5B AND revenue > 2B AND (sector is consumer-facing or B2B2C) AND brand_awareness_proxy < threshold. Brand awareness proxy = pytrends Google Trends interest score for the company name (install pytrends library) divided by market_cap in billions. Low ratio = large company with low public mindshare = hidden giant candidate. Flag in sector_scan_results.hidden_giant_flag = true.
-	Step 4 — Saturday digest: Pass all 110 entries plus hidden giants to Claude Sonnet. Prompt: 'Generate a Saturday market digest covering: (1) one-sentence state of each of the 11 sectors, (2) top 3 hidden giants found this week with explanation of why they qualify, (3) 3-5 companies worth researching further based on interesting score combinations. User follows Peter Lynch observation-based investing.' Store full digest in weekly_digest table. Send to Telegram and display on Tab 5.

Tab 5 — Weekly Sector Digest
Show the most recent Saturday digest at the top. Below it, a sector grid showing all 11 sectors with their top 10 companies in expandable rows. Hidden giants section prominently displayed with a one-click 'Add to Watchlist' button on each. Historical digests accessible via a date picker dropdown.

Phase 19	Congressional Trading Tracker	PENDING

What to build
-	File: ingestion/congress_tracker.py

Data sources
-	Primary — FMP (poll every 4 hours): Senate: GET https://financialmodelingprep.com/api/v4/senate-disclosure?page=0&apikey={KEY} and GET https://financialmodelingprep.com/api/stable/senate-latest?apikey={KEY}. House: GET https://financialmodelingprep.com/api/v4/house-disclosure?page=0&apikey={KEY} and GET https://financialmodelingprep.com/api/stable/house-latest?apikey={KEY}. Deduplicate by (member_name + ticker + trade_date).
-	Committee assignments — Congress.gov: GET https://api.congress.gov/v3/member?currentMember=true&limit=250&api_key={KEY} — paginate until empty. For each member get: GET https://api.congress.gov/v3/member/{bioguideId}/committee-assignment?api_key={KEY}. Store all 535 members in congress_members table. Refresh monthly.
-	Hearing schedule — leading indicator: GET https://api.congress.gov/v3/committee-meeting/119/{chamber}?api_key={KEY}&fromDateTime={NOW}&toDateTime={NOW+30DAYS} — pull upcoming hearings for the next 30 days. When a hearing's subject overlaps with a watchlist sector, open a 30-day watch window on all committee members. Flag them in disclosure_timing_profile.watch_window_active = true.
-	LDA lobbying monitor: GET https://lda.gov/api/v1/filings/?filing_type=registration&format=json&filing_dt_posted_after={LAST_CHECKED} — weekly scan. Cross-reference client_name and general_issue_code against committee_sector_map. Store in lobbying_registrations table.

Committee-sector jurisdiction map — hardcode in database
Committee	Oversight Sectors
Senate Banking	Financials, Real Estate
Senate Armed Services	Defense, Aerospace, Industrials
House/Senate Energy and Commerce	Energy, Utilities, Healthcare
Senate Finance	Healthcare, Insurance, Financials
House/Senate Intelligence	Information Technology, Cybersecurity, Communication Services
Senate Agriculture	Consumer Staples, Materials
House Transportation	Industrials, Logistics
House Financial Services	Financials, Real Estate, Crypto
Senate Commerce	Communication Services, Consumer Discretionary, Tech

Disclosure timing profile — beat the gap
-	Per-member filing history: Compute for each tracked member: avg_days_to_disclose, stddev_days from all historical filings. If a member who typically files within 5 days goes 20+ days silent, set last_30day_silence_flag = true. This likely indicates an undisclosed trade.
-	Post-vote watch window: When a significant floor vote occurs on legislation affecting a tracked sector, flag all tracked members who voted as being in a 30-day watch window. A member who votes on healthcare legislation and goes quiet on disclosures for 3 weeks is the highest priority watch case.

Validation checkpoint
Test the committee-trade correlation logic against known historical examples: members of the House Intelligence Committee trading semiconductor companies before the export control announcements of October 2022. The system must correctly identify those trades as committee-correlated. If it does not, the committee_sector_map jurisdiction entries for Intelligence committees need adjustment.

Phase 20	Tracked Funds 13F Monitor	PENDING

What to build
-	File: ingestion/tracked_funds.py

Primary target — Situational Awareness LP
-	Find CIK: Search EDGAR full-text: GET https://efts.sec.gov/LATEST/search-index?q=%22Situational+Awareness%22&forms=13F-HR — retrieve the CIK from results. Store in tracked_funds table.
-	Pull 13F filings: GET https://data.sec.gov/submissions/CIK{cik}.json — filter for form = '13F-HR'. For each filing, get the infotable XML from the primaryDocument URL. Parse with xml.etree.ElementTree: extract nameOfIssuer, cusip, value (in thousands), sshPrnamt (shares), putCall.
-	Q4 2025 baseline positions to validate against: IREN, Cipher Mining (CIFR), Riot Platforms (RIOT), Bitdeer (BTDR), Applied Digital (APLD), Babcock & Wilcox (BW). If these do not appear in the parsed Q4 2025 13F, the CIK or parsing logic is wrong.
-	Thesis context for synthesis prompt: Include this in every Situational Awareness LP synthesis call: 'Thesis: AGI arrives approximately 2027. The resulting infrastructure buildout requires compute, power, and data centers at historic scale compressed into 3-5 years. Fund is long the physical backbone — Bitcoin miners repositioned as AI compute hosts, power generation, optical networking, custom silicon. When a position is exited, ask: which infrastructure bottleneck thesis has shifted? When an obscure position is entered, ask: which specific bottleneck in the AI stack does this company address?'

Additional tracked funds
-	Pershing Square Capital (Bill Ackman): Find CIK via EDGAR company search for 'Pershing Square'. Pull 13F quarterly.
-	Coatue Management: Find CIK via EDGAR. Pull 13F quarterly. Technology-focused, early signal on AI software themes.
-	Tiger Global Management: Find CIK via EDGAR. Pull 13F quarterly.
-	ARK Invest — daily trades: Scrape https://ark-funds.com/trade-history daily at 6pm ET. The page offers a CSV download per fund — use requests to download the CSV, parse with pandas. Store in ark_daily_trades table. Flag any trade above $10 million for agent brain review using Claude Haiku for the initial summary.

Delta detection and alerts
-	Quarterly delta: Compare current quarter fund_positions against prior quarter. Flag: new positions (not in prior quarter), full exits (in prior quarter, not in current), size changes above 20%, options type direction changes (calls converting to puts).
-	Convergence signal: After computing deltas for all tracked funds in the same quarter, check for any ticker appearing as a new position or exit in 2 or more funds simultaneously. This is the highest-value signal in the module — fire Telegram + email immediately.
-	Synthesis call: Every delta above $50M in value change triggers a Claude Sonnet synthesis call using the fund's thesis context. Output stored in fund_analysis_log. Telegram alert sent immediately with the synthesis paragraph.

Tab 7 — Tracked Funds dashboard
Show current quarter holdings for each tracked fund in expandable panels. Quarter-over-quarter delta highlighted: new positions in green, exits in red, size changes with directional arrows. Convergence panel at the top showing any position held by 2+ tracked funds. ARK daily trades in a separate sub-view with 30-day activity log and a filter by fund ticker.

Pattern Intelligence — Two Phases
Market Lens uses two distinct forms of pattern intelligence. Phase 1 is implemented now using the Claude API as a pattern reasoner. Phase 2 is added after 12 months of data has accumulated.

Phase 1 — Claude API Pattern Reasoning (Implement Now)
-	90-day signal history: The compressed signal history in agent_memory is passed to every synthesis prompt. This enables the model to reason across patterns — 'this is the third insider sale in 90 days while revenue guidance was cut' — rather than evaluating events in isolation.
-	Congressional pattern prompt: For each of the top 50 tracked members, maintain a rolling 18-month trade history alongside their committee activity calendar. Every new disclosure triggers a synthesis prompt asking: does this member have a demonstrated pattern of trading ahead of specific committee actions? Name the most recent example if yes.
-	Cross-module coincidence detection: Already implemented in delta.py. When two or more signals from different modules fire within the same window, the synthesis call is flagged for deep cross-signal analysis.

Phase 2 — Classical ML Anomaly Detection (Add After 12 Months of Data)
-	IsolationForest: Add analysis/anomaly.py using scikit-learn's IsolationForest. Train on 12+ months of price, volume, and sentiment time-series already in the database. No labeled training data required. Detects statistical outliers that no explicit rule would catch. This is the only machine learning component in the platform.
-	Rolling correlation matrices: Compute pairwise correlations between Lynch score changes, sentiment shifts, insider activity, and subsequent price performance over rolling 90-day windows. Flag emergent correlations that were previously near zero but become strongly positive or negative.
-	Congressional trade return attribution: After 12 months of data, compute average return of stocks purchased by each tracked member in the 30, 60, and 90 days following disclosure. Sort top 50 by attribution score quarterly and reprioritize alerts accordingly.

Quick Reference — Key File Paths and Commands
Command	Purpose
.\venv\Scripts\python.exe -m market_lens.database.seed	Re-run seed (idempotent)
.\venv\Scripts\python.exe -m market_lens.database.watchlist list	List all watchlist companies
streamlit run app.py	Launch dashboard at localhost:8501
streamlit run verify.py	Launch diagnostic data check (Phase 2 temp tool)
.\venv\Scripts\python.exe agent.py	Start agent brain manually
nssm install MarketLensAgent ...	Register agent as Windows Service
nssm start MarketLensAgent	Start the Windows Service
nssm stop MarketLensAgent	Stop the Windows Service

Key File	Purpose
agent.py	Agent brain entry point — runs as Windows Service via NSSM
app.py	Streamlit dashboard — run manually when you want to review
config.py	All configuration loaded from .env — single source of truth
ingestion/edgar.py	SEC EDGAR ingestion — price, filings, Form 4
ingestion/congress_tracker.py	Congressional trading monitor
ingestion/tracked_funds.py	13F quarterly monitor for Situational Awareness LP and others
agent/synthesizer.py	Most critical prompt in the system — do not modify without testing
analysis/scoring.py	Lynch score and swing score computation
database/seed.py	Initial data — safe to re-run, idempotent


Market Lens  |  Build Handoff Document  |  Phases 2-20  |  March 2026
