"""Quick test: CIK map + company facts for DLB."""
from market_lens.ingestion.edgar import (
    _session,
    refresh_ticker_cik_map,
    _get_cik_for_ticker,
    _fetch_company_facts,
    _extract_us_gaap_facts,
    _upsert_edgar_facts,
)
from market_lens.database.models import Base
from market_lens.config import DATABASE_URL
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
s = Session()
refresh_ticker_cik_map(s)
s.commit()
cik = _get_cik_for_ticker(s, "DLB")
print("DLB CIK:", cik)
sess = _session()
facts = _fetch_company_facts(sess, cik)
rows = _extract_us_gaap_facts(facts, "DLB") if facts else []
print("DLB facts rows:", len(rows))
_upsert_edgar_facts(s, rows)
s.commit()
r = s.execute(text("SELECT tag, period_end, value FROM edgar_facts WHERE ticker = 'DLB' AND tag IN ('Revenues','NetIncomeLoss') LIMIT 5"))
print("Sample edgar_facts:", list(r))
s.close()
print("[OK] EDGAR pipeline verified for DLB")
