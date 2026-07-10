"""
Market Lens — Alert test script.
Sends one Telegram and one email test message and prints success/failure and any error.
Run from project root: python scripts/test_alerts.py  (or .\venv\Scripts\python.exe scripts\test_alerts.py on Windows)
"""
import sys

# Ensure package is importable when run from project root
sys.path.insert(0, ".")

from market_lens.alerts.notifier import send_telegram, send_email

def main():
    print("Sending test Telegram...")
    ok_tg, err_tg = send_telegram("Market Lens test — Telegram OK")
    if ok_tg:
        print("  Telegram: SUCCESS")
    else:
        print(f"  Telegram: FAILED — {err_tg or 'unknown'}")

    print("Sending test email...")
    ok_em, err_em = send_email("Market Lens test", "Dashboard test email. If you see this, email alerts work.")
    if ok_em:
        print("  Email: SUCCESS")
    else:
        print(f"  Email: FAILED — {err_em or 'unknown'}")

    if ok_tg and ok_em:
        print("\nAll alerts sent. Check Telegram chat and inbox (ALERT_EMAIL_TO).")
        return 0
    print("\nOne or more alerts failed. Set TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SMTP_*, ALERT_EMAIL_TO in .env as needed.")
    return 1

if __name__ == "__main__":
    sys.exit(main())
