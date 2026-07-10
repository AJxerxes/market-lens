"""
Market Lens — Configuration Module
All paths use pathlib.Path. All internal timestamps are UTC.
Portable: same code on Windows (NSSM) and Linux (systemd).
"""
from pathlib import Path
import os
from dotenv import load_dotenv

# Resolve project root: directory containing this file (market_lens/) then parent
_PROJECT_ROOT = Path(__file__).resolve().parent
# Workspace root (Market Lens folder) — one level up from market_lens package
WORKSPACE_ROOT = _PROJECT_ROOT.parent

# Load environment variables from .env at workspace root
load_dotenv(WORKSPACE_ROOT / ".env")

# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/market_lens",
)

# -----------------------------------------------------------------------------
# OCR — Tesseract executable (Windows default; override with TESSERACT_CMD)
# Install from https://github.com/UB-Mannheim/tesseract/wiki to default path.
# -----------------------------------------------------------------------------
try:
    import pytesseract
    _tesseract_cmd = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd
except ImportError:
    pass

# -----------------------------------------------------------------------------
# Paths (pathlib — no backslashes, cross-platform)
# -----------------------------------------------------------------------------
LOG_DIR = Path(os.getenv("MARKET_LENS_LOG_DIR", str(WORKSPACE_ROOT / "logs")))
LOG_MAX_BYTES = int(os.getenv("MARKET_LENS_LOG_MAX_BYTES", 10 * 1024 * 1024))  # 10MB
LOG_BACKUP_COUNT = int(os.getenv("MARKET_LENS_LOG_BACKUP_COUNT", 5))

# -----------------------------------------------------------------------------
# SEC EDGAR (required: User-Agent with contact email per SEC policy)
# -----------------------------------------------------------------------------
EDGAR_USER_AGENT = os.getenv(
    "EDGAR_USER_AGENT",
    "Market Lens Research contact@example.com",
)
EDGAR_BASE_URL = os.getenv("EDGAR_BASE_URL", "https://data.sec.gov")

# -----------------------------------------------------------------------------
# API keys (optional at startup; modules check before use)
# -----------------------------------------------------------------------------
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY", "")
USPTO_API_KEY = os.getenv("USPTO_API_KEY", "")
FMP_API_KEY = os.getenv("FMP_API_KEY", "")  # Financial Modeling Prep
COURTLISTENER_TOKEN = os.getenv("COURTLISTENER_TOKEN", "")

# Telegram & email alerts
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")

# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------
STREAMLIT_PORT = int(os.getenv("STREAMLIT_PORT", "8501"))
DASHBOARD_BASE_URL = os.getenv("DASHBOARD_BASE_URL", "http://localhost:8501")

# -----------------------------------------------------------------------------
# Timezone: internal = UTC only; display uses ET
# -----------------------------------------------------------------------------
DISPLAY_TIMEZONE = os.getenv("DISPLAY_TIMEZONE", "America/New_York")

# -----------------------------------------------------------------------------
# LLM model routing (Anthropic Claude)
# -----------------------------------------------------------------------------
# Defaults align with current Anthropic model IDs; override via .env if needed.
CLAUDE_SONNET_MODEL = os.getenv(
    "CLAUDE_SONNET_MODEL",
    "claude-sonnet-5",
)
CLAUDE_HAIKU_MODEL = os.getenv(
    "CLAUDE_HAIKU_MODEL",
    "claude-haiku-4-5-20251001",
)

# -----------------------------------------------------------------------------
# Scoring weights (user-adjustable; override via .env if desired)
# -----------------------------------------------------------------------------
LYNCH_WEIGHTS = {
    "revenue_growth_3y_cagr": 0.18,
    "fcf_yield_vs_sector": 0.13,
    "pe_vs_own_5y_avg": 0.13,
    "insider_net_buy": 0.13,
    "gross_margin_trend": 0.10,
    "dividend_growth_streak": 0.08,
    "debt_ebitda_ratio": 0.08,
    "leadership_stability": 0.10,
    "supplier_chain_risk": 0.07,
    "news_sentiment_30d": 0.00,
}

SWING_WEIGHTS = {
    "rsi_position": 0.25,
    "unusual_options_volume": 0.25,
    "volume_anomaly": 0.20,
    "insider_activity_90d": 0.15,
    "news_sentiment_7d": 0.15,
}

# -----------------------------------------------------------------------------
# Helper function to ensure directories exist
# -----------------------------------------------------------------------------
def ensure_directories():
    """Create necessary directories if they don't exist."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
