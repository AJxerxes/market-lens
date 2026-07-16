"""
Market Lens — EDGAR Ingestion (Phase 3)
SEC filings: 10-K, 10-Q, 8-K, Form 4, DEF 14A. XBRL company facts. RSS 8-K polling.
User-Agent required on every request. Rate limit 10 req/s.
"""
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin

import requests
import feedparser
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

from market_lens.config import DATABASE_URL, EDGAR_USER_AGENT, EDGAR_BASE_URL
from market_lens.processing.ocr import extract_text_cascade
from market_lens.database.models import (
    Base,
    Company,
    TickerCikMap,
    EdgarFact,
    EdgarRssLastChecked,
    InsiderTransaction,
    InstrumentType,
)

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_DATA_BASE = "https://data.sec.gov"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = EDGAR_USER_AGENT
    return s


def _rate_limit():
    time.sleep(0.11)


def _cik_10(cik: Any) -> str:
    """Zero-pad CIK to 10 digits."""
    c = str(cik).strip()
    return c.zfill(10)


def refresh_ticker_cik_map(session_orm) -> None:
    """Download company_tickers.json and upsert ticker_cik_map."""
    s = _session()
    r = s.get(COMPANY_TICKERS_URL)
    _rate_limit()
    r.raise_for_status()
    data = r.json()
    for entry in data.values():
        ticker = entry.get("ticker")
        cik = _cik_10(entry.get("cik_str", entry.get("cik", "")))
        name = entry.get("title", "")
        if not ticker or not cik:
            continue
        stmt = pg_insert(TickerCikMap).values(
            ticker=ticker,
            cik=cik,
            company_name=name,
            last_updated=datetime.now(timezone.utc),
        ).on_conflict_do_update(
            index_elements=["ticker"],
            set_={"cik": cik, "company_name": name, "last_updated": datetime.now(timezone.utc)},
        )
        session_orm.execute(stmt)
    session_orm.flush()


def _get_cik_for_ticker(session_orm, ticker: str) -> Optional[str]:
    row = session_orm.query(TickerCikMap).filter(TickerCikMap.ticker == ticker).first()
    return row.cik if row else None


def _fetch_submissions(session_http: requests.Session, cik: str) -> Optional[Dict]:
    url = f"{SEC_DATA_BASE}/submissions/CIK{cik}.json"
    try:
        r = session_http.get(url, timeout=30)
    except requests.exceptions.Timeout:
        print(f"[TIMEOUT] EDGAR submissions request to {url} timed out after 30 seconds — skipping")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] EDGAR submissions request to {url} failed: {e}")
        return None
    _rate_limit()
    if r.status_code != 200:
        print(f"[ERROR] EDGAR submissions {url} returned status {r.status_code}")
        return None
    try:
        return r.json()
    except Exception as e:
        print(f"[ERROR] EDGAR submissions JSON parse failed for {url}: {e}")
        return None


def _fetch_company_facts(session_http: requests.Session, cik: str) -> Optional[Dict]:
    url = f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{cik}.json"
    try:
        r = session_http.get(url, timeout=30)
    except requests.exceptions.Timeout:
        print(f"[TIMEOUT] Company facts request to {url} timed out after 30 seconds — skipping")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Company facts request to {url} failed: {e}")
        return None
    _rate_limit()
    if r.status_code != 200:
        print(f"[ERROR] Company facts {url} returned status {r.status_code}")
        return None
    try:
        return r.json()
    except Exception as e:
        print(f"[ERROR] Company facts JSON parse failed for {url}: {e}")
        return None


TAGS_OF_INTEREST = {
    "Revenues",
    "NetIncomeLoss",
    "GrossProfit",
    "OperatingIncomeLoss",
    "EarningsPerShareBasic",
    "CommonStockDividendsPaidPerShare",
    "LongTermDebt",
    "NetCashProvidedByUsedInOperatingActivities",
}


def _extract_us_gaap_facts(facts: Dict, ticker: str) -> List[Dict]:
    """From companyfacts JSON, extract us-gaap numeric facts for storage."""
    out = []
    try:
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
    except Exception:
        return out
    for tag, tag_data in us_gaap.items():
        if tag not in TAGS_OF_INTEREST:
            continue
        units = tag_data.get("units", {})
        usd = units.get("USD") or units.get("usd")
        if not usd:
            continue
        for item in usd[:500]:
            end = item.get("end")
            val = item.get("val")
            if end is None or val is None:
                continue
            try:
                if isinstance(end, str):
                    period_end = date.fromisoformat(end[:10])
                else:
                    period_end = end
            except Exception:
                continue
            try:
                value = float(val)
            except (TypeError, ValueError):
                continue
            fy = item.get("fy")
            fp = item.get("fp")
            form = item.get("form")
            filed = item.get("filed")
            accn = item.get("accn")
            if filed and isinstance(filed, str):
                try:
                    filed_d = date.fromisoformat(filed[:10])
                except Exception:
                    filed_d = None
            else:
                filed_d = None
            out.append({
                "ticker": ticker,
                "tag": tag,
                "period_end": period_end,
                "value": value,
                "fy": fy,
                "fp": fp,
                "form": form,
                "filed": filed_d,
                "accession_number": accn,
            })
    return out


