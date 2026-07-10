"""
One-off migration: add missing columns to existing tables so that
SQLAlchemy models match the database. Safe to run multiple times.
Run: python scripts/migrate_schema.py (from project root, with venv active).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from market_lens.config import DATABASE_URL


def column_exists(conn, table: str, column: str) -> bool:
    r = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return r.fetchone() is not None


def main():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        # companies: Phase 4 columns
        for col, typ in [
            ("revenue_cagr_3y", "DOUBLE PRECISION"),
            ("gross_margin_trend", "VARCHAR(20)"),
            ("fcf_yield", "DOUBLE PRECISION"),
            ("debt_ebitda_ratio", "DOUBLE PRECISION"),
            ("dividend_streak_years", "INTEGER"),
        ]:
            if not column_exists(conn, "companies", col):
                conn.execute(text(f"ALTER TABLE companies ADD COLUMN {col} {typ}"))
                conn.commit()
                print(f"  Added companies.{col}")
        # scores: Phase 4 dcf_fair_value_mid
        if not column_exists(conn, "scores", "dcf_fair_value_mid"):
            conn.execute(text("ALTER TABLE scores ADD COLUMN dcf_fair_value_mid DOUBLE PRECISION"))
            conn.commit()
            print("  Added scores.dcf_fair_value_mid")
    print("[OK] Migration done.")


if __name__ == "__main__":
    main()
