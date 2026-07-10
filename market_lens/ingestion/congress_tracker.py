"""
Congressional trading tracker (Phase 19).

Responsibilities:
- Ingest House and Senate STOCK Act disclosures via FMP free API.
- Maintain `congress_members` and `congress_trades` tables.
- Pull committee assignments from Congress.gov API.
- Maintain `committee_sector_map` and `disclosure_timing_profile`.
- Monitor Congress.gov hearing schedule and populate `committee_hearings`.
- In a later phase, integrate LDA lobbying data (see LobbyingRegistration model).

This module focuses on data ingestion and persistence. Higher-level
reasoning and alerting is handled by the agent brain and notifier.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from market_lens import config
from market_lens.database.models import (
    CongressMember,
    CongressTrade,
    CommitteeSectorMap,
    DisclosureTimingProfile,
    CommitteeHearing,
    LobbyingRegistration,
    Company,
)


_engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=_engine)

CONGRESS_BASE_URL = "https://api.congress.gov/v3"
HOUSE_DISCLOSURE_BASE = "https://disclosures.house.gov"
HOUSE_DISCLOSURE_SEARCH = "https://disclosures.house.gov/FinancialDisclosure/ViewMemberSearchResult"
# GitHub raw JSON — direct parses of official disclosure PDFs (no API, no rate limits)
SENATE_GITHUB_DATA_BASE = "https://raw.githubusercontent.com/timothycarambat/senate-stock-watcher-data/master/data"
HOUSE_GITHUB_RAW_URL = "https://raw.githubusercontent.com/jldec/house-stock-watcher-data/main/data/all_transactions.json"
USER_AGENT = "MarketLens/1.0 (compliance; omniaj@aol.com)"


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _get_session() -> Session:
    return SessionLocal()


# ---------------------------------------------------------------------------
# House Clerk & Senate eFD Search — official government disclosure sources (no FMP)
# ---------------------------------------------------------------------------


def _http_get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> Optional[requests.Response]:
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    try:
        resp = requests.get(url, params=params, headers=h, timeout=30)
        return resp if resp.status_code == 200 else None
    except requests.exceptions.Timeout:
        print(f"[TIMEOUT] Request to {url} timed out after 30 seconds")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Request to {url} failed: {e}")
        return None


def _parse_house_xml_for_trades(xml_text: str, member_name: str) -> List[Dict[str, Any]]:
    """Parse House disclosure XML and return list of trade dicts."""
    trades: List[Dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return trades
    # Common House PTR XML: transactions in various namespaces or under Transaction
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag in ("Transaction", "transaction", "Asset", "asset"):
            rec: Dict[str, Any] = {
                "member_name": member_name,
                "ticker": "",
                "company_name": "",
                "transaction_type": "",
                "amount_low": None,
                "amount_high": None,
                "transaction_date": None,
                "disclosure_date": None,
            }
            for child in elem.iter():
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                text = (child.text or "").strip()
                if ctag in ("TickerSymbol", "ticker", "Symbol"):
                    rec["ticker"] = text.upper()
                elif ctag in ("AssetName", "assetName", "CompanyName", "SecurityName"):
                    rec["company_name"] = rec["company_name"] or text
                elif ctag in ("TransactionType", "type", "TransactionTypeCode"):
                    rec["transaction_type"] = text.lower()
                elif ctag in ("Amount", "amount") and text:
                    try:
                        val = float(re.sub(r"[^\d.-]", "", text))
                        if rec["amount_low"] is None:
                            rec["amount_low"] = val
                        rec["amount_high"] = val
                    except ValueError:
                        pass
                elif ctag in ("TransactionDate", "transactionDate", "TransDate"):
                    rec["transaction_date"] = text[:10] if len(text) >= 10 else None
                elif ctag in ("DisclosureDate", "disclosureDate", "ReportDate"):
                    rec["disclosure_date"] = text[:10] if len(text) >= 10 else None
            if rec["ticker"] or rec["company_name"] or rec["transaction_type"]:
                trades.append(rec)
    # Fallback: look for any elements that might hold ticker/amount/date
    if not trades and "transaction" in xml_text.lower():
        # Try regex fallback for non-standard XML
        pass
    return trades


def _get_or_create_member(session: Session, member_id: str, name: str, chamber: str) -> CongressMember:
    """Ensure a CongressMember row exists for the given identifier."""
    if not member_id:
        return None
    member = session.query(CongressMember).filter_by(member_id=member_id).first()
    if not member:
        member = CongressMember(
            member_id=member_id,
            name=name or member_id,
            chamber=chamber,
        )
        session.add(member)
        session.flush()
    return member


def _ensure_or_create_member(
    session: Session, name: str, chamber: str, bioguide: str = ""
) -> CongressMember:
    """Ensure a CongressMember exists; use bioguide as member_id when provided."""
    member_id = (bioguide or name or "").strip() or "Unknown"
    return _get_or_create_member(session, member_id=member_id, name=name or member_id, chamber=chamber)


def _parse_house_github_record(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map House GitHub JSON record to trade fields. Returns None if missing ticker or date."""
    ticker = (rec.get("ticker") or rec.get("symbol") or "").strip().replace(" ", "")
    if not ticker or ticker in ("--", ""):
        return None
    trans_date = rec.get("transaction_date") or rec.get("disclosure_date") or rec.get("date") or ""
    disclosure_date = rec.get("disclosure_date") or rec.get("transaction_date") or rec.get("filing_date") or trans_date
    trade_date = _safe_date(trans_date) or _parse_senate_date(trans_date)
    if not trade_date:
        return None
    member = (rec.get("representative") or rec.get("member_name") or rec.get("name") or "").strip() or "Unknown"
    trans_type = (rec.get("type") or rec.get("transaction_type") or "disclosure").strip().lower()
    return {
        "member_name": member,
        "ticker": ticker,
        "company_name": (rec.get("asset_description") or rec.get("company") or rec.get("asset") or "").strip() or ticker,
        "transaction_type": trans_type or "disclosure",
        "transaction_date": trans_date,
        "disclosure_date": disclosure_date,
        "trade_date": trade_date,
        "disclosure_d": _safe_date(disclosure_date) or _parse_senate_date(disclosure_date) or trade_date,
    }


