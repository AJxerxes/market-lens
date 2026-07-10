"""
LDA (Lobbying Disclosure Act) ingestion from lda.gov.
Fetch recent filings without invalid filing_type filter; store all types.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_lens.config import DATABASE_URL
from market_lens.database.models import Base, LobbyingRegistration

LDA_API_BASE = "https://lda.gov/api/v1"
USER_AGENT = "MarketLens/1.0 (compliance; omniaj@aol.com)"

_engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=_engine)


def _get_session():
    return SessionLocal()


def _http_get(path: str, params: Optional[dict] = None) -> Optional[dict]:
    url = f"{LDA_API_BASE}{path}"
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(url, params=params or {}, headers=headers, timeout=30)
        if r.status_code != 200:
            print(f"[Lobbying] lda.gov {path} returned status {r.status_code}")
            return None
        return r.json()
    except requests.exceptions.Timeout:
        print(f"[Lobbying] lda.gov {path} timed out")
        return None
    except Exception as e:
        print(f"[Lobbying] lda.gov request failed: {e}")
        return None


def ingest_lobbying_filings(page_size: int = 50) -> int:
    """
    Fetch recent filings from lda.gov without filing_type=registration.
    Valid filing_type values are discovered from the API response.
    Store all returned filings in lobbying_registrations.
    Returns count of new rows inserted.
    """
    # No filing_type filter — fetch recent filings; API may use format=json and pagination
    data = _http_get("filings/", params={"format": "json", "page_size": page_size})
    if not data:
        return 0

    # Handle list or dict with results key
    if isinstance(data, list):
        results = data
    elif isinstance(data, dict):
        results = data.get("results") or data.get("filings") or data.get("data") or []
    else:
        results = []

    session = _get_session()
    inserted = 0
    try:
        for item in results:
            if not isinstance(item, dict):
                continue
            reg_id = str(item.get("id") or item.get("registration_id") or item.get("filing_id") or "")
            if not reg_id:
                continue
            existing = session.query(LobbyingRegistration).filter_by(registration_id=reg_id).first()
            if existing:
                continue
            filing_date_str = item.get("filing_date") or item.get("received_date") or item.get("date")
            try:
                filing_date = date.fromisoformat(str(filing_date_str)[:10]) if filing_date_str else date.today()
            except ValueError:
                filing_date = date.today()
            session.add(LobbyingRegistration(
                registration_id=reg_id,
                registrant_name=item.get("registrant_name") or item.get("registrant"),
                client_name=item.get("client_name") or item.get("client"),
                filing_date=filing_date,
                covered_officials=item.get("covered_officials"),
                sector_keywords=item.get("sector_keywords") or item.get("issues"),
                lobbying_activities=item.get("lobbying_activities") or item.get("activities"),
                committee_match=False,
                flagged=False,
            ))
            inserted += 1
        session.commit()
    finally:
        session.close()
    if inserted:
        print(f"[Lobbying] Inserted {inserted} filings.")
    return inserted
