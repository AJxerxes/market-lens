"""Add filing_id, senate_id, source to lobbying_registrations if missing. Safe to run multiple times."""
import sys
from pathlib import Path

# Project root = parent of market_lens
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from market_lens.config import DATABASE_URL

def main():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        for col, typ in [
            ("filing_id", "VARCHAR(100)"),
            ("senate_id", "VARCHAR(50)"),
            ("source", "VARCHAR(50)"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE lobbying_registrations ADD COLUMN IF NOT EXISTS {col} {typ}"))
                conn.commit()
                print(f"Added column (if missing): {col}")
            except Exception as e:
                print(f"Column {col}: {e}")
    print("Migration complete.")

if __name__ == "__main__":
    main()
