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
SENATE_EFTS_SEARCH = "https://efts.senate.gov/LATEST/search-index"
USER_AGENT = "MarketLens/1.0 (compliance; omniaj@aol.com)"

# House & Senate committee system codes to human-readable names
COMMITTEE_SYSTEM_CODE_MAP = {
    # House committees
    "hsag00": "House Committee on Agriculture",
    "hsap00": "House Committee on Appropriations",
    "hsas00": "House Committee on Armed Services",
    "hsba00": "House Committee on Financial Services",
    "hsbu00": "House Committee on the Budget",
    "hsed00": "House Committee on Education and the Workforce",
    "hseg00": "House Committee on Energy and Commerce",
    "hsfa00": "House Committee on Foreign Affairs",
    "hsha00": "House Committee on Homeland Security",
    "hshm00": "House Committee on House Administration",
    "hsii00": "House Committee on Natural Resources",
    "hsii13": "House Subcommittee on Federal Lands",
    "hsif00": "House Committee on Infrastructure and Transportation",
    "hlig00": "House Permanent Select Committee on Intelligence",
    "hsjp00": "House Committee on the Judiciary",
    "hsog00": "House Committee on Oversight and Accountability",
    "hsru00": "House Committee on Rules",
    "hssm00": "House Committee on Small Business",
    "hspw00": "House Committee on Transportation and Infrastructure",
    "hsvr00": "House Committee on Veterans' Affairs",
    "hswm00": "House Committee on Ways and Means",
    "hsso00": "House Committee on Science, Space, and Technology",
    # Senate committees
    "ssaf00": "Senate Committee on Agriculture, Nutrition, and Forestry",
    "ssap00": "Senate Committee on Appropriations",
    "ssas00": "Senate Committee on Armed Services",
    "ssbk00": "Senate Committee on Banking, Housing, and Urban Affairs",
    "ssbu00": "Senate Committee on the Budget",
    "sscm00": "Senate Committee on Commerce, Science, and Transportation",
    "sseg00": "Senate Committee on Energy and Natural Resources",
    "ssev00": "Senate Committee on Environment and Public Works",
    "ssfi00": "Senate Committee on Finance",
    "ssfr00": "Senate Committee on Foreign Relations",
    "ssgov": "Senate Committee on Homeland Security and Governmental Affairs",
    "sshr00": "Senate Committee on Health, Education, Labor, and Pensions",
    "ssju00": "Senate Committee on the Judiciary",
    "ssra00": "Senate Committee on Rules and Administration",
    "sssb00": "Senate Committee on Small Business and Entrepreneurship",
    "ssva00": "Senate Committee on Veterans' Affairs",
}

# House Clerk lobbying via Azure Elastic
LOBBYING_AZURE_URL = "https://app-pub-pri-elastic.azurewebsites.net/search"
LOBBYING_AZURE_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://disclosures.house.gov",
    "Referer": "https://disclosures.house.gov/",
    "User-Agent": USER_AGENT,
}


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _get_session() -> Session:
    return SessionLocal()


# ---------------------------------------------------------------------------
# House Clerk & Senate EFTS — official government disclosure sources (no FMP)
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