def ingest_house_disclosures(limit: int = 500) -> None:
    """
    Ingest House STOCK Act disclosures. Tries GitHub raw JSON first (jldec/house-stock-watcher-data);
    on 404 or parse failure falls back to House Clerk disclosure portal scraping.
    Dedup on member + ticker + transaction_date + type. Filter last 90 days, skip missing tickers.
    """
    today = _utc_today()
    cutoff = today - timedelta(days=90)
    headers = {"User-Agent": USER_AGENT}
    session = _get_session()
    inserted = 0

    try:
        resp = requests.get(HOUSE_GITHUB_RAW_URL, headers=headers, timeout=15)
        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                data = None
            if isinstance(data, list) and len(data) > 0:
                for rec in data:
                    if not isinstance(rec, dict):
                        continue
                    row = _parse_house_github_record(rec)
                    if not row or row["trade_date"] < cutoff:
                        continue
                    trade_id = f"house_gh_{row['member_name']}_{row['ticker']}_{row['trade_date'].isoformat()}_{row['transaction_type']}".replace(" ", "_")
                    if session.query(CongressTrade).filter_by(trade_id=trade_id).first():
                        continue
                    _get_or_create_member(session, member_id=row["member_name"], name=row["member_name"], chamber="house")
                    session.add(CongressTrade(
                        trade_id=trade_id,
                        member_id=row["member_name"],
                        ticker=row["ticker"],
                        company_name=row["company_name"],
                        sector=None,
                        transaction_type=row["transaction_type"][:50],
                        amount_range_low=None,
                        amount_range_high=None,
                        trade_date=row["trade_date"],
                        disclosure_date=row["disclosure_d"],
                        days_to_disclose=(row["disclosure_d"] - row["trade_date"]).days if row["disclosure_d"] and row["trade_date"] else None,
                        committee_correlated=False,
                        matching_committees=None,
                        cluster_flag=False,
                        source="house_github",
                    ))
                    inserted += 1
                    if inserted >= limit:
                        break
                session.commit()
                if inserted:
                    print(f"[Congress] House: inserted {inserted} trades (GitHub).")
                return
            # else: not a list or empty — fall through to Clerk
        # GitHub 404 or bad response — fall back to House Clerk
        _ingest_house_disclosures_clerk(session, limit, cutoff)
    finally:
        session.close()