def _upsert_edgar_facts(session_orm, rows: List[Dict]) -> None:
    for row in rows:
        stmt = pg_insert(EdgarFact).values(**row).on_conflict_do_update(
            index_elements=["ticker", "tag", "period_end"],
            set_={
                "value": row["value"],
                "fy": row.get("fy"),
                "fp": row.get("fp"),
                "form": row.get("form"),
                "filed": row.get("filed"),
                "accession_number": row.get("accession_number"),
            },
        )
        session_orm.execute(stmt)
    session_orm.flush()


def _get_filing_document_url(accession: str, primary_doc: str) -> str:
    """Build URL for primary document. accession is like 0001234567-21-000123."""
    acc = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{acc}/{primary_doc}"


def _local_tag(el: ET.Element) -> str:
    if el.tag and "}" in el.tag:
        return el.tag.split("}", 1)[1]
    return el.tag or ""


def _find_all_local(root: ET.Element, local_name: str) -> List[ET.Element]:
    out = []
    for el in root.iter():
        if _local_tag(el) == local_name:
            out.append(el)
    return out


def _find_child_local(parent: ET.Element, local_name: str) -> Optional[ET.Element]:
    for el in parent:
        if _local_tag(el) == local_name:
            return el
    for el in parent.iter():
        if el != parent and _local_tag(el) == local_name:
            return el
    return None


def _find_descendant_value(parent: ET.Element, *path: str) -> Optional[str]:
    cur = parent
    for name in path:
        found = None
        for el in cur.iter():
            if el != cur and _local_tag(el) == name:
                found = el
                break
        if found is None:
            return None
        cur = found
    return cur.text.strip() if cur.text else None


def _parse_form4_xml(xml_text: str, ticker: str, filing_date: date, accession: str) -> List[Dict]:
    """Parse Form 4 XML and return list of insider transaction dicts."""
    results = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return results
    owners = _find_all_local(root, "reportingOwner")
    if not owners:
        owners = [root]
    for owner in owners:
        name_el = _find_child_local(owner, "rptOwnerName")
        name = (name_el.text or "").strip() if name_el is not None and name_el.text else "Unknown"
        if not name and name_el is not None:
            for c in name_el:
                if c.text:
                    name = c.text.strip()
                    break
        if name == "Unknown":
            for c in owner.iter():
                if _local_tag(c) == "rptOwnerName" and c.text:
                    name = c.text.strip()
                    break
        for nd in _find_all_local(root, "nonDerivativeTransaction"):
            shares_el = _find_child_local(nd, "transactionShares")
            if shares_el is None:
                for el in nd.iter():
                    if _local_tag(el) == "transactionShares":
                        shares_el = el
                        break
            shares = None
            if shares_el is not None and shares_el.text:
                try:
                    shares = int(float(shares_el.text))
                except (ValueError, TypeError):
                    pass
            if shares is None:
                val = _find_descendant_value(nd, "transactionAmounts", "transactionShares")
                if val:
                    try:
                        shares = int(float(val))
                    except (ValueError, TypeError):
                        pass
            if shares is None:
                continue
            price_el = _find_child_local(nd, "transactionPricePerShare")
            price = None
            if price_el is not None:
                v = _find_child_local(price_el, "value")
                if v is not None and v.text:
                    try:
                        price = float(v.text)
                    except (ValueError, TypeError):
                        pass
            acq_el = _find_child_local(nd, "transactionAcquiredDisposedCode")
            acq = ""
            if acq_el is not None:
                v = _find_child_local(acq_el, "value")
                if v is not None and v.text:
                    acq = (v.text or "").strip()
            total = shares * price if price is not None else None
            trans_type = "buy" if acq.upper() == "A" else "sell"
            results.append({
                "ticker": ticker,
                "filing_date": filing_date,
                "insider_name": name,
                "insider_title": None,
                "transaction_type": trans_type,
                "shares": shares,
                "price_per_share": price,
                "total_value": total,
                "source_filing": accession,
            })
    return results


