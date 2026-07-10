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

from datetime import date, datetime, timezone, timedelta
from typing import Iterable, Optional

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from market_lens import config
from market_lens.database.models import (
    CongressMember,
    CongressTrade,
    CommitteeSectorMap,
    DisclosureTimingProfile,
    CommitteeHearing,
)


_engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=_engine)


FMP_BASE_URL = "https://financialmodelingprep.com"
CONGRESS_BASE_URL = "https://api.congress.gov/v3"


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _get_session() -> Session:
    return SessionLocal()


# ---------------------------------------------------------------------------
# FMP congressional disclosures
# ---------------------------------------------------------------------------


def _fmp_get(path: str, params: Optional[dict] = None) -> Optional[dict]:
    if not config.FMP_API_KEY:
        return None
    if params is None:
        params = {}
    params.setdefault("apikey", config.FMP_API_KEY)
    url = f"{FMP_BASE_URL}{path}"
    resp = requests.get(url, params=params, timeout=15)
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def ingest_house_disclosures(limit: int = 1000) -> None:
    """
    Ingest House STOCK Act disclosures via FMP `/api/v4/house-disclosure`.

    This function is designed to be idempotent; it should skip
    any trade_id that already exists in `congress_trades`.
    """
    data = _fmp_get("/api/v4/house-disclosure", params={"page": 0, "size": limit})
    if not data:
        return

    session = _get_session()
    try:
        for item in data:
            trade_id = str(item.get("transactionId") or "")
            if not trade_id:
                continue

            existing = (
                session.query(CongressTrade).filter_by(trade_id=trade_id).first()
            )
            if existing:
                continue

            member_id = item.get("representative") or ""
            ticker = item.get("ticker") or ""
            company_name = item.get("assetDescription") or ""
            transaction_type = (item.get("type") or "").lower()

            trade = CongressTrade(
                trade_id=trade_id,
                member_id=member_id,
                ticker=ticker,
                company_name=company_name,
                sector=None,
                transaction_type=transaction_type,
                amount_range_low=item.get("amountLower"),
                amount_range_high=item.get("amountUpper"),
                trade_date=_safe_date(item.get("transactionDate")),
                disclosure_date=_safe_date(item.get("reportDate")),
                days_to_disclose=_compute_days_to_disclose(
                    item.get("transactionDate"), item.get("reportDate")
                ),
                committee_correlated=False,
                matching_committees=None,
                cluster_flag=False,
                source="fmp_house",
            )
            session.add(trade)

        session.commit()
    finally:
        session.close()


def ingest_senate_disclosures(limit: int = 1000) -> None:
    """
    Ingest Senate STOCK Act disclosures via FMP `/api/v4/senate-disclosure`.
    """
    data = _fmp_get("/api/v4/senate-disclosure", params={"page": 0, "size": limit})
    if not data:
        return

    session = _get_session()
    try:
        for item in data:
            trade_id = str(item.get("transactionId") or "")
            if not trade_id:
                continue

            existing = (
                session.query(CongressTrade).filter_by(trade_id=trade_id).first()
            )
            if existing:
                continue

            member_id = item.get("senator") or ""
            ticker = item.get("ticker") or ""
            company_name = item.get("assetDescription") or ""
            transaction_type = (item.get("type") or "").lower()

            trade = CongressTrade(
                trade_id=trade_id,
                member_id=member_id,
                ticker=ticker,
                company_name=company_name,
                sector=None,
                transaction_type=transaction_type,
                amount_range_low=item.get("amountLower"),
                amount_range_high=item.get("amountUpper"),
                trade_date=_safe_date(item.get("transactionDate")),
                disclosure_date=_safe_date(item.get("reportDate")),
                days_to_disclose=_compute_days_to_disclose(
                    item.get("transactionDate"), item.get("reportDate")
                ),
                committee_correlated=False,
                matching_committees=None,
                cluster_flag=False,
                source="fmp_senate",
            )
            session.add(trade)

        session.commit()
    finally:
        session.close()


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
    resp = requests.get(url, params=params, timeout=15)
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
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
    """
    Pull upcoming committee meetings from Congress.gov and
    populate the `committee_hearings` table.
    """
    path = f"/committee-meeting/{congress_number}/{chamber}"
    data = _congress_get(path)
    if not data:
        return

    session = _get_session()
    try:
        meetings = data.get("committeeMeetings") or []
        for m in meetings:
            hearing_id = str(m.get("meetingId") or "")
            if not hearing_id:
                continue

            existing = (
                session.query(CommitteeHearing)
                .filter_by(hearing_id=hearing_id)
                .first()
            )
            if existing:
                continue

            dt_str = m.get("meetingDate")
            hearing_dt = None
            if dt_str:
                try:
                    hearing_dt = datetime.fromisoformat(dt_str)
                except Exception:
                    hearing_dt = None

            hearing = CommitteeHearing(
                hearing_id=hearing_id,
                committee_name=m.get("committeeName") or "",
                chamber=chamber,
                hearing_date=hearing_dt or datetime.now(timezone.utc),
                subject=m.get("description"),
                hearing_title=m.get("description"),
                topic_keywords=None,
                sector_relevance=None,
                relevant_sectors=None,
                relevant_watchlist_tickers=None,
                member_watch_window_triggered=False,
                alerted=False,
            )
            session.add(hearing)

        session.commit()
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
