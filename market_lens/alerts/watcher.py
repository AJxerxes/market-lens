"""
Market Lens — Alert Watcher (Phase 8)
Evaluates conditions and calls notifier for Telegram/email.
Alert types and channels are defined here; agent brain and ingestion modules
call send_alert when a trigger fires.
"""
from typing import Optional, Literal
from market_lens.alerts.notifier import send_telegram, send_email, format_telegram_alert

Channel = Literal["telegram", "email", "both"]


def send_alert(
    alert_type: str,
    ticker: str,
    signal_line: str,
    channel: Channel = "telegram",
    email_subject: Optional[str] = None,
    email_body: Optional[str] = None,
) -> None:
    """
    Send alert to Telegram and/or email.
    alert_type: e.g. "8K", "SWING", "LYNCH_UP"
    ticker: symbol
    signal_line: one-line description of the signal (line 2 of Telegram).
    """
    if channel in ("telegram", "both"):
        msg = format_telegram_alert(alert_type, ticker, signal_line)
        ok, err = send_telegram(msg)
        if not ok:
            # Surface delivery issues so they are not silently swallowed.
            print(f"[ALERT WARNING] Telegram delivery failed for {alert_type} {ticker}: {err}")
    if channel in ("email", "both"):
        subj = email_subject or f"Market Lens: {alert_type} {ticker}"
        body = email_body or signal_line
        ok, err = send_email(subj, body)
        if not ok:
            print(f"[ALERT WARNING] Email delivery failed for {alert_type} {ticker}: {err}")
