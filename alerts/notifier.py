"""
Market Lens — Notifier (Phase 8)
Telegram and email delivery. 3-line max for Telegram; AOL SMTP for email.
Returns (success, error_message); error_message is None on success.
"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Tuple

from market_lens.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    ALERT_EMAIL_TO,
    DASHBOARD_BASE_URL,
)

logger = logging.getLogger(__name__)


def send_telegram(message: str) -> Tuple[bool, Optional[str]]:
    """Send message to Telegram chat. Message should be 3 lines max. Returns (success, error_message)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        err = "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"
        logger.warning("send_telegram: %s", err)
        return False, err
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        if r.status_code == 200:
            return True, None
        err = f"HTTP {r.status_code}: {r.text[:200] if r.text else 'no body'}"
        logger.warning("send_telegram: %s", err)
        return False, err
    except Exception as e:
        err = str(e)
        logger.exception("send_telegram failed")
        return False, err


def send_email(subject: str, body: str) -> Tuple[bool, Optional[str]]:
    """Send email via AOL SMTP (TLS). Returns (success, error_message)."""
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD or not ALERT_EMAIL_TO:
        err = "SMTP_HOST, SMTP_USER, SMTP_PASSWORD, or ALERT_EMAIL_TO not set"
        logger.warning("send_email: %s", err)
        return False, err
    try:
        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = ALERT_EMAIL_TO
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, ALERT_EMAIL_TO, msg.as_string())
        return True, None
    except Exception as e:
        err = str(e)
        logger.exception("send_email failed")
        return False, err


def format_telegram_alert(alert_type: str, ticker: str, signal_line: str) -> str:
    """Format 3-line Telegram alert. Line 3 = dashboard link."""
    lines = [
        f"{alert_type} {ticker.upper()}",
        signal_line,
        f"{DASHBOARD_BASE_URL}/company/{ticker}" if DASHBOARD_BASE_URL else "",
    ]
    return "\n".join(lines[:3])
