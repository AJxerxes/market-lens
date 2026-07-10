"""
Market Lens — Leadership events from 8-K Item 5.02 (Phase 15).

Backfills and ongoing parsing of 8-K Item 5.02 (Departure/Election of directors
or principal officers). Classifies departure language into planned / abrupt / forced.
"""
import re
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from sqlalchemy.orm import Session

from market_lens.config import EDGAR_USER_AGENT, DATABASE_URL
from market_lens.database.models import (
    Company,
    TickerCikMap,
    LeadershipEvent,
    LeadershipVelocity,
    EventType,
    DepartureClassification,
)

SEC_DATA_BASE = "https://data.sec.gov"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions"


def _session_http() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = EDGAR_USER_AGENT
    return s


def _rate_limit():
    time.sleep(0.11)


def _cik_10(cik: Any) -> str:
    return str(cik).strip().zfill(10)


def _get_filing_url(cik: str, accession: str, primary_doc: str) -> str:
    acc = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{primary_doc}"


def _fetch_8k_text(session_http: requests.Session, cik: str, accession: str, primary_doc: str) -> Optional[str]:
    url = _get_filing_url(cik, accession, primary_doc)
    try:
        r = session_http.get(url, timeout=30)
        _rate_limit()
        if r.status_code != 200:
            return None
        return r.text
    except requests.RequestException:
        return None


# Item 5.02 section patterns
ITEM_502_HEADERS = re.compile(
    r"Item\s+5\.02\s*(?:\([^)]*\))?\s*[.\s]*"
    r"(?:Departure|Election|Appointment|Resignation|Election of Directors)?",
    re.IGNORECASE,
)
# Capture blocks that look like "On DATE, NAME, ROLE, resigned/retired/appointed..."
EVENT_BLOCK = re.compile(
    r"(?:on|effective)\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})"
    r"[^.]*?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*,?\s*"
    r"((?:Chief\s+)?(?:Executive|Financial|Operating|Accounting)\s+Officer|Director|President|COO|CEO|CFO)[^.]*?"
    r"(resigned|retired|departed|appointed|elected|terminated|removed|ceased)",
    re.IGNORECASE | re.DOTALL,
)


def _parse_item_502_section(text: str) -> List[Dict[str, Any]]:
    """Extract leadership change events from Item 5.02 section text."""
    events = []
    # Find Item 5.02; take text until next Item or end of doc
    start = ITEM_502_HEADERS.search(text)
    if not start:
        return events
    section = text[start.end() : start.end() + 8000]
    # Next Item
    next_item = re.search(r"\n\s*Item\s+\d+\.\d+", section, re.IGNORECASE)
    if next_item:
        section = section[: next_item.start()]

    for m in EVENT_BLOCK.finditer(section):
        event_date_str, name, role, action = m.group(1), m.group(2), m.group(3), m.group(4)
        name = name.strip()
        role = role.strip()
        if not name or len(name) > 200:
            continue
        try:
            if "/" in event_date_str:
                parts = event_date_str.replace(",", "").split("/")
                if len(parts) >= 3:
                    month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
                    if year < 100:
                        year += 2000
                    event_date = date(year, month, day)
                else:
                    event_date = date.today()
            else:
                # "September 15, 2024"
                from datetime import datetime as dt
                parsed = dt.strptime(re.sub(r",", "", event_date_str.strip()), "%B %d %Y")
                event_date = parsed.date()
        except Exception:
            event_date = date.today()

        action_lower = action.lower()
        if "resign" in action_lower or "retir" in action_lower or "depart" in action_lower or "ceased" in action_lower or "remov" in action_lower or "terminat" in action_lower:
            event_type = EventType.departed
        elif "appoint" in action_lower or "elect" in action_lower:
            event_type = EventType.appointed
        else:
            event_type = EventType.departed

        # Excerpt of surrounding text for departure language
        excerpt = section[max(0, m.start() - 50) : m.end() + 200]
        departure_lang = excerpt.strip()[:2000] if event_type == EventType.departed else None

        events.append({
            "person_name": name[:255],
            "role": role[:100],
            "event_type": event_type,
            "event_date": event_date,
            "departure_language": departure_lang,
        })
    return events


def classify_departure(departure_language: Optional[str]) -> DepartureClassification:
    """
    Classify departure into planned / abrupt / forced using keyword heuristics.
    """
    if not departure_language or not departure_language.strip():
        return DepartureClassification.abrupt
    text = departure_language.lower()
    # Forced
    if any(k in text for k in ("terminated", "removed", "for cause", "dismissed", "fired", "no longer serve")):
        return DepartureClassification.forced
    # Planned
    if any(k in text for k in ("retirement", "retire", "planned transition", "pursue other", "other opportunities", "resignation, effective", "notice")):
        return DepartureClassification.planned
    # Abrupt (resigned effective immediately, resigned, etc. without retirement/planned)
    return DepartureClassification.abrupt