def _ingest_house_disclosures_clerk(session: Session, limit: int, cutoff: Optional[date] = None) -> None:
    """Fallback: ingest House PTR via House Clerk disclosure portal (scrape + XML parse)."""
    resp = _http_get(HOUSE_DISCLOSURE_SEARCH)
    if not resp or not resp.text:
        print("[Congress] House disclosure search page not available (check URL/User-Agent).")
        return

    soup = BeautifulSoup(resp.text, "lxml")
    links: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = (a.get_text() or "").strip()
        if "PTR" in text.upper() or "periodic" in text.lower():
            full_url = urljoin(HOUSE_DISCLOSURE_BASE, href)
            if full_url not in links and (".xml" in full_url or "ViewDocument" in full_url or "FinancialDisclosure" in full_url):
                links.append(full_url)
    for row in soup.find_all("tr"):
        if "PTR" not in (row.get_text() or "").upper():
            continue
        for a in row.find_all("a", href=True):
            full_url = urljoin(HOUSE_DISCLOSURE_BASE, a["href"])
            if full_url not in links:
                links.append(full_url)

    links = links[:limit]
    if not links:
        print("[Congress] No House PTR disclosure links found on search page.")
        return

    inserted = 0
    for doc_url in links:
        member_name = "Unknown"
        doc_resp = _http_get(doc_url)
        if not doc_resp or not doc_resp.text:
            continue
        if "<?xml" in doc_resp.text or "<Transaction" in doc_resp.text or "<transaction" in doc_resp.text:
            xml_text = doc_resp.text
        else:
            soup_d = BeautifulSoup(doc_resp.text, "lxml")
            for h in soup_d.find_all(["h1", "h2", "span", "div"]):
                t = (h.get_text() or "").strip()
                if t and len(t) < 100 and ("Representative" in t or "Member" in t):
                    member_name = re.sub(r"Representative|Member|Congress", "", t, flags=re.I).strip() or "Unknown"
                    break
            xml_link = soup_d.find("a", href=re.compile(r"\.xml$", re.I))
            if not xml_link or not xml_link.get("href"):
                continue
            xml_url = urljoin(doc_url, xml_link["href"])
            xml_resp = _http_get(xml_url)
            if not xml_resp or not xml_resp.text:
                continue
            xml_text = xml_resp.text

        trades = _parse_house_xml_for_trades(xml_text, member_name or "Unknown")
        for item in trades:
            trade_date = _safe_date(item.get("transaction_date"))
            if cutoff and trade_date and trade_date < cutoff:
                continue
            trade_id = f"house_{member_name}_{item.get('ticker','')}_{item.get('transaction_date','')}_{item.get('disclosure_date','')}".replace(" ", "_")
            if not trade_id or trade_id == "house_Unknown__":
                trade_id = f"house_{doc_url}_{inserted}"
            if session.query(CongressTrade).filter_by(trade_id=trade_id).first():
                continue
            member_name = (item.get("member_name") or "Unknown").strip()
            _get_or_create_member(session, member_id=member_name, name=member_name, chamber="house")
            session.add(CongressTrade(
                trade_id=trade_id,
                member_id=member_name,
                ticker=item.get("ticker") or "",
                company_name=item.get("company_name") or "",
                sector=None,
                transaction_type=(item.get("transaction_type") or "").lower() or "unknown",
                amount_range_low=item.get("amount_low"),
                amount_range_high=item.get("amount_high"),
                trade_date=_safe_date(item.get("transaction_date")),
                disclosure_date=_safe_date(item.get("disclosure_date")),
                days_to_disclose=_compute_days_to_disclose(item.get("transaction_date"), item.get("disclosure_date")),
                committee_correlated=False,
                matching_committees=None,
                cluster_flag=False,
                source="house_clerk",
            ))
            inserted += 1
    session.commit()
    if inserted:
        print(f"[Congress] House: inserted {inserted} trades (Clerk fallback).")


def _parse_senate_date(s: str) -> Optional[date]:
    """Parse MM/DD/YYYY from Senate GitHub JSON."""
    if not s or len(s) < 10:
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%m/%d/%Y").date()
    except ValueError:
        return None


