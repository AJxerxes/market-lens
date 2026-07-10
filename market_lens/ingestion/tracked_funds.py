"""
Tracked funds & 13F positions (Phase 20).

Responsibilities:
- Maintain a small set of high-conviction / thematic funds in `tracked_funds`.
- Discover their CIKs via SEC search-index.
- Ingest historical 13F-HR filings and store positions in `fund_positions`.
- Compute quarter-over-quarter deltas in `fund_position_delta`.
- Ingest ARK Invest daily trade history into `ark_daily_trades`.
- Provide raw inputs for agent brain synthesis and convergence analysis.

This module focuses on ingestion and bookkeeping. The agent brain
handles reasoning and alerting.
"""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, List, Optional

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from market_lens import config
from market_lens.database.models import (
    TrackedFund,
    FundPosition,
    FundPositionDelta,
    ArkDailyTrade,
)


_engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=_engine)

EDGAR_SEARCH_INDEX_URL = "https://efts.sec.gov/LATEST/search-index"
ARK_TRADE_HISTORY_URL = "https://ark-funds.com/trade-history"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_session() -> Session:
    return SessionLocal()


def _edgar_session() -> requests.Session:
    s = requests.Session()
    # Per spec: every EDGAR request must carry this User-Agent
    s.headers.update({"User-Agent": config.EDGAR_USER_AGENT})
    return s


@dataclass
class CIKSearchResult:
    cik: str
    name: str


def discover_cik_for_fund(fund_name: str) -> Optional[CIKSearchResult]:
    """
    Use SEC search-index to discover a fund's CIK from its legal name.

    This is a best-effort helper; some funds may require manual CIK entry.
    """
    session = _edgar_session()
    params = {
        "q": f"\"{fund_name}\"",
        "forms": "13F-HR",
    }
    try:
        resp = session.get(EDGAR_SEARCH_INDEX_URL, params=params, timeout=30)
    except requests.exceptions.Timeout:
        print(f"[TIMEOUT] EDGAR search-index request for fund '{fund_name}' timed out after 30 seconds — skipping")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] EDGAR search-index request for fund '{fund_name}' failed: {e}")
        return None
    if resp.status_code != 200:
        print(
            f"[ERROR] EDGAR search-index {EDGAR_SEARCH_INDEX_URL} returned status {resp.status_code} "
            f"for fund '{fund_name}'"
        )
        return None

    try:
        data = resp.json()
    except Exception as e:
        print(f"[ERROR] EDGAR search-index JSON parse failed for fund '{fund_name}': {e}")
        return None

    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        return None

    # Pick the first hit; refine later if needed.
    hit = hits[0].get("_source", {})
    cik = str(hit.get("cik") or "").lstrip("0")
    name = hit.get("entityName") or fund_name
    if not cik:
        return None

    return CIKSearchResult(cik=cik, name=name)


# Known CIKs for funds (EDGAR-verified); avoids runtime lookup when API is flaky
KNOWN_FUND_CIKS: dict = {
    "Situational Awareness LP": "0002045724",
    "Pershing Square Capital Management": None,  # discovered via EDGAR search below
}

SEC_DATA_BASE = "https://data.sec.gov"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


def ensure_tracked_funds_seeded() -> None:
    """
    Ensure core tracked funds exist in `tracked_funds`.
    Situational Awareness LP CIK hardcoded; others discovered via EDGAR or left for manual fill.
    """
    default_funds = [
        ("Situational Awareness LP", KNOWN_FUND_CIKS.get("Situational Awareness LP")),
        ("Pershing Square Capital Management", KNOWN_FUND_CIKS.get("Pershing Square Capital Management")),
        ("Coatue Management", None),
        ("Tiger Global Management", None),
        ("ARK Invest", None),
    ]

    session = _get_session()
    try:
        for name, cik in default_funds:
            existing = session.query(TrackedFund).filter_by(name=name).first()
            if existing:
                if cik and not existing.cik:
                    existing.cik = cik
                continue

            if not cik and name == "Pershing Square Capital Management":
                result = discover_cik_for_fund(name)
                cik = result.cik if result else None
            tracked = TrackedFund(
                name=name,
                cik=cik,
                fund_type="hedge_fund" if "ARK" not in name else "etf_family",
                thesis_notes="Situational Awareness LP (Leopold Aschenbrenner)" if name == "Situational Awareness LP" else None,
                active=True,
            )
            session.add(tracked)

        session.commit()
    finally:
        session.close()


FMP_BASE = "https://financialmodelingprep.com"


