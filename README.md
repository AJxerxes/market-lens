# Market Lens

**Personal Investment Research & Pricing Platform**  
Version 2.0 - Active Agent Edition

Market Lens is a Peter Lynch-style investment research platform that validates real-world business observations with financial data, computes fair value ranges, and runs an active agent brain that monitors news, filings, and signals 24/7.

## Philosophy

- **Lynch Framework**: Invest in what you observe in daily life, validate with fundamentals
- **Explainable**: Every score, alert, and recommendation comes with plain-English reasoning
- **Agent Brain**: Runs continuously in the background, surfaces material changes proactively
- **Single-User**: Built for one retail investor, no auth complexity
- **Dual-Instance Portable**: Same code runs on Windows (NSSM) and Linux (systemd)

## Features

### Core Capabilities

- **Dynamic Watchlist**: Add any ticker (equity, OTC ADR, ETF, inverse ETF, mutual fund) at runtime with auto-classification
- **Lynch Score**: Weighted fundamental analysis (revenue growth, FCF, P/E, insider activity, leadership stability, supplier risk)
- **Swing Score**: Technical + options flow + sentiment for timing decisions
- **Valuation**: DCF, comps, and mean reversion models → fair value range
- **Agent Brain**: Perceive → Compare → Reason → Notify loop runs 24/7

### Data Sources (All Free or Low-Cost)

- **SEC EDGAR**: 10-K, 10-Q, 8-K, Form 4, 13F
- **yfinance**: Price history, fundamentals, sector data, Layer 1 options chains
- **FRED**: Macro indicators (rates, CPI, PMI)
- **NewsAPI**: Headlines + FinBERT sentiment
- **Options Flow**: 3-layer cross-validation (yfinance computed unusual volume + Unusual Whales public flow + Nasdaq options page)
- **Court Dockets**: CourtListener v4 + PACER fallback (token auth)
- **Congressional Trading**: STOCK Act disclosures with committee correlation
- **Supplier Intelligence**: 10-K risk factors + US Census trade data + Panjiva previews (monthly, best-effort)
- **Leadership Tracking**: 8-K Item 5.02 departure classification

### Agent Brain Intelligence

- **Pattern Recognition**: 90-day signal history fed to Claude API for pattern vs noise detection
- **Leadership Instability**: Tracks C-suite velocity, departure language, equity acceleration
- **Supplier Switches**: Detects new suppliers in filings/transcripts/customs before disclosure
- **Congressional Signals**: Committee hearing calendar + bill tracking as leading indicators
- **Weekly Sector Scan**: Hidden giant detector (high market cap, low brand awareness)

## Architecture

```
market_lens/
├── app.py                    # Streamlit dashboard
├── agent.py                  # Agent brain (runs as Windows Service via NSSM)
├── config.py                 # Environment config (pathlib, UTC, portable)
├── database/
│   ├── models.py             # SQLAlchemy ORM (all timestamps UTC)
│   ├── seed.py               # Initial watchlist seeder
│   └── watchlist.py          # Dynamic add/remove/pause
├── ingestion/                # Data ingestion modules
├── processing/               # NLP, OCR, parsing
├── analysis/                 # Fundamentals, valuation, technicals
├── agent/                    # Brain, memory, delta, synthesizer
├── alerts/                   # Telegram + email
└── recommendation/           # Final scoring + rationale
```

## Installation

### Prerequisites

- **Windows 10/11** (primary) or **Ubuntu 22.04 LTS** (cloud migration path)
- **Python 3.11+**
- **PostgreSQL 15+** with pgAdmin
- **NSSM** (Windows) or systemd (Linux)

### Setup Steps

1. **Clone repository**
   ```powershell
   cd C:\Users\User\.cursor\worktrees\Market_Lens\avi
   ```

2. **Create virtual environment**
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```powershell
   copy .env.example .env
   # Edit .env with your API keys and database credentials
   ```

4. **Create PostgreSQL database**
   - Open pgAdmin
   - Create database: `market_lens`
   - Update `DATABASE_URL` in `.env`

5. **Seed database**
   ```powershell
   python -m market_lens.database.seed
   ```

6. **Test watchlist manager**
   ```powershell
   python -m market_lens.database.watchlist list
   ```

7. **Register agent as Windows Service** (after Phase 14)
   See `docs/NSSM_SETUP.md`

## Usage

### Dashboard

```powershell
streamlit run market_lens/app.py
```

Open browser to `http://localhost:8501`

### Add Ticker to Watchlist

```powershell
# By ticker
python -m market_lens.database.watchlist add CTAS "Cintas - uniform rental trucks everywhere"

# By company name (will search and confirm)
python -m market_lens.database.watchlist add "Fastenal"
```

### Agent Brain

Runs as background service via NSSM (see `docs/NSSM_SETUP.md`).

Monitors:
- News 3x daily (9am, 12pm, 5pm ET)
- EDGAR every 30 minutes
- Options flow every 15 minutes (market hours)
- Court dockets daily
- Sector scan Saturdays

## API Keys Required

### Free Tier (Sufficient for Personal Use)

