"""
Market Lens — OGE Executive Branch Filings (Phase: Not Yet Built -> built)

Trump, cabinet members, and agency heads file Periodic Transaction Reports
with the Office of Government Ethics (OGE), not Congress — so they never show
up in the House/Senate ingestion. Open Cabinet (open-cabinet.org) already
scrapes and structures OGE's PDF filings into a maintained CSV, ticker
extraction included, which is far less brittle than us parsing OGE PDFs
ourselves.

Reuses the existing CongressTrade/CongressMember tables (chamber="executive")
rather than a parallel model, so executive-branch trades show up for free in
every view and signal that already reads CongressTrade: raw trades table,
active-sectors, cluster trades, convergence signals.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Optional, Tuple

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_lens.config import DATABASE_URL
from market_lens.database.models import CongressMember, CongressTrade

ALL_TRANSACTIONS_CSV_URL = "https://www.open-cabinet.org/data/all-transactions.csv"
USER_AGENT = "MarketLens/1.0 (compliance; omniaj@aol.com)"

TYPE_MAP = {
    "purchase": "buy",
    "sale": "sell",
    "sale (partial)": "sell",
}


def _get_session():
    engine = create_engine(DATABASE_URL)
    return sessionmaker(bind=engine)()


def _normalize_oge_name(raw_name: str) -> str:
    """Open Cabinet gives "Last, First Middle" — reorder to "First Middle Last"."""
    name = raw_name.strip()
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first.strip()} {last.strip()}"
    return re.sub(r"\s+", " ", name).strip()


def _parse_amount_range(raw: str) -> Tuple[Optional[float], Optional[float]]:
    cleaned = raw.replace("$", "").replace(",", "").strip()
    parts = cleaned.split("-")
    if len(parts) != 2:
        return None, None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None, None


def _parse_date(raw: str) -> Optional[date]:
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def ingest_oge_executive_filings() -> None:
    """
    Download Open Cabinet's structured OGE transaction CSV and store rows
    that have a real ticker as CongressTrade records (chamber="executive").

    ponytail: ~89% of rows have no ticker (private holdings, bonds, real
    estate) — skipped, since a blank ticker has no signal value and would
    just pollute ticker-keyed grouping elsewhere. The CSV also has no
    separate filing/disclosure date, only the transaction date — both
    trade_date and disclosure_date are set to it (days_to_disclose left
    null rather than guessed). Upgrade path: Open Cabinet's `late_filing`
    flag hints they track a real filing date internally; worth another look
    if disclosure-timing signals ever need it.
    """
    inserted = 0
    skipped_no_ticker = 0
    skipped_other = 0

    try:
        r = requests.get(ALL_TRANSACTIONS_CSV_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    except requests.exceptions.RequestException as e:
        print(f"[OGE] Download failed: {type(e).__name__}: {e}")
        return

    if r.status_code != 200:
        print(f"[OGE] Download returned status {r.status_code} — skipping")
        return

    reader = csv.DictReader(io.StringIO(r.text))
    session = _get_session()
    try:
        for row in reader:
            try:
                ticker = (row.get("ticker") or "").strip().upper()
                if not ticker:
                    skipped_no_ticker += 1
                    continue

                record_id = (row.get("recordId") or "").strip()
                if not record_id:
                    skipped_other += 1
                    continue
                trade_id = f"oge_{record_id}"

                existing = session.query(CongressTrade).filter_by(trade_id=trade_id).first()
                if existing:
                    skipped_other += 1
                    continue

                trade_date = _parse_date(row.get("date", ""))
                if not trade_date:
                    skipped_other += 1
                    continue

                member_name = _normalize_oge_name(row.get("official_name") or "")
                if not member_name:
                    skipped_other += 1
                    continue

                member_row = (
                    session.query(CongressMember)
                    .filter_by(name=member_name, chamber="executive")
                    .first()
                )
                if not member_row:
                    member_row = CongressMember(
                        member_id=f"oge_name::{member_name}",
                        name=member_name,
                        chamber="executive",
                    )
                    session.add(member_row)
                    session.flush()

                amount_low, amount_high = _parse_amount_range(row.get("amount_range") or "")
                transaction_type = TYPE_MAP.get((row.get("type") or "").strip().lower(), "disclosure")

                session.add(
                    CongressTrade(
                        trade_id=trade_id,
                        member_id=member_row.member_id,
                        ticker=ticker,
                        company_name=(row.get("description") or "").strip() or None,
                        transaction_type=transaction_type,
                        amount_range_low=amount_low,
                        amount_range_high=amount_high,
                        trade_date=trade_date,
                        disclosure_date=trade_date,
                        committee_correlated=False,
                        cluster_flag=False,
                        source="oge_open_cabinet",
                    )
                )
                inserted += 1
            except Exception as e:
                print(f"[OGE] Row error: {e}")
                skipped_other += 1
                continue

        session.commit()
    finally:
        session.close()

    print(
        f"[OGE] Complete — Inserted: {inserted} | Skipped (no ticker): {skipped_no_ticker} "
        f"| Skipped (other): {skipped_other}"
    )


if __name__ == "__main__":
    ingest_oge_executive_filings()