def ingest_house_disclosures(limit: int = 500) -> None:
    """
    House STOCK Act PTR and financial disclosures via yearly zip files.

    Confirmed working zip URLs:
    - https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip

    Zip contains {year}FD.xml with <FinancialDisclosure><Member> elements.
    Each Member has: First, Last, FilingType, StateDst, Year, FilingDate, DocID.
    FilingType P = Periodic Transaction Report (PTR) — stock trades.
    DocID builds PDF URL: public_disc/ptr-pdfs/{year}/{DocID}.pdf

    We store all PTR filings (FilingType=P) as CongressTrade records.
    Individual PDF parsing for ticker extraction is a future enhancement.
    """
    import requests
    import zipfile
    import io
    from xml.etree import ElementTree as ET

    base_url = "https://disclosures-clerk.house.gov"
    headers = {
        "User-Agent": USER_AGENT
    }

    current_year = datetime.now(timezone.utc).year
    years_to_fetch = [current_year, current_year - 1]

    inserted = 0
    skipped = 0

    for year in years_to_fetch:
        zip_url = f"{base_url}/public_disc/financial-pdfs/{year}FD.zip"
        print(f"[House] Fetching {year} zip: {zip_url}")

        try:
            resp = requests.get(zip_url, headers=headers, timeout=30)
            print(f"[House] {year} zip status: {resp.status_code} | {len(resp.content)} bytes")

            if resp.status_code != 200:
                print(f"[House] {year} zip not available — skipping")
                continue

            z = zipfile.ZipFile(io.BytesIO(resp.content))
            xml_files = [n for n in z.namelist() if n.lower().endswith(".xml")]

            if not xml_files:
                print(f"[House] {year} zip has no XML files")
                continue

            xml_content = z.read(xml_files[0]).decode("utf-8", errors="replace")
            root = ET.fromstring(xml_content)
            members = root.findall("Member")
            print(f"[House] {year}: {len(members)} member records in XML")

            session = _get_session()
            try:
                for member in members:
                    try:
                        filing_type = (member.findtext("FilingType") or "").strip()

                        # Only process PTR filings (P = Periodic Transaction Report)
                        if filing_type != "P":
                            skipped += 1
                            continue

                        first = (member.findtext("First") or "").strip()
                        last = (member.findtext("Last") or "").strip()
                        member_name = f"{first} {last}".strip()
                        state_dst = (member.findtext("StateDst") or "").strip()
                        filing_date_str = (member.findtext("FilingDate") or "").strip()
                        doc_id = (member.findtext("DocID") or "").strip()
                        filing_year = (member.findtext("Year") or str(year)).strip()

                        if not member_name or not doc_id:
                            skipped += 1
                            continue

                        # Parse filing date
                        filing_date = None
                        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                            try:
                                filing_date = datetime.strptime(filing_date_str, fmt).date()
                                break
                            except ValueError:
                                continue

                        if not filing_date:
                            skipped += 1
                            continue

                        # Build PDF URL for this PTR
                        pdf_url = f"{base_url}/public_disc/ptr-pdfs/{filing_year}/{doc_id}.pdf"

                        # Deterministic trade ID for dedup
                        trade_id = f"house_ptr_{filing_year}_{doc_id}"

                        # Check existing
                        existing = (
                            session.query(CongressTrade)
                            .filter_by(trade_id=trade_id)
                            .first()
                        )
                        if existing:
                            skipped += 1
                            continue

                        # Ensure or create member by name (no stable member_id in FD XML)
                        member_row = (
                            session.query(CongressMember)
                            .filter_by(name=member_name, chamber="house")
                            .first()
                        )
                        if not member_row:
                            synthetic_id = f"house_name::{member_name}"
                            member_row = CongressMember(
                                member_id=synthetic_id,
                                name=member_name,
                                chamber="house",
                            )
                            session.add(member_row)
                            session.flush()

                        trade = CongressTrade(
                            trade_id=trade_id,
                            member_id=member_row.member_id,
                            ticker="PTR_PENDING",
                            company_name=f"House PTR — {pdf_url}",
                            sector=None,
                            transaction_type="disclosure",
                            amount_range_low=None,
                            amount_range_high=None,
                            trade_date=filing_date,
                            disclosure_date=filing_date,
                            days_to_disclose=0,
                            committee_correlated=False,
                            matching_committees=None,
                            cluster_flag=False,
                            source="house_fd_zip",
                        )
                        session.add(trade)
                        inserted += 1

                    except Exception as e:
                        print(f"[House] Member parse error: {e}")
                        skipped += 1
                        continue

                session.commit()
                print(f"[House] {year} committed — inserted so far: {inserted}")
            finally:
                session.close()

        except Exception as e:
            print(f"[House] {year} failed: {e}")
            continue

    print(f"[House] Complete — Inserted: {inserted} | Skipped: {skipped}")