def _ingest_form4_for_ticker(
    session_orm,
    session_http: requests.Session,
    ticker: str,
    cik: str,
    limit: int = 20,
) -> int:
    """Fetch submissions, find Form 4, download primary doc, parse, store. Returns count stored."""
    try:
        data = _fetch_submissions(session_http, cik)
        if not data:
            return 0
        filings = data.get("filings", {}).get("recent", {})
        if not filings:
            return 0
        forms = filings.get("form") or []
        accessions = filings.get("accessionNumber") or []
        primary_docs = filings.get("primaryDocument") or []
        filing_dates = filings.get("filingDate") or []
        count = 0
        for i, form in enumerate(forms):
            if form != "4":
                continue
            if count >= limit:
                break
            try:
                acc = accessions[i] if i < len(accessions) else None
                prim = primary_docs[i] if i < len(primary_docs) else "form4.xml"
                fd = filing_dates[i] if i < len(filing_dates) else str(date.today())
                try:
                    filing_date = date.fromisoformat(fd[:10])
                except Exception:
                    filing_date = date.today()
                if not acc:
                    continue
                url = _get_filing_document_url(acc, prim)
                try:
                    r = session_http.get(url, timeout=30)
                except requests.exceptions.Timeout:
                    try:
                        print(f"[TIMEOUT] Form 4 timed out for {ticker}")
                    except OSError:
                        pass
                    continue
                except requests.exceptions.RequestException as e:
                    try:
                        print(f"[ERROR] Form 4 request failed for {ticker}: {type(e).__name__}")
                    except OSError:
                        pass
                    continue
                _rate_limit()
                if r.status_code != 200:
                    try:
                        print(f"[ERROR] Form 4 status {r.status_code} for {ticker}")
                    except OSError:
                        pass
                    continue
                rows = _parse_form4_xml(r.text, ticker, filing_date, acc)
                if not rows and r.content and len(r.content) >= 4 and r.content[:4] == b"%PDF":
                    import tempfile
                    try:
                        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                            tmp.write(r.content)
                            tmp_path = Path(tmp.name)
                        try:
                            text, source = extract_text_cascade(file_path=tmp_path)
                            if text and source != "manual":
                                rows = _parse_form4_xml(text, ticker, filing_date, acc)
                        finally:
                            try:
                                tmp_path.unlink(missing_ok=True)
                            except Exception:
                                pass
                    except Exception:
                        pass
                for row in rows:
                    try:
                        existing = session_orm.query(InsiderTransaction).filter_by(
                            ticker=ticker,
                            filing_date=row["filing_date"],
                            insider_name=row["insider_name"],
                            source_filing=row["source_filing"],
                        ).first()
                        if not existing:
                            session_orm.add(InsiderTransaction(**row))
                            count += 1
                    except Exception:
                        continue
                try:
                    session_orm.flush()
                except Exception as e:
                    try:
                        print(f"[WARN] Form 4 flush failed for {ticker}: {type(e).__name__}")
                    except OSError:
                        pass
            except OSError:
                pass
            except Exception as e:
                try:
                    print(f"[WARN] Form 4 skipping doc for {ticker}: {type(e).__name__}")
                except OSError:
                    pass
                continue
        return count
    except OSError:
        return 0
    except Exception as e:
        try:
            print(f"[WARN] Form 4 ingestion failed for {ticker}: {type(e).__name__}")
        except OSError:
            pass
        return 0


def _poll_8k_rss(session_orm, session_http: requests.Session, cik: str) -> Optional[datetime]:
    """Poll 8-K RSS for CIK. Update last_checked. Return new last_checked."""
    url = (
        f"https://www.sec.gov/cgi-bin/browse-edgar?"
        f"action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count=10"
        f"&search_text=&output=atom"
    )
    try:
        r = session_http.get(url, timeout=30)
    except requests.exceptions.Timeout:
        try:
            print(f"[TIMEOUT] 8-K RSS timed out for CIK {cik}")
        except OSError:
            pass
        return None
    except requests.exceptions.RequestException as e:
        try:
            print(f"[ERROR] 8-K RSS request failed for CIK {cik}: {type(e).__name__}")
        except OSError:
            pass
        return None

    _rate_limit()

    if r.status_code != 200:
        try:
            print(f"[ERROR] 8-K RSS status {r.status_code} for CIK {cik}")
        except OSError:
            pass
        return None

    try:
        feed = feedparser.parse(r.content)
    except Exception as e:
        try:
            print(f"[ERROR] feedparser failed for CIK {cik}: {type(e).__name__}")
        except OSError:
            pass
        return None

    updated = None
    for entry in feed.entries[:10]:
        updated_parsed = entry.get("updated_parsed")
        if updated_parsed:
            try:
                from time import mktime
                utc = datetime.fromtimestamp(mktime(updated_parsed), tz=timezone.utc)
                if updated is None or utc > updated:
                    updated = utc
            except Exception:
                continue

    if updated is None:
        updated = datetime.now(timezone.utc)

    try:
        row = session_orm.query(EdgarRssLastChecked).filter(
            EdgarRssLastChecked.cik == cik
        ).first()
        if row:
            row.last_checked = updated
            row.updated_at = datetime.now(timezone.utc)
        else:
            session_orm.add(EdgarRssLastChecked(cik=cik, last_checked=updated))
        session_orm.flush()
    except Exception as e:
        try:
            print(f"[ERROR] 8-K RSS DB flush failed for CIK {cik}: {type(e).__name__}")
        except OSError:
            pass

    return updated


