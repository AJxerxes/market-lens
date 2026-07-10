"""Add digest_type and digest_time to weekly_digest; drop old unique on digest_date."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import create_engine, text
from market_lens.config import DATABASE_URL

engine = create_engine(DATABASE_URL)
with engine.connect() as c:
    c.execute(text("ALTER TABLE weekly_digest ADD COLUMN IF NOT EXISTS digest_type VARCHAR(20)"))
    c.execute(text("ALTER TABLE weekly_digest ADD COLUMN IF NOT EXISTS digest_time VARCHAR(20)"))
    c.execute(text("UPDATE weekly_digest SET digest_type = 'weekly' WHERE digest_type IS NULL"))
    try:
        c.execute(text("ALTER TABLE weekly_digest DROP CONSTRAINT IF EXISTS weekly_digest_digest_date_key"))
    except Exception:
        pass
    c.commit()
print("Migration done.")