def ingest_senate_disclosures(limit: int = 10000) -> None:
    """
    Pull Senate STOCK Act disclosures from timothycarambat/senate-stock-watcher-data.
    Constructs per-date URLs directly — no GitHub API directory listing.
    URL pattern: .../data/transaction_report_for_{MM}_{DD}_{YYYY}.json
    """
    base_url = f"{SENATE_GITHUB_DATA_BASE}/transaction_report_for_{{month}}_{{day}}_{{year}}.json"
    headers = {"User-Agent": USER_AGENT}

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=90)
    cutoff = start_date.date()

    inserted = 0
    skipped = 0
    files_found = 0
    files_missing = 0

    session = _get_session()
    try:
        current = start_date
        while current <= end_date:
            month = current.strftime("%m")
            day = current.strftime("%d")
            year = current.strftime("%Y")
            url = base_url.format(month=month, day=day, year=year)

            try:
                resp = requests.get(url, headers=headers, timeout=15)

                if resp.status_code == 404:
                    files_missing += 1
                    current += timedelta(days=1)
                    continue

                if resp.status_code != 200:
                    print(f"[Senate] Unexpected status {resp.status_code} for {url}")
                    current += timedelta(days=1)
                    continue

                try:
                    senators = resp.json()
                except Exception:
                    current += timedelta(days=1)
                    continue

                if not isinstance(senators, list):
                    current += timedelta(days=1)
                    continue

                files_found += 1
                file_date = current.date()

                for senator in senators:
                    if not isinstance(senator, dict):
                        continue
                    first = (senator.get("first_name") or "").strip()
                    last = (senator.get("last_name") or "").strip()
                    member_name = f"{first} {last}".strip() or "Unknown"
                    bioguide = (senator.get("bioguide") or "").strip()
                    date_received = senator.get("date_recieved") or ""
                    disclosure_d = _parse_senate_date(date_received) or file_date

                    for t in senator.get("transactions") or []:
                        if not isinstance(t, dict):
                            continue
                        try:
                            ticker = (t.get("ticker") or "").strip().replace(" ", "").upper()
                            if not ticker or ticker in ("--", "N/A", ""):
                                skipped += 1
                                continue

                            raw_date = t.get("transaction_date") or ""
                            if not raw_date:
                                skipped += 1
                                continue

                            trade_date = None
                            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
                                try:
                                    trade_date = datetime.strptime(raw_date[:10], fmt).date()
                                    break
                                except ValueError:
                                    continue
                            if not trade_date or trade_date < cutoff:
                                skipped += 1
                                continue

                            transaction_type = (t.get("type") or "unknown").strip()[:50]
                            member = _ensure_or_create_member(
                                session=session,
                                name=member_name,
                                chamber="senate",
                                bioguide=bioguide,
                            )
                            member_id = member.member_id

                            existing = session.query(CongressTrade).filter_by(
                                member_id=member_id,
                                ticker=ticker,
                                trade_date=trade_date,
                                transaction_type=transaction_type,
                            ).first()
                            if existing:
                                skipped += 1
                                continue

                            trade_id = f"senate_gh_{member_id}_{ticker}_{trade_date.isoformat()}_{transaction_type}".replace(" ", "_")
                            session.add(CongressTrade(
                                trade_id=trade_id,
                                member_id=member_id,
                                ticker=ticker,
                                company_name=(t.get("asset_description") or "").strip() or ticker,
                                sector=None,
                                transaction_type=transaction_type,
                                amount_range_low=None,
                                amount_range_high=None,
                                trade_date=trade_date,
                                disclosure_date=disclosure_d,
                                days_to_disclose=(disclosure_d - trade_date).days if disclosure_d and trade_date else None,
                                committee_correlated=False,
                                matching_committees=None,
                                cluster_flag=False,
                                source="senate_github",
                            ))
                            inserted += 1

                        except Exception as e:
                            print(f"[Senate] Transaction error: {e} — {t}")
                            skipped += 1

            except Exception as e:
                print(f"[Senate] File error for {current.date()}: {e}")

            current += timedelta(days=1)

        session.commit()
    finally:
        session.close()

    print(f"[Senate] Files found: {files_found} | Files missing (normal): {files_missing}")
    print(f"[Senate] Inserted: {inserted} | Skipped: {skipped}")


# ---------------------------------------------------------------------------
# House Clerk lobbying via Azure Elastic (confirmed working)
# ---------------------------------------------------------------------------

LOBBYING_AZURE_URL = "https://app-pub-pri-elastic.azurewebsites.net/search"
LOBBYING_AZURE_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://disclosures.house.gov",
    "Referer": "https://disclosures.house.gov/",
    "User-Agent": USER_AGENT,
}


def ingest_lobbying_registrations() -> None:
    """
    Pull lobbying disclosure registrations via House Clerk Azure Elastic endpoint.
    Confirmed working: POST https://app-pub-pri-elastic.azurewebsites.net/search
    index: lobbying-disclosures
    """
    current_year = datetime.now(timezone.utc).year
    inserted = 0
    skipped = 0
    page_num = 0
    page_size = 100

    while True:
        payload = {
            "index": "lobbying-disclosures",
            "size": page_size,
            "from": page_num * page_size,
        }

        try:
            resp = requests.post(LOBBYING_AZURE_URL, json=payload, headers=LOBBYING_AZURE_HEADERS, timeout=30)
            print(f"[Lobbying] Page {page_num} status: {resp.status_code}")

            if resp.status_code != 200:
                print(f"[Lobbying] Failed: {resp.text[:200]}")
                break

            data = resp.json()
            hits = data.get("filteredHits", [])
            total = data.get("hitsTotal", 0)
            print(f"[Lobbying] Page {page_num}: {len(hits)} records (total: {total})")

            if not hits:
                break

            session = _get_session()
            try:
                for hit in hits:
                    try:
                        # Support both flat hit and _source-wrapped response
                        src = hit.get("_source") or hit
                        filing_id = str(hit.get("_id") or "")
                        registration_id = filing_id or ""
                        registrant_name = (src.get("registrantName") or (src.get("registrant") or {}).get("name") or (src.get("registrant") or {}).get("organizationName") or "").strip()
                        client_name = (src.get("clientName") or (src.get("client") or {}).get("name") or "").strip()
                        report_type = src.get("reportType", "")
                        if isinstance(report_type, dict):
                            report_type_str = report_type.get("description", "") or report_type.get("name", "") or ""
                        else:
                            report_type_str = str(report_type or "")
                        report_year = src.get("reportYear", current_year)
                        senate_id = str(src.get("senateId") or "")
                        lobbyist_names = src.get("lobbyistNames") or src.get("lobbyists") or []
                        if not isinstance(lobbyist_names, list):
                            lobbyist_names = [str(lobbyist_names)] if lobbyist_names else []

                        if not registrant_name or not client_name:
                            skipped += 1
                            continue

                        if not registration_id:
                            skipped += 1
                            continue

                        existing = session.query(LobbyingRegistration).filter_by(
                            registration_id=registration_id
                        ).first()

                        if existing:
                            skipped += 1
                            continue

                        report_year_int = int(report_year) if str(report_year).isdigit() else current_year
                        filing_date_val = date(report_year_int, 1, 1)
                        reg = LobbyingRegistration(
                            registration_id=registration_id,
                            filing_id=filing_id,
                            registrant_name=registrant_name,
                            client_name=client_name,
                            filing_date=filing_date_val,
                            covered_officials=None,
                            sector_keywords=None,
                            lobbying_activities={"report_type": report_type_str, "lobbyist_names": lobbyist_names},
                            committee_match=False,
                            flagged=False,
                            senate_id=senate_id or None,
                            source="house_clerk_elastic"
                        )
                        session.add(reg)
                        inserted += 1

                    except Exception as e:
                        print(f"[Lobbying] Row error: {hit.get('_id', 'unknown')} — {e}")
                        skipped += 1
                        continue

                session.commit()
                print(f"[Lobbying] Page {page_num} committed — running total inserted: {inserted}")

            finally:
                session.close()

            if (page_num + 1) * page_size >= total:
                break

            page_num += 1

        except Exception as e:
            print(f"[Lobbying] Request error: {e}")
            break

    print(f"[Lobbying] Complete — Inserted: {inserted} | Skipped: {skipped}")