def run_edgar_ingestion(tickers: Optional[List[str]] = None) -> None:
    """
    Full EDGAR run: refresh CIK map, then for each watchlist equity:
    submissions -> company facts (XBRL), Form 4 parsing, 8-K RSS update.
    """
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session_orm = Session()
    session_http = _session()
    try:
        print("Refreshing ticker->CIK map...")
        refresh_ticker_cik_map(session_orm)
        session_orm.commit()
        print("[OK] Ticker-CIK map refreshed")

        if tickers is None:
            companies = (
                session_orm.query(Company)
                .filter(Company.active == True, Company.paused == False)
                .filter(Company.instrument_type.in_([InstrumentType.equity, InstrumentType.otc_adr]))
            )
            tickers = [c.ticker for c in companies]
        else:
            tickers = list(tickers)

        for ticker in tickers:
            cik = _get_cik_for_ticker(session_orm, ticker)
            if not cik:
                try:
                    print(f"  [WARN] {ticker}: no CIK found")
                except OSError:
                    pass
                continue

            facts_json = _fetch_company_facts(session_http, cik)
            if facts_json:
                rows = _extract_us_gaap_facts(facts_json, ticker)
                _upsert_edgar_facts(session_orm, rows)
                try:
                    print(f"  [OK] {ticker} edgar_facts: {len(rows)} rows")
                except OSError:
                    pass
            else:
                try:
                    print(f"  [WARN] {ticker}: no company facts")
                except OSError:
                    pass

            n4 = _ingest_form4_for_ticker(session_orm, session_http, ticker, cik, limit=15)
            try:
                print(f"  [OK] {ticker} Form 4: {n4} insider transactions")
            except OSError:
                pass

            try:
                _poll_8k_rss(session_orm, session_http, cik)
                try:
                    print(f"  [OK] {ticker} 8-K RSS last_checked updated")
                except OSError:
                    pass
            except OSError:
                # Ignore console/OS-level errors during 8-K polling
                pass
            except Exception as e:
                try:
                    print(f"  [WARN] {ticker} 8-K RSS failed: {type(e).__name__}")
                except OSError:
                    pass

        session_orm.commit()
        try:
            print("[OK] EDGAR ingestion complete")
        except OSError:
            pass
    except OSError as e:
        session_orm.rollback()
        try:
            print(f"[ERROR] EDGAR ingestion OSError: {e.errno} - {e.strerror}")
        except Exception:
            pass
        # Do not re-raise OSError — avoid crashing the dashboard on console issues
    except Exception as e:
        session_orm.rollback()
        try:
            print(f"[ERROR] EDGAR ingestion failed: {type(e).__name__}")
        except Exception:
            pass
        raise
    finally:
        session_orm.close()


def run_edgar_for_all() -> None:
    """
    Convenience wrapper for dashboards/schedulers: run EDGAR ingestion
    for all active, unpaused equity/ADR companies.
    """
    import sys
    import io
    # Redirect stdout to prevent OSError [Errno 22] on Windows console
    # when printing URLs with special characters
    old_stdout = sys.stdout
    try:
        sys.stdout = io.StringIO()
        run_edgar_ingestion(tickers=None)
    except OSError:
        pass
    except Exception:
        raise
    finally:
        sys.stdout = old_stdout


if __name__ == "__main__":
    import sys
    tickers = sys.argv[1:] if len(sys.argv) > 1 else None
    print("Market Lens — EDGAR Ingestion")
    print("-----------------------------")
    run_edgar_ingestion(tickers)