def _fmp_get(path: str, params: Optional[dict] = None) -> Optional[list]:
    if not config.FMP_API_KEY:
        return None
    params = dict(params or {})
    params.setdefault("apikey", config.FMP_API_KEY)
    try:
        r = requests.get(f"{FMP_BASE}{path}", params=params, timeout=30)
        if r.status_code != 200:
            print(f"[ERROR] FMP tracked funds {FMP_BASE}{path} returned status {r.status_code}")
            return None
        data = r.json()
        return data if isinstance(data, list) else None
    except requests.exceptions.Timeout:
        print(f"[TIMEOUT] FMP tracked funds request to {FMP_BASE}{path} timed out after 30 seconds — skipping")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] FMP tracked funds request to {FMP_BASE}{path} failed: {e}")
        return None
    except Exception as e:
        print(f"[ERROR] FMP tracked funds JSON parse failed for {FMP_BASE}{path}: {e}")
        return None


def _get_latest_13f_accession(cik: str) -> Optional[str]:
    """Get accession number (with dashes) for the most recent 13F-HR filing from EDGAR submissions."""
    cik_pad = cik.zfill(10)
    url = f"{SEC_DATA_BASE}/submissions/CIK{cik_pad}.json"
    sess = _edgar_session()
    try:
        r = sess.get(url, timeout=30)
        if r.status_code != 200:
            return None
        data = r.json()
        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form") or []
        accessions = filings.get("accessionNumber") or []
        for i, form in enumerate(forms):
            if form == "13F-HR" and i < len(accessions):
                return accessions[i]  # most recent first
        return None
    except Exception as e:
        print(f"[TrackedFunds] EDGAR submissions for CIK {cik}: {e}")
        return None


def _fetch_13f_infotable_xml(cik: str, accession_number: str) -> Optional[str]:
    """Fetch infotable.xml for a 13F-HR filing. accession_number has dashes e.g. 0002045724-25-000008."""
    acc_clean = accession_number.replace("-", "")
    # CIK without leading zeros for URL path
    cik_num = cik.lstrip("0") or "0"
    url = f"{SEC_ARCHIVES_BASE}/{cik_num}/{acc_clean}/infotable.xml"
    sess = _edgar_session()
    try:
        r = sess.get(url, timeout=30)
        if r.status_code != 200:
            return None
        return r.text
    except Exception as e:
        print(f"[TrackedFunds] EDGAR infotable fetch {url}: {e}")
        return None