def _safe_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except Exception:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except Exception:
            return None


def _compute_days_to_disclose(trade_date_str: Optional[str], disclosure_date_str: Optional[str]) -> Optional[int]:
    trade_d = _safe_date(trade_date_str)
    disc_d = _safe_date(disclosure_date_str)
    if not trade_d or not disc_d:
        return None
    return (disc_d - trade_d).days


# ---------------------------------------------------------------------------
# Congress.gov committee assignments & hearings
# ---------------------------------------------------------------------------


def _congress_get(path: str, params: Optional[dict] = None) -> Optional[dict]:
    if not config.CONGRESS_API_KEY:
        return None
    if params is None:
        params = {}
    params.setdefault("api_key", config.CONGRESS_API_KEY)
    url = f"{CONGRESS_BASE_URL}{path}"
    try:
        resp = requests.get(url, params=params, timeout=30)
    except requests.exceptions.Timeout:
        print(f"[TIMEOUT] Congress.gov request to {url} timed out after 30 seconds — skipping")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Congress.gov request to {url} failed: {e}")
        return None
    if resp.status_code != 200:
        print(f"[ERROR] Congress.gov {url} returned status {resp.status_code}")
        return None
    try:
        return resp.json()
    except Exception as e:
        print(f"[ERROR] Congress.gov JSON parse failed for {url}: {e}")
        return None


def update_member_committees(bioguide_ids: Iterable[str]) -> None:
    """
    For each member (identified by bioguideId), fetch the current
    committee assignments and update `congress_members.committees`.
    """
    session = _get_session()
    try:
        for bioguide_id in bioguide_ids:
            data = _congress_get(f"/member/{bioguide_id}/committee-assignment")
            if not data:
                continue

            committees = []
            assignments = data.get("committeeAssignments") or []
            for a in assignments:
                name = a.get("name")
                if name:
                    committees.append(name)

            member = (
                session.query(CongressMember)
                .filter_by(member_id=bioguide_id)
                .first()
            )
            if not member:
                # Create a placeholder member row if none exists yet
                member = CongressMember(
                    member_id=bioguide_id,
                    name=bioguide_id,
                    chamber=None,
                )
                session.add(member)

            member.committees = committees

        session.commit()
    finally:
        session.close()


# Sectors we care about — mapped from committee names for hearing relevance
_COMMITTEE_SECTOR_MAP = {
    "intelligence": ["cybersecurity", "AI", "defense"],
    "armed services": ["defense", "cybersecurity"],
    "commerce": ["technology", "telecom", "AI"],
    "banking": ["financials", "fintech"],
    "finance": ["financials", "tax"],
    "judiciary": ["antitrust", "technology"],
    "energy": ["energy", "utilities"],
    "transportation": ["automotive", "logistics"],
    "homeland security": ["cybersecurity", "defense"],
    "science": ["technology", "AI", "research"],
}


