"""
Market Lens — Court docket ingestion (Phase 13).

- CourtListener v4: search by party name (company/legal name). Token required.
- USPTO PTAB v3: api.data.gov/USPTO/PTAB/v3/ for patent trial proceedings.
- PACER: never called on a schedule; only when a case has pacer_needed=True
  (manual flag). This module does not invoke PACER automatically.
"""
from datetime import date
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy.orm import Session

from market_lens.config import COURTLISTENER_TOKEN, USPTO_API_KEY
from market_lens.database.models import CourtCase

COURTLISTENER_BASE = "https://www.courtlistener.com/api/rest/v4"
USPTO_PTAB_BASE = "https://api.data.gov/USPTO/PTAB/v3"


def _courtlistener_headers() -> Dict[str, str]:
    h = {"Accept": "application/json"}
    if COURTLISTENER_TOKEN:
        h["Authorization"] = f"Token {COURTLISTENER_TOKEN}"
    return h


def _uspto_headers() -> Dict[str, str]:
    h = {"Accept": "application/json"}
    if USPTO_API_KEY:
        h["X-Api-Key"] = USPTO_API_KEY
    return h


def search_courtlistener(party_name: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Search CourtListener v4 for dockets/opinions by party name.
    Returns list of result items (simplified). Requires COURTLISTENER_TOKEN for full access.
    """
    if not party_name or not party_name.strip():
        return []
    results: List[Dict[str, Any]] = []
    # Search endpoint: /search/ with q= or dockets with party filter
    url = f"{COURTLISTENER_BASE}/search/"
    params = {"q": party_name.strip(), "type": "d", "court": ""}  # d = docket
    try:
        r = requests.get(url, params=params, headers=_courtlistener_headers(), timeout=30)
        if r.status_code == 401:
            return []  # Token missing or invalid
        r.raise_for_status()
        data = r.json()
        for obj in data.get("results", [])[:limit]:
            results.append({
                "case_number": obj.get("docket_number") or obj.get("case_name_full") or "",
                "court": obj.get("court") or "",
                "filed_date": obj.get("date_filed"),
                "plaintiff": obj.get("parties", [""])[0] if obj.get("parties") else "",
                "defendant": party_name,
                "case_type": obj.get("nature_of_suit", {}).get("description", "") if isinstance(obj.get("nature_of_suit"), dict) else str(obj.get("nature_of_suit", "")),
                "summary": (obj.get("case_name") or obj.get("case_name_full") or "")[:500],
                "source": "courtlistener",
            })
    except requests.RequestException:
        pass
    return results


def search_uspto_ptab(company_name: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Search USPTO PTAB v3 (api.data.gov) for patent trial proceedings by party name.
    Returns list of proceeding summaries. Uses USPTO_API_KEY (api.data.gov key).
    """
    if not company_name or not company_name.strip():
        return []
    results: List[Dict[str, Any]] = []
    # PTAB proceedings search - endpoint may be /proceedings or /search
    url = f"{USPTO_PTAB_BASE}/proceedings"
    params = {"party_name": company_name.strip(), "limit": limit}
    if USPTO_API_KEY:
        params["api_key"] = USPTO_API_KEY  # api.data.gov uses query param
    try:
        r = requests.get(url, params=params, headers=_uspto_headers(), timeout=30)
        if r.status_code in (401, 403):
            return []
        r.raise_for_status()
        data = r.json()
        items = data if isinstance(data, list) else data.get("results", data.get("data", []))
        for obj in (items or [])[:limit]:
            if isinstance(obj, dict):
                results.append({
                    "case_number": obj.get("proceeding_number") or obj.get("trial_number") or "",
                    "court": "USPTO PTAB",
                    "filed_date": obj.get("filing_date") or obj.get("institution_date"),
                    "plaintiff": obj.get("petitioner") or company_name,
                    "defendant": obj.get("patent_owner") or "",
                    "case_type": obj.get("proceeding_type") or "PTAB",
                    "summary": str(obj.get("patent_number", ""))[:200],
                    "source": "uspto_ptab",
                })
    except requests.RequestException:
        pass
    return results


def upsert_court_cases(
    session: Session,
    ticker: str,
    party_name: str,
    from_courtlistener: bool = True,
    from_ptab: bool = True,
) -> int:
    """
    Search CourtListener (and optionally PTAB), upsert into court_cases.
    Does NOT call PACER. Returns count of new/updated cases stored.
    """
    added = 0
    if from_courtlistener and COURTLISTENER_TOKEN:
        for item in search_courtlistener(party_name, limit=15):
            case_number = (item.get("case_number") or "").strip()
            if not case_number:
                continue
            existing = session.query(CourtCase).filter_by(case_number=case_number).first()
            if not existing:
                filed = item.get("filed_date")
                if isinstance(filed, str) and len(filed) >= 10:
                    try:
                        filed_date = date.fromisoformat(filed[:10])
                    except ValueError:
                        filed_date = None
                else:
                    filed_date = None
                session.add(CourtCase(
                    ticker=ticker,
                    case_number=case_number,
                    court=item.get("court") or "",
                    filed_date=filed_date,
                    plaintiff=(item.get("plaintiff") or "")[:500],
                    defendant=(item.get("defendant") or "")[:500],
                    case_type=(item.get("case_type") or "")[:100],
                    summary=(item.get("summary") or "")[:2000],
                    source=item.get("source") or "courtlistener",
                    pacer_needed=False,
                ))
                added += 1
        session.flush()

    if from_ptab and USPTO_API_KEY:
        for item in search_uspto_ptab(party_name, limit=10):
            case_number = (item.get("case_number") or "").strip()
            if not case_number:
                continue
            existing = session.query(CourtCase).filter_by(case_number=case_number).first()
            if not existing:
                filed = item.get("filed_date")
                if isinstance(filed, str) and len(filed) >= 10:
                    try:
                        filed_date = date.fromisoformat(filed[:10])
                    except ValueError:
                        filed_date = None
                else:
                    filed_date = None
                session.add(CourtCase(
                    ticker=ticker,
                    case_number=case_number,
                    court=item.get("court") or "USPTO PTAB",
                    filed_date=filed_date,
                    plaintiff=(item.get("plaintiff") or "")[:500],
                    defendant=(item.get("defendant") or "")[:500],
                    case_type=(item.get("case_type") or "")[:100],
                    summary=(item.get("summary") or "")[:2000],
                    source=item.get("source") or "uspto_ptab",
                    pacer_needed=False,
                ))
                added += 1
        session.flush()
    return added


def run_pacer_for_case_if_needed(session: Session, case_id: int) -> bool:
    """
    If the case has pacer_needed=True, this is the hook for a manual or
    scheduled PACER fetch. We do NOT call PACER on a schedule; only when
    explicitly requested for a case marked pacer_needed.
    Returns True if a fetch was attempted (caller can implement actual PACER call).
    """
    case = session.query(CourtCase).filter_by(id=case_id).first()
    if not case or not case.pacer_needed:
        return False
    # Stub: actual PACER integration would go here (e.g. RECAP or PACER API).
    # Per project rules: PACER only when pacer_needed is set manually.
    return False