def backfill_8k_item_502(
    session_orm: Session,
    session_http: requests.Session,
    ticker: str,
    cik: str,
    limit: int = 20,
) -> int:
    """
    Fetch recent 8-K filings for CIK, parse Item 5.02, upsert LeadershipEvent.
    Returns count of new events stored.
    """
    url = f"{SEC_DATA_BASE}/submissions/CIK{cik}.json"
    try:
        r = session_http.get(url, timeout=15)
        _rate_limit()
        if r.status_code != 200:
            return 0
        data = r.json()
    except requests.RequestException:
        return 0
    filings = data.get("filings", {}).get("recent", {})
    if not filings:
        return 0
    forms = filings.get("form") or []
    accessions = filings.get("accessionNumber") or []
    primary_docs = filings.get("primaryDocument") or []
    filing_dates = filings.get("filingDate") or []
    added = 0
    seen = 0
    for i, form in enumerate(forms):
        if form != "8-K":
            continue
        if seen >= limit:
            break
        seen += 1
        acc = accessions[i] if i < len(accessions) else None
        prim = primary_docs[i] if i < len(primary_docs) else "8k.htm"
        if not acc:
            continue
        text = _fetch_8k_text(session_http, cik, acc, prim)
        if not text:
            continue
        events = _parse_item_502_section(text)
        for ev in events:
            existing = session_orm.query(LeadershipEvent).filter_by(
                ticker=ticker,
                person_name=ev["person_name"],
                event_date=ev["event_date"],
                role=ev["role"],
            ).first()
            if existing:
                continue
            dep_lang = ev.get("departure_language")
            classified = classify_departure(dep_lang) if ev["event_type"] == EventType.departed else None
            session_orm.add(LeadershipEvent(
                ticker=ticker,
                person_name=ev["person_name"],
                role=ev["role"],
                event_type=ev["event_type"],
                event_date=ev["event_date"],
                tenure_days=None,
                departure_language=dep_lang,
                departure_language_classified=classified,
                equity_accelerated=False,
                source_filing=acc,
            ))
            added += 1
        session_orm.flush()
    return added


def update_velocity(session_orm: Session, ticker: str, role: str) -> None:
    """Update LeadershipVelocity for (ticker, role) from leadership_events."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    year_ago = (now - timedelta(days=365)).date()
    two_years_ago = (now - timedelta(days=730)).date()
    events_24mo = (
        session_orm.query(LeadershipEvent)
        .filter(
            LeadershipEvent.ticker == ticker,
            LeadershipEvent.role == role,
            LeadershipEvent.event_date >= two_years_ago,
        )
        .all()
    )
    change_12mo = sum(1 for e in events_24mo if e.event_date >= year_ago)
    change_24mo = len(events_24mo)
    avg_tenure_days = None
    existing_vel = (
        session_orm.query(LeadershipVelocity)
        .filter_by(ticker=ticker, role=role)
        .first()
    )
    if existing_vel:
        existing_vel.change_count_12mo = change_12mo
        existing_vel.change_count_24mo = change_24mo
        existing_vel.avg_tenure_days = avg_tenure_days
        existing_vel.instability_flag = change_12mo >= 2
        existing_vel.last_updated = now
    else:
        session_orm.add(LeadershipVelocity(
            ticker=ticker,
            role=role,
            change_count_12mo=change_12mo,
            change_count_24mo=change_24mo,
            avg_tenure_days=avg_tenure_days,
            instability_flag=change_12mo >= 2,
            last_updated=now,
        ))
    session_orm.flush()


def run_leadership_backfill(tickers: Optional[List[str]] = None) -> None:
    """Backfill 8-K Item 5.02 for watchlist (or given tickers)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session_orm = Session()
    session_http = _session_http()
    try:
        if tickers is None:
            companies = session_orm.query(Company).filter(Company.active == True).all()
            tickers = [c.ticker for c in companies]
        for ticker in tickers:
            row = session_orm.query(TickerCikMap).filter(TickerCikMap.ticker == ticker).first()
            cik = row.cik if row else None
            if not cik:
                continue
            cik = _cik_10(cik)
            n = backfill_8k_item_502(session_orm, session_http, ticker, cik, limit=15)
            if n > 0:
                for ev in session_orm.query(LeadershipEvent).filter_by(ticker=ticker).all():
                    update_velocity(session_orm, ticker, ev.role)
        session_orm.commit()
    except Exception:
        session_orm.rollback()
        raise
    finally:
        session_orm.close()