- **SEC EDGAR**: No key, just set `EDGAR_USER_AGENT` to your email
- **FRED**: Free from fred.stlouisfed.org
- **NewsAPI**: Free tier (100 req/day) from newsapi.org
- **Alpha Vantage**: Free tier (25 req/day) from alphavantage.co (statements + earnings calendar)
- **Congress.gov**: Free from api.congress.gov
- **USPTO PTAB**: Free key from data.uspto.gov (api.data.gov/USPTO/PTAB/v3)
- **FMP**: Free tier from financialmodelingprep.com (congressional trades + helpers)
- **CourtListener**: Free token from courtlistener.com (stored as COURTLISTENER_TOKEN)

### Paid (Low Cost)

- **Anthropic Claude API**: ~$2-8/month for personal use with smart model routing
  - Haiku 4.5 for high-frequency low-stakes calls
  - Sonnet 4.6 for deep agent brain synthesis

### Optional Upgrades (Only if Free Stack Insufficient)

- **WhaleStream**: Real-time options sweeps (~$30/month)
- **Polygon.io**: Intraday tick data (from $29/month)

## Development Phases

Status as of 2026-07-10, based on `GO_LIVE_VERIFICATION_SUMMARY.md` and a live
verification pass (Telegram, Claude Haiku/Sonnet, congressional data sources).
All active code lives under `market_lens/`; the top-level `ingestion/`,
`analysis/`, `agent/`, `alerts/`, `recommendation/`, `database/`, and `models/`
folders are stale pre-consolidation duplicates and are not imported by
`app.py` or `agent.py`.

- ✅ **Phase 1**: Foundation (config, models, seed, watchlist)
- ✅ **Phase 2**: Price & fundamentals ingestion
- ✅ **Phase 3**: EDGAR ingestion
- ✅ **Phase 4**: Fundamentals analysis & valuation
- ✅ **Phase 5**: Scoring engine
- ✅ **Phase 6**: NLP pipeline — implemented with Claude Haiku sentiment scoring instead of FinBERT
- ✅ **Phase 7**: Streamlit dashboard (9 tabs)
- ✅ **Phase 8**: Alerts — Telegram verified live; email (AOL SMTP) code path is correct but untestable from a sandbox that blocks outbound port 587
- ✅ **Phase 9**: Claude API rationale generation — verified live (Haiku + Sonnet)
- ✅ **Phase 10**: OCR pipeline (EDGAR text → pdfplumber → Tesseract → manual-placeholder cascade)
- ✅ **Phase 11**: Agent brain core (memory + delta)
- ✅ **Phase 12**: Agent synthesizer (Claude reasoning) — verified live
- ✅ **Phase 13**: Court docket monitor
- ✅ **Phase 14**: Agent scheduling & full loop (APScheduler cron jobs in `agent.py`)
- ✅ **Phase 15**: Leadership instability tracker
- ✅ **Phase 16**: Supplier intelligence
- ✅ **Phase 17**: Agent brain dashboard tab — now a dedicated "Agent Brain" tab
- ✅ **Phase 18**: Weekly sector scanner
- ⚠️ **Phase 19**: Congressional trading tracker — ingestion code is complete, but all three of its free data sources are currently dead/paywalled: the House GitHub JSON mirror repo no longer exists (404), the House Clerk fallback target is a JS-rendered SPA that yields no scrapeable links, and the Senate GitHub mirror hasn't been updated since 2021. FMP's `senate-trades` endpoint requires a paid tier not included on the current key. A new data source needs to be sourced before this phase produces live data.

### Known issues fixed since the phases above were last verified

- Tracked-funds quarter-over-quarter position delta computation was a stub (`TODO`); now implemented in `market_lens/ingestion/tracked_funds.py`.
- `agent.py` scheduled both a standalone Saturday sector-scan job and the weekly-digest job (which itself calls the sector scan) at the same time, doubling scan writes and Claude Haiku calls — the redundant job was removed.
- `CLAUDE_SONNET_MODEL` defaulted to a retired model ID (`claude-sonnet-4-20250514`, HTTP 404) in `market_lens/config.py` — every Sonnet-tier call (agent synthesis, recommendation rationale) was silently failing. Updated to `claude-sonnet-5`.

## Design Principles

### Cross-Platform Portability

- **No Windows-only libraries** in code
- **pathlib.Path** for all file paths (never backslashes)
- **UTC timestamps** internally, ET for display only
- **Environment variables** for all connection strings
- **Process manager abstraction**: NSSM (Windows) or systemd (Linux) wraps `agent.py` externally

### Data Quality

- **Data quality flags** for incomplete OTC/ADR data
- **Three-source cross-validation** for options flow before alerting
- **CourtListener first**, PACER only on manual flag to control costs
- **Graceful degradation** when scrapers fail

### Alert Discipline

- **Max 2 alerts per company per day** unless critical event
- **Pattern reasoning** over individual events (90-day history context)
- **Material vs noise** distinction via Claude synthesis
- **Logged but not alerted** when brain concludes noise

## License

Personal use only. Not for redistribution or commercial use.

## Support

This is a personal project. No official support. See `docs/` for detailed setup guides.

## Acknowledgments

Built on the Peter Lynch investment philosophy from *One Up On Wall Street*.

Data sources: SEC EDGAR, FRED, yfinance, and the open-source community.