def update_hearing_schedule(congress_number: int = 119, chamber: Optional[str] = None) -> None:
    """
    Pull upcoming committee hearings from Congress.gov API v3 committee-meeting endpoint.
    Stores ALL hearings; relevant_sectors set to matched sectors or empty list for non-matching.
    """
    if not config.CONGRESS_API_KEY:
        print("[Hearings] CONGRESS_API_KEY not set — skipping.")
        return

    base = f"{CONGRESS_BASE_URL}/committee-meeting"
    headers = {"User-Agent": USER_AGENT}
    params_base = {"api_key": config.CONGRESS_API_KEY, "limit": 250, "format": "json"}

    chambers = [chamber] if chamber else ["house", "senate"]
    inserted = 0
    skipped = 0

    session = _get_session()
    try:
        for ch in chambers:
            url = f"{base}/{congress_number}/{ch}"
            try:
                resp = requests.get(url, headers=headers, params=params_base, timeout=30)
                print(f"[Hearings] {ch} status: {resp.status_code}")

                if resp.status_code != 200:
                    print(f"[Hearings] {ch} failed: {resp.text[:200]}")
                    continue

                data = resp.json()
                meetings = data.get("committeeMeetings") or []
                print(f"[Hearings] {ch} meetings returned: {len(meetings)}")

                for m in meetings:
                    try:
                        event_date_raw = m.get("date") or m.get("meetingDate") or ""
                        if not event_date_raw:
                            skipped += 1
                            continue

                        event_date = datetime.strptime(event_date_raw[:10], "%Y-%m-%d")
                        event_date = event_date.replace(tzinfo=timezone.utc)

                        title = m.get("title") or m.get("description") or ""
                        committees = m.get("committees") or []
                        committee_name = committees[0].get("name", "") if committees else m.get("committeeName") or ""

                        relevant_sectors = []
                        for keyword, sectors in _COMMITTEE_SECTOR_MAP.items():
                            if keyword.lower() in committee_name.lower() or keyword.lower() in (title or "").lower():
                                relevant_sectors.extend(sectors)
                        relevant_sectors = list(set(relevant_sectors))  # store all hearings; empty list if no match

                        hearing_id = str(m.get("eventId") or m.get("meetingId") or "")
                        if not hearing_id:
                            hearing_id = f"{ch}_{event_date_raw[:10]}_{(title or '')[:40]}".replace(" ", "_")

                        existing = (
                            session.query(CommitteeHearing)
                            .filter_by(hearing_id=hearing_id)
                            .first()
                        )
                        if existing:
                            skipped += 1
                            continue

                        hearing = CommitteeHearing(
                            hearing_id=hearing_id,
                            committee_name=committee_name,
                            chamber=ch,
                            hearing_date=event_date,
                            subject=title,
                            hearing_title=title,
                            topic_keywords=None,
                            sector_relevance={"source": "congress.gov"} if relevant_sectors else None,
                            relevant_sectors=relevant_sectors,
                            relevant_watchlist_tickers=None,
                            member_watch_window_triggered=False,
                            alerted=False,
                        )
                        session.add(hearing)
                        inserted += 1

                    except Exception as e:
                        print(f"[Hearings] Row error: {e}")
                        skipped += 1
                        continue

            except Exception as e:
                print(f"[Hearings] {ch} request failed: {e}")

        session.commit()
        print(f"[Hearings] Inserted: {inserted}, Skipped: {skipped}")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Congressional intelligence aggregates for dashboard
# ---------------------------------------------------------------------------


def compute_recent_trading_activity(window_days: int = 60) -> dict:
    """
    Aggregate congressional trades over the last `window_days` into:
    - active_sectors: sectors with 3+ trades
    - cluster_trades: tickers with 2+ trades by different members
    """
    today = _utc_today()
    cutoff = today - timedelta(days=window_days)
    session = _get_session()
    try:
        rows = (
            session.query(CongressTrade, Company.sector)
            .outerjoin(Company, CongressTrade.ticker == Company.ticker)
            .filter(CongressTrade.trade_date.isnot(None))
            .filter(CongressTrade.trade_date >= cutoff)
            .all()
        )
        total_trades = len(rows)
        if not rows:
            return {
                "window_start": cutoff,
                "window_end": today,
                "total_trades": 0,
                "active_sectors": [],
                "cluster_trades": [],
            }

        sector_counts: dict = {}
        ticker_members: dict = {}
        ticker_trade_counts: dict = {}

        for trade, company_sector in rows:
            sector = trade.sector or company_sector or "Unknown"
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

            ticker = (trade.ticker or "").strip()
            if ticker:
                ticker_trade_counts[ticker] = ticker_trade_counts.get(ticker, 0) + 1
                members = ticker_members.setdefault(ticker, set())
                if trade.member_id:
                    members.add(trade.member_id)

        active_sectors = [
            {"sector": sector, "trade_count": count}
            for sector, count in sector_counts.items()
            if sector != "Unknown" and count >= 3
        ]
        active_sectors.sort(key=lambda x: x["trade_count"], reverse=True)

        cluster_trades = []
        for ticker, members in ticker_members.items():
            trade_count = ticker_trade_counts.get(ticker, 0)
            if trade_count >= 2 and len(members) >= 2:
                cluster_trades.append(
                    {
                        "ticker": ticker,
                        "trade_count": trade_count,
                        "unique_members": len(members),
                    }
                )
        cluster_trades.sort(key=lambda x: x["trade_count"], reverse=True)

        return {
            "window_start": cutoff,
            "window_end": today,
            "total_trades": total_trades,
            "active_sectors": active_sectors,
            "cluster_trades": cluster_trades,
        }
    finally:
        session.close()


