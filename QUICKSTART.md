# Market Lens - Quick Start Guide

## Phase 1 Complete ✅

The foundation is built. Here's how to get started.

## Prerequisites

- **Windows 10/11** with Python 3.11+ installed
- **PostgreSQL 15+** with pgAdmin
- **Git** (optional, for version control)

## Setup (5 Steps)

### Step 1: Install Python Dependencies

```powershell
# Navigate to project directory
cd "C:\Users\User\.cursor\worktrees\Market_Lens\avi"

# Create virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\activate

# Install all dependencies
pip install -r requirements.txt
```

This installs ~30 packages including:
- streamlit (dashboard)
- sqlalchemy, psycopg2-binary (database)
- yfinance, fredapi (market data)
- transformers, torch (NLP/FinBERT)
- anthropic (Claude API)
- APScheduler, python-telegram-bot (scheduling & alerts)

### Step 2: Configure Environment

```powershell
# Copy template
copy .env.example .env

# Edit .env in your favorite editor
notepad .env
```

**Minimum required for Phase 1 testing:**
```env
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/market_lens
EDGAR_USER_AGENT=Market Lens Research your_email@example.com
```

**Optional (can add later):**
- FRED_API_KEY (free from fred.stlouisfed.org)
- NEWSAPI_KEY (free from newsapi.org)
- ANTHROPIC_API_KEY (paid, ~$2-8/month)
- TELEGRAM_BOT_TOKEN (free via @BotFather)
- FMP_API_KEY (free from financialmodelingprep.com)
- CONGRESS_API_KEY (free from api.congress.gov)
- USPTO_API_KEY (free from data.uspto.gov for PTAB)
- COURTLISTENER_TOKEN (free token from courtlistener.com)

### Step 3: Create PostgreSQL Database

1. Open **pgAdmin**
2. Right-click **Databases** → **Create** → **Database**
3. Name: `market_lens`
4. Owner: `postgres`
5. Click **Save**

### Step 4: Seed Database

```powershell
# Make sure venv is activated
.\venv\Scripts\activate

# Run seeder
python -m market_lens.database.seed
```

Expected output:
```
============================================================
Market Lens Database Seeder
============================================================
Creating database tables...
✓ Tables created successfully

Seeding initial watchlist...
  ✓ Added ASAZY (Assa Abloy AB) as otc_adr
  ✓ Added DLB (Dolby Laboratories, Inc.) as equity
  ✓ Added SYY (Sysco Corporation) as equity
  ✓ Added JBHT (J.B. Hunt Transport Services, Inc.) as equity

✓ Watchlist seeded successfully

============================================================
Seeding complete!
============================================================
```

### Step 5: Verify Setup

```powershell
# Run verification tests
python test_phase1.py
```

All tests should pass ✓

## Test the Watchlist Manager

```powershell
# List current watchlist
python -m market_lens.database.watchlist list

# Add a new ticker
python -m market_lens.database.watchlist add CTAS "Cintas - uniform rental trucks everywhere"

# Add by company name (will search and confirm)
python -m market_lens.database.watchlist add "Fastenal"

# List again to see new additions
python -m market_lens.database.watchlist list
```

## Verify in pgAdmin

Open pgAdmin and explore:

1. **Database**: `market_lens`
2. **Schemas** → **public** → **Tables** (should see 25+ tables)
3. **companies** table → View Data
   - Should see 4 seed companies (ASAZY, DLB, SYY, JBHT)
4. **agent_memory** table → View Data
   - Should see 4 initial snapshots

## What You Have Now

### ✅ Complete Database Schema
- 25+ tables covering all Market Lens features
- Companies with instrument type classification
- Price history, fundamentals, scores
- Insider transactions, news sentiment, options signals
- Agent brain memory and cycle logs
- Court cases, leadership tracking, supplier intelligence
- Congressional trading with committee correlation
- Weekly sector scanner

### ✅ Dynamic Watchlist Manager
- Add any ticker (equity, OTC ADR, ETF, inverse ETF, mutual fund)
- Auto-classification from yfinance metadata
- Search by ticker or company name
- Thesis notes (your Lynch observation)
- Soft delete (data retained)
- Pause/resume monitoring

### ✅ Cross-Platform Foundation
- pathlib.Path for all file paths (no backslashes)
- UTC timestamps internally, ET for display
- No Windows-only libraries
- Same code runs on Windows (NSSM) or Linux (systemd)

### ✅ Documentation
- README.md - Full project overview
- NSSM_SETUP.md - Windows Service guide
- .env.example - All API keys documented
- test_phase1.py - Verification script

## What's Next (Phase 2)

Phase 2 will implement:
- `ingestion/prices.py` - yfinance price history
- 5-year historical backfill for all watchlist companies
- Fundamental data ingestion (revenue, margins, FCF, P/E)
- Data quality flags for incomplete OTC/ADR data

## Troubleshooting

### Python not found
Install Python 3.11+ from python.org, ensure "Add to PATH" is checked during installation.

### PostgreSQL connection error
1. Verify PostgreSQL is running (check Services)
2. Check DATABASE_URL in .env matches your PostgreSQL credentials
3. Test connection in pgAdmin first

### Import errors
Make sure virtual environment is activated:
```powershell
.\venv\Scripts\activate
```

### Table creation fails
Drop and recreate the database in pgAdmin, then re-run seed script.

## Getting API Keys (Optional for Phase 1)

You can test Phase 1 without any API keys. Add these later:

### Free Tier APIs
- **FRED**: fred.stlouisfed.org/docs/api/ (instant approval)
- **NewsAPI**: newsapi.org/register (100 req/day free)
- **Alpha Vantage**: alphavantage.co/support/#api-key (25 req/day free)
- **Congress.gov**: api.congress.gov (instant approval)
- **USPTO PTAB**: data.uspto.gov (api.data.gov/USPTO/PTAB/v3)
- **FMP**: financialmodelingprep.com (250 req/day free)
- **CourtListener**: courtlistener.com (token auth, removes default rate cap)

### Paid APIs (Low Cost)
- **Anthropic Claude**: console.anthropic.com (~$2-8/month for personal use)

### Free Alerts
- **Telegram Bot**: Message @BotFather on Telegram, create bot, get token
- **Email**: Use Gmail SMTP with app password (free)

## Support

This is a personal project. See documentation in `docs/` folder.

For Phase 2 and beyond, follow the build order in the main spec document.

---

**Status**: Phase 1 Complete ✅  
**Ready for**: Phase 2 (Price & Fundamentals Ingestion)  
**Estimated Phase 2 time**: 2-3 hours
