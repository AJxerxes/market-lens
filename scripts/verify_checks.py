"""
Quick DB verification for Checks 1, 2, 8, 9.
Run: python scripts/verify_checks.py (from project root, venv active).
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from market_lens.config import DATABASE_URL

def main():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        # Check 1: price_history for 4 tickers
        r = conn.execute(text(
            "SELECT ticker, COUNT(*) AS cnt FROM price_history GROUP BY ticker"
        ))
        rows = r.fetchall()
        print("Check 1 - price_history:", dict((r[0], r[1]) for r in rows))
        # Check 2: edgar_facts Revenues for DLB, SYY; insider_transactions
        r = conn.execute(text(
            "SELECT ticker, COUNT(*) FROM edgar_facts WHERE tag = 'Revenues' AND ticker IN ('DLB','SYY') GROUP BY ticker"
        ))
        print("Check 2 - edgar_facts Revenues (DLB,SYY):", dict(r.fetchall()))
        r = conn.execute(text("SELECT COUNT(*) FROM insider_transactions"))
        print("Check 2 - insider_transactions count:", r.scalar())
        # Check 8: congress_trades, committee_sector_map
        r = conn.execute(text("SELECT COUNT(*) FROM congress_trades"))
        print("Check 8 - congress_trades:", r.scalar())
        r = conn.execute(text("SELECT COUNT(*) FROM committee_sector_map"))
        print("Check 8 - committee_sector_map:", r.scalar())
        # Check 9: fund_positions (Situational Awareness), ark_daily_trades
        r = conn.execute(text(
            "SELECT COUNT(*) FROM fund_positions fp JOIN tracked_funds tf ON fp.fund_id = tf.id WHERE tf.name LIKE '%Situational%'"
        ))
        print("Check 9 - fund_positions (Situational Awareness):", r.scalar())
        r = conn.execute(text("SELECT COUNT(*) FROM ark_daily_trades"))
        print("Check 9 - ark_daily_trades:", r.scalar())
        # Check 6: agent_cycle_log
        r = conn.execute(text("SELECT COUNT(*) FROM agent_cycle_log"))
        print("Check 6 - agent_cycle_log:", r.scalar())
    print("[OK] Verify done.")

if __name__ == "__main__":
    main()