def get_congress_hearing_timeline(
    recent_days: int = 30, upcoming_days: int = 30
) -> dict:
    """
    Return upcoming and recent hearings with basic metadata and
    whether there is any associated lobbying activity in the same sectors.
    """
    today = _utc_today()
    recent_cutoff = today - timedelta(days=recent_days)
    upcoming_cutoff = today + timedelta(days=upcoming_days)

    session = _get_session()
    try:
        # Map sectors with any lobbying filings in the recent window
        lobbying_rows = (
            session.query(LobbyingRegistration)
            .filter(LobbyingRegistration.filing_date >= recent_cutoff)
            .all()
        )
        lobbying_sectors: set = set()
        for reg in lobbying_rows:
            for kw in (reg.sector_keywords or []):
                lobbying_sectors.add(kw)

        hearings = session.query(CommitteeHearing).all()
        upcoming = []
        recent = []
        for h in hearings:
            h_date = h.hearing_date.date() if hasattr(h.hearing_date, "date") else h.hearing_date
            sectors = h.relevant_sectors or []
            lobby_flag = any(s in lobbying_sectors for s in sectors)
            entry = {
                "date": h_date.isoformat(),
                "committee": h.committee_name,
                "chamber": h.chamber,
                "subject": h.subject or h.hearing_title or "",
                "sectors": sectors,
                "lobbyist_activity_flag": lobby_flag,
            }
            if h_date >= today and h_date <= upcoming_cutoff:
                upcoming.append(entry)
            elif h_date < today and h_date >= recent_cutoff:
                recent.append(entry)

        upcoming.sort(key=lambda x: x["date"])
        recent.sort(key=lambda x: x["date"], reverse=True)

        return {
            "today": today,
            "recent_cutoff": recent_cutoff,
            "upcoming_cutoff": upcoming_cutoff,
            "upcoming_hearings": upcoming,
            "recent_hearings": recent,
            "has_lobbying_data": bool(lobbying_rows),
        }
    finally:
        session.close()