def _parse_infotable_xml(xml_text: str) -> List[dict]:
    """Parse SEC 13F infotable.xml into list of position dicts (nameOfIssuer, cusip, value, sshPrnamt, etc.)."""
    out: List[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    ns = {"ns": "http://www.sec.gov/edgar/document/thirteenf/informationtable"}
    for info in root.findall(".//ns:infoTable", ns):
        if info is None:
            info = root.find(".//infoTable")
        if info is None:
            for elem in root.iter():
                if "infoTable" in (elem.tag or ""):
                    info = elem
                    break
        if info is None:
            continue
        def text(tag: str) -> str:
            el = info.find(f".//{{{ns['ns']}}}{tag}") if ns else info.find(f".//{tag}")
            if el is None:
                for e in info.iter():
                    if tag in (e.tag or ""):
                        return (e.text or "").strip()
                return ""
            return (el.text or "").strip()
        def text_any(tag: str) -> str:
            for t in (tag, tag.replace("_", ""), tag.lower()):
                v = text(t)
                if v:
                    return v
            return ""
        name = text_any("nameOfIssuer") or text_any("nameOfIssuer")
        cusip = text_any("cusip")
        val = text_any("value")
        sh = text_any("sshPrnamt")
        try:
            value_thou = float(val) if val else 0.0
            shares = float(sh) if sh else 0.0
        except ValueError:
            value_thou = 0.0
            shares = 0.0
        out.append({
            "nameOfIssuer": name,
            "cusip": cusip,
            "value": value_thou * 1000,  # value in thousands
            "shares": shares,
            "accession_number": None,
        })
    # No namespace fallback
    if not out:
        for info in root.iter():
            if "infoTable" not in (info.tag or ""):
                continue
            name = ""
            val = ""
            sh = ""
            for c in info:
                tag = (c.tag or "").split("}")[-1]
                if tag == "nameOfIssuer":
                    name = (c.text or "").strip()
                elif tag == "value":
                    val = (c.text or "").strip()
                elif tag == "sshPrnamt":
                    sh = (c.text or "").strip()
            try:
                value_thou = float(val) if val else 0.0
                shares = float(sh) if sh else 0.0
            except ValueError:
                value_thou = 0.0
                shares = 0.0
            out.append({"nameOfIssuer": name, "cusip": "", "value": value_thou * 1000, "shares": shares, "accession_number": None})
    return out


def ingest_13f_positions_for_fund(fund: TrackedFund) -> None:
    """
    Ingest 13F positions from EDGAR (free). Fetches latest 13F-HR accession and parses infotable.xml.
    No FMP dependency.
    """
    cik = (fund.cik or "").strip().lstrip("0") or None
    if not cik:
        return
    acc = _get_latest_13f_accession(cik)
    if not acc:
        return
    xml_text = _fetch_13f_infotable_xml(cik, acc)
    if not xml_text:
        return
    positions = _parse_infotable_xml(xml_text)
    if not positions:
        return
    session = _get_session()
    try:
        # Report date from accession or today
        as_of = _utc_now().date()
        quarter = f"{as_of.year}Q{(as_of.month - 1) // 3 + 1}"
        for item in positions[:500]:
            name = (item.get("nameOfIssuer") or "").strip()
            cusip = (item.get("cusip") or "").strip()
            ticker = (item.get("ticker") or cusip or name[:20] or "N/A").upper()
            ticker = re.sub(r"[^A-Z0-9.]", "", ticker)[:20] or "CUSIP"
            if not name and not cusip:
                continue
            shares = float(item.get("shares") or 0)
            market_value = float(item.get("value") or 0)
            existing = (
                session.query(FundPosition)
                .filter_by(fund_id=fund.id, ticker=ticker, quarter=quarter)
                .first()
            )
            if not existing:
                session.add(
                    FundPosition(
                        fund_id=fund.id,
                        ticker=ticker,
                        company_name=name,
                        quarter=quarter,
                        shares=shares,
                        market_value=market_value,
                        form_type="13F-HR",
                        accession_number=acc,
                        as_of_date=as_of,
                    )
                )
        session.commit()
    finally:
        session.close()


def _sorted_quarters(quarters: Iterable[str]) -> List[str]:
    def key(q: str):
        try:
            year, qtr = q.split("Q")
            return (int(year), int(qtr))
        except Exception:
            return (0, 0)
    return sorted(set(quarters), key=key)


def recompute_fund_position_deltas(fund: TrackedFund) -> None:
    """
    Compute quarter-over-quarter deltas for a fund's 13F positions.

    Compares the two most recent quarters present in `fund_positions`:
    - added: ticker present now, absent previously
    - exited: ticker present previously, absent now
    - increased / decreased: ticker in both, market_value change beyond a noise threshold
    Writes results into FundPositionDelta (idempotent: clears prior deltas for the
    current/previous quarter pair before inserting fresh ones).
    """
    session = _get_session()
    try:
        quarters = [
            row[0]
            for row in session.query(FundPosition.quarter)
            .filter_by(fund_id=fund.id)
            .distinct()
            .all()
        ]
        ordered = _sorted_quarters(quarters)
        if len(ordered) < 2:
            return
        current_q, previous_q = ordered[-1], ordered[-2]

        current_positions = {
            p.ticker: p
            for p in session.query(FundPosition).filter_by(fund_id=fund.id, quarter=current_q).all()
        }
        previous_positions = {
            p.ticker: p
            for p in session.query(FundPosition).filter_by(fund_id=fund.id, quarter=previous_q).all()
        }

        # Clear any previously computed deltas for this quarter pair to keep this idempotent.
        session.query(FundPositionDelta).filter_by(
            fund_id=fund.id, quarter=current_q, previous_quarter=previous_q
        ).delete()

        NOISE_THRESHOLD_PCT = 5.0  # ignore value swings smaller than this as noise

        for ticker, curr in current_positions.items():
            prev = previous_positions.get(ticker)
            if prev is None:
                session.add(
                    FundPositionDelta(
                        fund_id=fund.id,
                        ticker=ticker,
                        quarter=current_q,
                        previous_quarter=previous_q,
                        change_type="added",
                        size_change_pct=None,
                        direction_changed=True,
                        notes=f"New position: {curr.market_value:,.0f} market value.",
                    )
                )
                continue

            prev_value = prev.market_value or 0.0
            curr_value = curr.market_value or 0.0
            if prev_value <= 0:
                pct_change = 100.0 if curr_value > 0 else 0.0
            else:
                pct_change = ((curr_value - prev_value) / prev_value) * 100.0

            if abs(pct_change) < NOISE_THRESHOLD_PCT:
                continue

            change_type = "increased" if pct_change > 0 else "decreased"
            session.add(
                FundPositionDelta(
                    fund_id=fund.id,
                    ticker=ticker,
                    quarter=current_q,
                    previous_quarter=previous_q,
                    change_type=change_type,
                    size_change_pct=pct_change,
                    direction_changed=False,
                    notes=f"Market value {prev_value:,.0f} -> {curr_value:,.0f} ({pct_change:+.1f}%).",
                )
            )

        for ticker, prev in previous_positions.items():
            if ticker in current_positions:
                continue
            session.add(
                FundPositionDelta(
                    fund_id=fund.id,
                    ticker=ticker,
                    quarter=current_q,
                    previous_quarter=previous_q,
                    change_type="exited",
                    size_change_pct=-100.0,
                    direction_changed=True,
                    notes=f"Position exited: was {prev.market_value:,.0f} market value in {previous_q}.",
                )
            )

        session.commit()
    finally:
        session.close()


def ingest_ark_daily_trades() -> None:
    """
    Parse ARK's daily trade history CSV.

    The ARK site exposes daily trades as downloadable CSV(s).
    This function fetches the page, finds CSV links, downloads
    the most recent file(s), and populates `ark_daily_trades`.
    """
    try:
        resp = requests.get(ARK_TRADE_HISTORY_URL, timeout=30)
    except requests.exceptions.Timeout:
        print(f"[TIMEOUT] ARK trade history request to {ARK_TRADE_HISTORY_URL} timed out after 30 seconds — skipping")
        return
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] ARK trade history request to {ARK_TRADE_HISTORY_URL} failed: {e}")
        return
    if resp.status_code != 200:
        print(f"[ERROR] ARK trade history {ARK_TRADE_HISTORY_URL} returned status {resp.status_code}")
        return

    # Many implementations expose a direct CSV link via an <a> tag.
    # Here we extract any .csv URL from the HTML as a simple heuristic.
    csv_urls = set(re.findall(r"https?://[^\s\"']+\.csv", resp.text))
    if not csv_urls:
        return

    session_db = _get_session()
    try:
        for url in csv_urls:
            try:
                csv_resp = requests.get(url, timeout=30)
            except requests.exceptions.Timeout:
                print(f"[TIMEOUT] ARK CSV request to {url} timed out after 30 seconds — skipping")
                continue
            except requests.exceptions.RequestException as e:
                print(f"[ERROR] ARK CSV request to {url} failed: {e}")
                continue

            if csv_resp.status_code != 200:
                print(f"[ERROR] ARK CSV {url} returned status {csv_resp.status_code}")
                continue

            try:
                text = csv_resp.text
                reader = csv.DictReader(io.StringIO(text))
            except Exception as e:
                print(f"[ERROR] Failed parsing ARK CSV from {url}: {e}")
                continue

            for row in reader:
                try:
                    trade_date = _parse_date(row.get("date") or row.get("Date"))
                    ticker = (row.get("ticker") or row.get("Ticker") or "").upper()
                    fund_name = row.get("fund") or row.get("Fund") or "ARK"
                    company_name = row.get("company") or row.get("Company")
                    direction = (row.get("direction") or row.get("Direction") or "").lower()
                    shares = float(row.get("shares") or row.get("Shares") or 0)
                    notional = float(row.get("value") or row.get("Value") or 0)
                except Exception:
                    continue

                large_flag = notional > 10_000_000

                trade = ArkDailyTrade(
                    trade_date=trade_date or _utc_now().date(),
                    fund_name=fund_name,
                    ticker=ticker,
                    company_name=company_name,
                    direction=direction,
                    shares=shares,
                    notional_value=notional,
                    large_trade_flag=large_flag,
                    raw_source_url=url,
                )
                session_db.add(trade)

        session_db.commit()
    finally:
        session_db.close()


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except Exception:
            continue
    return None