def _normalize_house_search_name(raw_name: str) -> str:
    """
    The search results table renders names as "Last, Hon.. First Middle."
    while the zip XML gives separate First/Last fields (no title). Normalize
    to "First Middle Last" so both ingestion paths land on the same
    CongressMember row instead of creating look-alike duplicates.
    """
    name = raw_name.replace("Hon..", "").strip()
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first.strip()} {last.strip()}"
    return re.sub(r"\s+", " ", name).strip().rstrip(".")


def ingest_house_ptr_search() -> None:
    """
    Near-real-time House PTR filings via the Financial Disclosure Search tool,
    as an improvement over waiting for the annual zip (ingest_house_disclosures)
    to be regenerated. Meant to run every 30 minutes from the scheduler.

    The search form's LastName field is marked required client-side, but the
    server doesn't enforce it — an empty LastName + a FilingYear returns every
    filing for that year in one request, no per-member enumeration needed.
    Confirmed live: an empty search returned all ~389 filings for the current
    year in a single POST.

    ponytail: the results table has no filing-date column (only Name, Office,
    Filing Year, Filing type), so newly-discovered rows here are stamped with
    today's date as an approximation rather than the real filing date. Uses
    the same trade_id scheme as ingest_house_disclosures(), so once the
    annual zip catches up it will see the row already exists and skip it —
    the approximate date is never corrected. Upgrade path: open the PTR PDF
    (like Form 4 does for EDGAR) to read the real filing date, if the
    approximate date ever proves too imprecise for signal timing.
    """
    base_url = "https://disclosures-clerk.house.gov"
    headers = {"User-Agent": USER_AGENT}
    today = _utc_today()
    inserted = 0
    skipped = 0

    session_http = requests.Session()
    session_http.headers.update(headers)

    for year in (today.year, today.year - 1):
        try:
            r = session_http.get(f"{base_url}/FinancialDisclosure/ViewSearch", timeout=30)
            if r.status_code != 200:
                print(f"[House PTR search] {year}: ViewSearch page returned {r.status_code} — skipping")
                continue
            token_el = BeautifulSoup(r.text, "html.parser").find(
                "input", {"name": "__RequestVerificationToken"}
            )
            if not token_el or not token_el.get("value"):
                print(f"[House PTR search] {year}: no CSRF token found — site structure may have changed")
                continue
            token = token_el["value"]

            resp = session_http.post(
                f"{base_url}/FinancialDisclosure/ViewMemberSearchResult",
                data={
                    "LastName": "",
                    "FilingYear": str(year),
                    "State": "",
                    "District": "",
                    "__RequestVerificationToken": token,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"[House PTR search] {year}: search POST returned {resp.status_code} — skipping")
                continue

            rows = BeautifulSoup(resp.text, "html.parser").select("tbody tr")
            if not rows:
                print(f"[House PTR search] {year}: 0 rows returned")
                continue

            session_orm = _get_session()
            try:
                for row in rows:
                    try:
                        cells = row.find_all("td")
                        if len(cells) < 4:
                            skipped += 1
                            continue
                        filing_type = cells[3].get_text(strip=True)
                        if "PTR" not in filing_type:
                            skipped += 1
                            continue

                        name_link = cells[0].find("a")
                        if not name_link or not name_link.get("href"):
                            skipped += 1
                            continue
                        member_name = _normalize_house_search_name(name_link.get_text())
                        pdf_href = name_link["href"]
                        doc_id_match = re.search(r"/(\d+)\.pdf", pdf_href)
                        if not member_name or not doc_id_match:
                            skipped += 1
                            continue
                        doc_id = doc_id_match.group(1)

                        trade_id = f"house_ptr_{year}_{doc_id}"
                        existing = (
                            session_orm.query(CongressTrade).filter_by(trade_id=trade_id).first()
                        )
                        if existing:
                            skipped += 1
                            continue

                        pdf_url = f"{base_url}/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"

                        member_row = (
                            session_orm.query(CongressMember)
                            .filter_by(name=member_name, chamber="house")
                            .first()
                        )
                        if not member_row:
                            member_row = CongressMember(
                                member_id=f"house_name::{member_name}",
                                name=member_name,
                                chamber="house",
                            )
                            session_orm.add(member_row)
                            session_orm.flush()

                        session_orm.add(
                            CongressTrade(
                                trade_id=trade_id,
                                member_id=member_row.member_id,
                                ticker="PTR_PENDING",
                                company_name=f"House PTR — {pdf_url}",
                                transaction_type="disclosure",
                                trade_date=today,
                                disclosure_date=today,
                                days_to_disclose=0,
                                committee_correlated=False,
                                cluster_flag=False,
                                source="house_ptr_search",
                            )
                        )
                        inserted += 1
                    except Exception as e:
                        print(f"[House PTR search] Row error: {e}")
                        skipped += 1
                        continue

                session_orm.commit()
            finally:
                session_orm.close()

            _rate_limit_house_search()
        except Exception as e:
            print(f"[House PTR search] {year} failed: {type(e).__name__}: {e}")
            continue

    print(f"[House PTR search] Complete — Inserted: {inserted} | Skipped: {skipped}")


def _rate_limit_house_search():
    import time
    time.sleep(0.5)


def _ingest_house_from_zip(year: int) -> None:
    """
    Diagnostic helper: download House annual PTR ZIP(s) and print basic info.

    URL patterns (subject to change):
    - PTR ZIP: https://disclosures.house.gov/public_disc/ptr-pdfs/{year}PTR.zip
    - Financial disclosure ZIP: https://disclosures.house.gov/public_disc/financial-pdfs/{year}FD.zip
    """
    import io
    import zipfile

    ptr_url = f"https://disclosures.house.gov/public_disc/ptr-pdfs/{year}PTR.zip"
    fd_url = f"https://disclosures.house.gov/public_disc/financial-pdfs/{year}FD.zip"

    for url in (ptr_url, fd_url):
        print(f"[House ZIP] Trying: {url}")
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
            print(f"[House ZIP] Status: {resp.status_code}, size={len(resp.content)} bytes")
            if resp.status_code == 200 and len(resp.content) > 1024:
                try:
                    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                        names = zf.namelist()
                        print(f"[House ZIP] Files in ZIP (first 10): {names[:10]}")
                except Exception as e:
                    print(f"[House ZIP] Failed to read ZIP from {url}: {e}")
                # For now, stop after first successful ZIP; parsing can be added later.
                return
        except Exception as e:
            print(f"[House ZIP] Request failed for {url}: {e}")

    print("[House ZIP] All ZIP attempts failed.")


def ingest_senate_disclosures():
    """
    Senate PTR disclosures via Playwright (real browser).
    Server blocks requests-based calls to /search/report/data/ — Playwright bypasses this.
    """
    import asyncio
    from playwright.async_api import async_playwright
    import re
    from datetime import datetime, timedelta
    from market_lens.database.models import CongressTrade, CongressMember

    base_url = "https://efdsearch.senate.gov"
    inserted = 0
    skipped = 0
    captured_batches = []

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            # Intercept all responses from the data endpoint
            async def handle_response(response):
                if "search/report/data" in response.url:
                    try:
                        body = await response.json()
                        rows = body.get("data", [])
                        total = body.get("recordsFiltered", 0)
                        print(f"[Senate] Captured batch: {len(rows)} rows | total: {total}")
                        captured_batches.append({"rows": rows, "total": total})
                    except Exception as e:
                        print(f"[Senate] Response parse error: {e}")

            page.on("response", handle_response)

            # Step 1 — consent
            print("[Senate] Loading consent page...")
            resp = await page.goto(f"{base_url}/search/home/", timeout=30000)
            await page.wait_for_timeout(2000)

            # The site (Akamai-fronted) can flat-out block the request before any
            # HTML we care about loads — e.g. an IP/ASN-level block on a
            # datacenter or cloud egress IP, which looks nothing like normal
            # anti-bot friction. Fail loudly here instead of silently limping
            # through the rest of the flow and reporting a vague "no data" at
            # the end, which is indistinguishable from "genuinely no filings".
            if resp is not None and resp.status >= 400:
                body_snippet = (await page.content())[:300]
                print(f"[Senate] Blocked loading consent page: HTTP {resp.status}. Body: {body_snippet}")
                await browser.close()
                return

            checkbox_found = await page.evaluate("""
                () => {
                    const cb = document.querySelector('input[type="checkbox"]');
                    if (cb) {
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'checked'
                        ).set;
                        setter.call(cb, true);
                        cb.dispatchEvent(new Event('change', {bubbles: true}));
                        cb.dispatchEvent(new Event('click', {bubbles: true}));
                        return true;
                    }
                    return false;
                }
            """)
            if not checkbox_found:
                title = await page.title()
                print(f"[Senate] No consent checkbox found on page (title: {title!r}) — site structure may have changed, or the page didn't render.")
                await browser.close()
                return
            await page.wait_for_timeout(1000)

            await page.evaluate("""
                () => {
                    const btns = Array.from(document.querySelectorAll('button, input[type=submit]'));
                    const btn = btns.find(b =>
                        (b.textContent || b.value || '').toLowerCase().includes('agree') ||
                        (b.textContent || b.value || '').toLowerCase().includes('submit') ||
                        (b.textContent || b.value || '').toLowerCase().includes('i agree')
                    );
                    if (btn) btn.click();
                }
            """)
            await page.wait_for_load_state("networkidle", timeout=15000)
            await page.wait_for_timeout(2000)
            print(f"[Senate] After consent: {page.url}")

            # Consent should land on the actual search form; if the PTR
            # filter checkboxes aren't there, everything downstream will
            # silently no-op the same way the missing-checkbox case above did.
            has_search_form = await page.evaluate(
                "() => document.querySelectorAll('input[name=\\'report_type\\']').length > 0"
            )
            if not has_search_form:
                title = await page.title()
                print(f"[Senate] Consent did not reach the search form (title: {title!r}, url: {page.url}) — report_type filter not found.")
                await browser.close()
                return

            # Step 2 — set PTR filter and date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=90)
            start_str = start_date.strftime("%m/%d/%Y")
            end_str = end_date.strftime("%m/%d/%Y")

            await page.evaluate(f"""
                () => {{
                    // Check PTR checkbox (value=11)
                    document.querySelectorAll('input[name="report_type"]').forEach(cb => {{
                        cb.checked = cb.value === '11';
                        cb.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }});

                    // Set date range
                    const setVal = (sel, val) => {{
                        const el = document.querySelector(sel);
                        if (el) {{
                            const setter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value'
                            ).set;
                            setter.call(el, val);
                            el.dispatchEvent(new Event('input', {{bubbles: true}}));
                            el.dispatchEvent(new Event('change', {{bubbles: true}}));
                        }}
                    }};
                    setVal('input[name="submitted_start_date"]', '{start_str}');
                    setVal('input[name="submitted_end_date"]', '{end_str}');
                }}
            """)
            await page.wait_for_timeout(1000)

            # Step 3 — click Search Reports
            await page.evaluate("""
                () => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    const btn = btns.find(b => b.textContent.trim().includes('Search Reports'));
                    if (btn) btn.click();
                }
            """)
            await page.wait_for_load_state("networkidle", timeout=20000)
            await page.wait_for_timeout(3000)

            print(f"[Senate] Search triggered. Batches captured so far: {len(captured_batches)}")

            # Step 4 — paginate through results by clicking Next
            # DataTables pagination fires new /search/report/data/ requests automatically
            page_num = 1
            while True:
                if not captured_batches:
                    print("[Senate] No data captured on this page")
                    break

                last_batch = captured_batches[-1]
                total = last_batch.get("total", 0)
                rows_so_far = sum(len(b["rows"]) for b in captured_batches)

                print(f"[Senate] Page {page_num}: rows so far {rows_so_far} / {total}")

                if rows_so_far >= int(total):
                    break

                # Click Next button
                next_clicked = await page.evaluate("""
                    () => {
                        const next = document.querySelector('#fdsearch_next, .next, [id*="next"]');
                        if (next && !next.classList.contains('disabled')) {
                            next.click();
                            return true;
                        }
                        return false;
                    }
                """)

                if not next_clicked:
                    print("[Senate] No Next button or pagination complete")
                    break

                await page.wait_for_load_state("networkidle", timeout=15000)
                await page.wait_for_timeout(2000)
                page_num += 1

                if page_num > 50:  # Safety limit
                    break

            await browser.close()

    # Run the async function
    asyncio.run(_run())

    print(f"[Senate] Total batches captured: {len(captured_batches)}")

    if not captured_batches:
        print("[Senate] No data captured — server may still be blocking or no PTR filings in range")
        return

    # Insert captured rows into database
    all_rows = []
    for batch in captured_batches:
        all_rows.extend(batch["rows"])

    print(f"[Senate] Processing {len(all_rows)} total rows...")

    db_session = _get_session()
    try:
        for row in all_rows:
            try:
                if len(row) < 5:
                    skipped += 1
                    continue

                first_name = str(row[0]).strip() if row[0] else ""
                last_name = str(row[1]).strip() if row[1] else ""
                member_name = f"{first_name} {last_name}".strip()
                report_html = str(row[3]) if row[3] else ""
                date_str = str(row[4]).strip() if row[4] else ""

                url_match = re.search(r'href=["\']([^"\']+)["\']', report_html)
                report_path = url_match.group(1) if url_match else ""
                filing_id = report_path.strip("/").split("/")[-1] if report_path else ""

                if not filing_id or not member_name:
                    skipped += 1
                    continue

                disclosure_date = None
                for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                    try:
                        disclosure_date = datetime.strptime(date_str[:10], fmt)
                        break
                    except ValueError:
                        continue

                if not disclosure_date:
                    skipped += 1
                    continue

                trade_id = f"senate_efdsearch_{filing_id}"

                existing = db_session.query(CongressTrade).filter_by(
                    trade_id=trade_id
                ).first()
                if existing:
                    skipped += 1
                    continue

                member_row = db_session.query(CongressMember).filter_by(
                    name=member_name, chamber="senate"
                ).first()
                if not member_row:
                    member_row = CongressMember(
                        member_id=f"senate_name::{member_name}",
                        name=member_name,
                        chamber="senate"
                    )
                    db_session.add(member_row)
                    db_session.flush()

                trade = CongressTrade(
                    trade_id=trade_id,
                    member_id=member_row.member_id,
                    ticker="PTR_PENDING",
                    company_name=f"Senate PTR — {base_url}{report_path}",
                    transaction_type="disclosure",
                    trade_date=disclosure_date.date(),
                    disclosure_date=disclosure_date.date(),
                    days_to_disclose=0,
                    committee_correlated=False,
                    cluster_flag=False,
                    source="senate_efdsearch"
                )
                db_session.add(trade)
                inserted += 1

            except Exception as e:
                print(f"[Senate] Row error: {e}")
                skipped += 1
                continue

        db_session.commit()
    finally:
        db_session.close()

    print(f"[Senate] Complete — Inserted: {inserted} | Skipped: {skipped}")


def ingest_lobbying_registrations() -> None:
    """
    Pull lobbying disclosure registrations via House Clerk Azure Elastic endpoint.
    Confirmed working: POST https://app-pub-pri-elastic.azurewebsites.net/search
    index: lobbying-disclosures. Filters to last 2 years and stops when pages are all old.
    """
    import requests

    current_year = datetime.now(timezone.utc).year
    inserted = 0
    skipped = 0
    page_num = 0
    page_size = 100
    consecutive_old_pages = 0

    # Prefer sort by signedDate (exact submission time); API may 400 — fallback to reportYear for all pages.
    sort_signed = [{"field": "signedDate", "order": "desc"}]
    sort_report_year = [{"field": "reportYear", "order": "desc"}]
    sort_to_use = sort_signed

    while True:
        payload = {
            "index": "lobbying-disclosures",
            "size": page_size,
            "from": page_num * page_size,
            "sort": sort_to_use,
        }

        try:
            resp = requests.post(LOBBYING_AZURE_URL, json=payload, headers=LOBBYING_AZURE_HEADERS, timeout=30)
            if resp.status_code == 400 and sort_to_use == sort_signed:
                sort_to_use = sort_report_year
                payload["sort"] = sort_report_year
                resp = requests.post(LOBBYING_AZURE_URL, json=payload, headers=LOBBYING_AZURE_HEADERS, timeout=30)
                if resp.status_code == 200:
                    print("[Lobbying] signedDate sort not supported; using reportYear sort")
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

            old_count_this_page = 0

            session = _get_session()
            try:
                for hit in hits:
                    try:
                        filing_id = str(hit.get("_id", ""))
                        registration_id = filing_id

                        if not filing_id:
                            skipped += 1
                            continue

                        source = hit.get("_source", {})

                        # Registrant name
                        registrant = source.get("registrant", {})
                        registrant_name = (
                            registrant.get("name")
                            or registrant.get("organizationName")
                            or f"{registrant.get('firstName', '')} {registrant.get('lastName', '')}".strip()
                        ).strip()

                        # Client name
                        client = source.get("client", {})
                        client_name = (client.get("name") or "").strip()

                        # Report type
                        report_type_obj = source.get("reportType", {})
                        if isinstance(report_type_obj, dict):
                            report_type_str = report_type_obj.get("description") or report_type_obj.get("name") or ""
                        else:
                            report_type_str = str(report_type_obj)

                        # 2-year cutoff and filing_date from signedDate (exact submission time)
                        signed_date_str = source.get("signedDate", "")
                        filing_date_val = None

                        if signed_date_str:
                            try:
                                signed_dt = datetime.fromisoformat(
                                    signed_date_str.replace("Z", "+00:00")
                                )
                                cutoff = datetime.now(timezone.utc) - timedelta(days=730)
                                if signed_dt < cutoff:
                                    old_count_this_page += 1
                                    skipped += 1
                                    continue
                                filing_date_val = signed_dt.date()
                            except Exception:
                                pass

                        if filing_date_val is None:
                            # Fallback to reportYear
                            report_year = source.get("reportYear", str(current_year))
                            report_year_int = int(report_year) if str(report_year).isdigit() else 0
                            if report_year_int < current_year - 1:
                                old_count_this_page += 1
                                skipped += 1
                                continue
                            filing_date_val = date(report_year_int, 1, 1)

                        # Senate ID
                        senate_id = source.get("senateId", "")

                        # Lobbyists
                        lobbyists = source.get("lobbyists", [])
                        lobbyist_names = ", ".join(
                            [
                                l.get("fullName")
                                or f"{l.get('firstName', '')} {l.get('lastName', '')}".strip()
                                for l in lobbyists
                                if isinstance(l, dict)
                            ]
                        )

                        # Issue areas as sector keywords (JSON list)
                        issue_areas = source.get("issueAreaCodes", [])
                        sector_keywords = [
                            i.get("description", "")
                            for i in issue_areas
                            if isinstance(i, dict) and i.get("description")
                        ]

                        if not registrant_name or not client_name:
                            skipped += 1
                            continue

                        existing = (
                            session.query(LobbyingRegistration)
                            .filter_by(registration_id=registration_id)
                            .first()
                        )
                        if existing:
                            skipped += 1
                            continue

                        reg = LobbyingRegistration(
                            registration_id=registration_id,
                            registrant_name=registrant_name,
                            client_name=client_name,
                            filing_date=filing_date_val,
                            covered_officials=None,
                            sector_keywords=sector_keywords or None,
                            lobbying_activities={
                                "report_type": report_type_str,
                                "lobbyist_names": lobbyist_names,
                                "senate_id": senate_id,
                                "source": "house_clerk_elastic",
                            },
                            committee_match=False,
                            flagged=False,
                        )
                        session.add(reg)
                        inserted += 1
                    except Exception as e:
                        print(f"[Lobbying] Row error: {hit.get('_id', 'unknown')} — {e}")
                        skipped += 1
                        continue

                session.commit()
                print(f"[Lobbying] Page {page_num} committed - running total inserted: {inserted}")
            finally:
                session.close()

            if old_count_this_page == len(hits):
                consecutive_old_pages += 1
                print(
                    f"[Lobbying] All records on page {page_num} are older than {current_year - 1} "
                    f"(consecutive old pages: {consecutive_old_pages})"
                )
            else:
                consecutive_old_pages = 0

            if consecutive_old_pages >= 3:
                print(
                    f"[Lobbying] Reached {consecutive_old_pages} consecutive old pages - stopping pagination at page {page_num}"
                )
                break

            if (page_num + 1) * page_size >= (total or 0):
                break

            page_num += 1

        except Exception as e:
            print(f"[Lobbying] Request error: {e}")
            break

    print(f"[Lobbying] Complete - Inserted: {inserted} | Skipped: {skipped}")


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


def update_hearing_schedule(
    congress_number: int, chamber: str = "house"
) -> None:
    import time

    path = f"/committee-meeting/{congress_number}/{chamber}"
    data = _congress_get(path)
    if not data:
        print(f"[Hearings] No data from Congress.gov for {chamber}")
        return

    session = _get_session()
    try:
        meetings = data.get("committeeMeetings") or []
        print(f"[Hearings] {chamber}: {len(meetings)} meetings from list endpoint")
        inserted = 0
        updated = 0

        for m in meetings:
            hearing_id = str(m.get("eventId") or m.get("meetingId") or "")
            if not hearing_id:
                continue

            detail_url = m.get("url", "")
            src = {}
            if detail_url:
                try:
                    detail_path = detail_url.split("/v3")[-1].split("?")[0]
                    detail_data = _congress_get(detail_path)
                    if detail_data:
                        src = detail_data.get("committeeMeeting", {})
                except Exception as e:
                    print(f"[Hearings] Detail fetch error for {hearing_id}: {e}")
                time.sleep(0.3)

            # Extract committee name from systemCode lookup
            committee_name = ""
            committees = src.get("committees", [])
            if committees and isinstance(committees, list):
                system_code = committees[0].get("systemCode", "")
                committee_name = COMMITTEE_SYSTEM_CODE_MAP.get(system_code, system_code)

            # Extract title — confirmed field is 'title' in detail response
            hearing_title = (src.get("title") or "").strip().strip('"')
            subject = hearing_title

            # Extract date — confirmed field is 'date' in detail response
            dt_str = src.get("date") or src.get("meetingDate") or m.get("updateDate")
            hearing_dt = None
            if dt_str:
                try:
                    hearing_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                except Exception:
                    hearing_dt = None

            existing = (
                session.query(CommitteeHearing)
                .filter_by(hearing_id=hearing_id)
                .first()
            )

            if existing:
                if not existing.committee_name and committee_name:
                    existing.committee_name = committee_name
                if not existing.hearing_title and hearing_title:
                    existing.hearing_title = hearing_title
                if not existing.subject and subject:
                    existing.subject = subject
                if hearing_dt and (not existing.hearing_date or existing.hearing_date == existing.created_at):
                    existing.hearing_date = hearing_dt
                updated += 1
            else:
                relevant_sectors = None
                cm = (
                    session.query(CommitteeSectorMap)
                    .filter_by(committee_name=committee_name)
                    .first()
                )
                if cm and cm.jurisdiction_sectors:
                    relevant_sectors = cm.jurisdiction_sectors

                hearing = CommitteeHearing(
                    hearing_id=hearing_id,
                    committee_name=committee_name,
                    chamber=chamber,
                    hearing_date=hearing_dt or datetime.now(timezone.utc),
                    subject=subject,
                    hearing_title=hearing_title,
                    topic_keywords=None,
                    sector_relevance={"source": "committee_sector_map"} if relevant_sectors else None,
                    relevant_sectors=relevant_sectors,
                    relevant_watchlist_tickers=None,
                    member_watch_window_triggered=False,
                    alerted=False,
                )
                session.add(hearing)
                inserted += 1

        session.commit()
        print(f"[Hearings] {chamber}: {inserted} inserted, {updated} updated")
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