def compute_convergence_signals(window_days: int = 30) -> dict:
    """
    Compute convergence signals where, for a given sector:
    - There are trades in the last `window_days`
    - There are hearings touching that sector
    - There are lobbying registrations in that sector
    """
    today = _utc_today()
    cutoff = today - timedelta(days=window_days)
    session = _get_session()
    try:
        # Trades per sector
        trade_rows = (
            session.query(CongressTrade, Company.sector)
            .outerjoin(Company, CongressTrade.ticker == Company.ticker)
            .filter(CongressTrade.trade_date.isnot(None))
            .filter(CongressTrade.trade_date >= cutoff)
            .all()
        )
        sector_trade_counts: dict = {}
        for trade, company_sector in trade_rows:
            sector = trade.sector or company_sector or "Unknown"
            if sector == "Unknown":
                continue
            sector_trade_counts[sector] = sector_trade_counts.get(sector, 0) + 1

        # Hearings per sector
        hearings = (
            session.query(CommitteeHearing)
            .filter(CommitteeHearing.hearing_date >= datetime.combine(cutoff, datetime.min.time()).replace(tzinfo=timezone.utc))
            .all()
        )
        sector_hearing_counts: dict = {}
        for h in hearings:
            for sec in (h.relevant_sectors or []):
                sector_hearing_counts[sec] = sector_hearing_counts.get(sec, 0) + 1

        # Lobbying per sector
        lobbying = (
            session.query(LobbyingRegistration)
            .filter(LobbyingRegistration.filing_date >= cutoff)
            .all()
        )
        sector_lobby_counts: dict = {}
        for reg in lobbying:
            for sec in (reg.sector_keywords or []):
                sector_lobby_counts[sec] = sector_lobby_counts.get(sec, 0) + 1

        convergences = []
        for sector, trade_count in sector_trade_counts.items():
            hearings_count = sector_hearing_counts.get(sector, 0)
            lobby_count = sector_lobby_counts.get(sector, 0)
            if trade_count > 0 and hearings_count > 0 and lobby_count > 0:
                convergences.append(
                    {
                        "sector": sector,
                        "company": None,  # sector-level convergence for now
                        "trade_count": trade_count,
                        "hearings_count": hearings_count,
                        "filings_count": lobby_count,
                    }
                )
        convergences.sort(key=lambda x: x["trade_count"], reverse=True)

        return {
            "window_start": cutoff,
            "window_end": today,
            "convergences": convergences,
            "has_lobbying_data": bool(lobbying),
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Disclosure timing profiles
# ---------------------------------------------------------------------------


def recompute_disclosure_timing_profiles() -> None:
    """
    Recompute average / stddev / min / max disclosure lags
    for each member and update `disclosure_timing_profile`.
    """
    session = _get_session()
    try:
        members = session.query(CongressMember).all()
        for member in members:
            trades = (
                session.query(CongressTrade)
                .filter(CongressTrade.member_id == member.member_id)
                .filter(CongressTrade.days_to_disclose.isnot(None))
                .all()
            )
            if not trades:
                continue

            lags = [t.days_to_disclose for t in trades if t.days_to_disclose is not None]
            if not lags:
                continue

            avg_lag = sum(lags) / len(lags)
            min_lag = min(lags)
            max_lag = max(lags)
            # Simple proxy for stddev to avoid pulling in numpy here
            variance = sum((x - avg_lag) ** 2 for x in lags) / len(lags)
            stddev = variance ** 0.5

            profile = (
                session.query(DisclosureTimingProfile)
                .filter_by(member_id=member.member_id)
                .first()
            )
            if not profile:
                profile = DisclosureTimingProfile(member_id=member.member_id)
                session.add(profile)

            profile.avg_days_to_disclose = avg_lag
            profile.stddev_days = stddev
            profile.min_days = min_lag
            profile.max_days = max_lag
            profile.last_30day_silence_flag = False  # To be set in a separate job
            profile.last_updated = datetime.now(timezone.utc)

        session.commit()
    finally:
        session.close()


def mark_silence_flags(window_days: int = 30) -> None:
    """
    Mark members as `last_30day_silence_flag=True` when they
    normally disclose quickly but have gone silent for the
    specified window.
    """
    cutoff = _utc_today() - timedelta(days=window_days)
    session = _get_session()
    try:
        profiles = session.query(DisclosureTimingProfile).all()
        for profile in profiles:
            member = (
                session.query(CongressMember)
                .filter_by(member_id=profile.member_id)
                .first()
            )
            if not member:
                continue

            last_trade = (
                session.query(CongressTrade)
                .filter(CongressTrade.member_id == profile.member_id)
                .order_by(CongressTrade.disclosure_date.desc())
                .first()
            )
            if not last_trade or not last_trade.disclosure_date:
                continue

            # If member typically files quickly but last disclosure is old, flag.
            if (
                profile.avg_days_to_disclose is not None
                and profile.avg_days_to_disclose <= 10
                and last_trade.disclosure_date < cutoff
            ):
                profile.last_30day_silence_flag = True
            else:
                profile.last_30day_silence_flag = False

        session.commit()
    finally:
        session.close()


def seed_committee_sector_map() -> None:
    """Seed committee_sector_map with common committees and GICS sector jurisdictions."""
    session = _get_session()
    try:
        defaults = [
            ("House Financial Services Committee", "house", ["Financials"]),
            ("Senate Banking Committee", "senate", ["Financials"]),
            ("House Energy and Commerce Committee", "house", ["Energy", "Health Care", "Communication Services"]),
            ("Senate Health, Education, Labor, and Pensions Committee", "senate", ["Health Care", "Consumer Discretionary"]),
            ("House Ways and Means Committee", "house", ["Financials", "Consumer Staples", "Industrials"]),
            # Additional high-signal committees for sector correlation
            ("Senate Armed Services Committee", "senate", ["Industrials", "Energy"]),
            ("House Permanent Select Committee on Intelligence", "house", ["Information Technology", "Communication Services"]),
            ("Senate Select Committee on Intelligence", "senate", ["Information Technology", "Communication Services"]),
            ("Senate Commerce, Science, and Transportation Committee", "senate", ["Information Technology", "Communication Services", "Industrials"]),
            ("House Transportation and Infrastructure Committee", "house", ["Industrials"]),
        ]
        for name, chamber, sectors in defaults:
            existing = session.query(CommitteeSectorMap).filter_by(committee_name=name).first()
            if not existing:
                session.add(CommitteeSectorMap(committee_name=name, chamber=chamber, jurisdiction_sectors=sectors))
        session.commit()
    finally:
        session.close()


# NOTE: cluster-trade detection and cross-signal reasoning between hearings,
# options, and price moves are handled in delta.py and the agent brain.


if __name__ == "__main__":
    print("Market Lens — Congress Tracker")
    print("------------------------------")
    ingest_house_disclosures(limit=500)
    ingest_senate_disclosures(limit=500)
    seed_committee_sector_map()
    print("[OK] Congress ingestion done.")