def run_tracked_funds_ingestion() -> None:
    """
    High-level entry point for APScheduler:
    - Ensure default tracked funds exist.
    - Discover / confirm CIKs where missing.
    - Ingest or refresh 13F positions.
    - Recompute position deltas.
    - Ingest ARK daily trades.
    """
    ensure_tracked_funds_seeded()

    session = _get_session()
    try:
        funds: List[TrackedFund] = session.query(TrackedFund).filter_by(active=True).all()

        # Discover CIKs for funds that lack them.
        for fund in funds:
            if not fund.cik:
                result = discover_cik_for_fund(fund.name)
                if result:
                    fund.cik = result.cik
                    if not fund.thesis_notes:
                        fund.thesis_notes = f"Tracked fund discovered via EDGAR search-index: {result.name}"

        session.commit()
        fund_ids = [f.id for f in funds]
    finally:
        session.close()

    # EDGAR-intensive operations can run outside the DB session.
    for fund_id in fund_ids:
        session2 = _get_session()
        try:
            fund = session2.query(TrackedFund).filter_by(id=fund_id).first()
            if fund:
                ingest_13f_positions_for_fund(fund)
                recompute_fund_position_deltas(fund)
        finally:
            session2.close()

    # ARK trades can be ingested daily.
    ingest_ark_daily_trades()


if __name__ == "__main__":
    print("Market Lens — Tracked Funds")
    print("---------------------------")
    run_tracked_funds_ingestion()
    print("[OK] Tracked funds ingestion done.")
