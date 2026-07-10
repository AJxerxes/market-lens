"""
Market Lens — Supplier signal detection (Phase 16).

Four layers:
1. 10-K risk factor delta (meaningful_change_flag from risk_factor_delta) -> supplier_risk_language.
2. Transcript keywords (earnings_call) -> supplier_risk_language / new_supplier_named.
3. 8-K Item 1.01 / 2.03 material contract -> new_supplier_named / supplier_removed.
4. Census / Panjiva / ImportYeti (stub) -> customs_import_change.

Uses supplier_registry for known supplier names and severity.
"""
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from market_lens.database.models import (
    Company,
    RiskFactorDelta,
    SupplierSignal,
    SupplierRegistry,
    SignalType,
    SignalSeverity,
)
from market_lens.processing.nlp import run_supplier_keyword_scan, run_risk_factor_delta


# Layer 1: 10-K risk factor delta — already populated by NLP/EDGAR. We emit supplier_signals when meaningful.
def _layer_1_from_risk_delta(session: Session, ticker: str) -> int:
    """Create supplier_signals from recent risk_factor_delta rows with meaningful_change_flag."""
    added = 0
    rows = (
        session.query(RiskFactorDelta)
        .filter(
            RiskFactorDelta.ticker == ticker,
            RiskFactorDelta.meaningful_change_flag == True,
        )
        .order_by(RiskFactorDelta.current_filing_date.desc())
        .limit(5)
        .all()
    )
    for r in rows:
        existing = (
            session.query(SupplierSignal)
            .filter_by(
                ticker=ticker,
                detected_date=r.current_filing_date,
                signal_type=SignalType.supplier_risk_language,
                source="10k_risk_factors",
            )
            .first()
        )
        if not existing and r.current_risk_text:
            session.add(
                SupplierSignal(
                    ticker=ticker,
                    detected_date=r.current_filing_date,
                    signal_type=SignalType.supplier_risk_language,
                    source="10k_risk_factors",
                    context_text=(r.current_risk_text or "")[:2000],
                    severity=SignalSeverity.watch,
                )
            )
            added += 1
    session.flush()
    return added


# Layer 2: transcript — caller passes transcript text; we call run_supplier_keyword_scan.
def layer_2_transcript_scan(session: Session, ticker: str, transcript_text: str, source: str = "earnings_call") -> int:
    """Scan transcript for supplier keywords. Returns count of signals added."""
    return run_supplier_keyword_scan(session, ticker, transcript_text, source=source)


# Layer 3: 8-K material contract — parse 8-K text for Item 1.01 / 2.03 and detect supplier change.
ITEM_101_203 = re.compile(
    r"Item\s+(?:1\.01|2\.03)\s*[^I]*?"
    r"(?:material\s+contract|entered\s+into|termination|amendment|supplier|manufacturing\s+agreement)",
    re.IGNORECASE | re.DOTALL,
)
SUPPLIER_NAMED = re.compile(
    r"(?:entered\s+into\s+(?:a\s+)?(?:agreement|contract)\s+with)\s+([A-Z][A-Za-z0-9\s,&]+?)(?:\s+[,(]|\s+to\s|\s+for\s|\.)",
    re.IGNORECASE,
)
TERMINATION = re.compile(
    r"(?:terminated|termination\s+of)\s+(?:the\s+)?(?:agreement|contract)\s+with\s+([A-Z][A-Za-z0-9\s,&]+?)(?:\s+[,(]|\s+effective|\.)",
    re.IGNORECASE,
)


def _parse_8k_material_contract_suppliers(text: str) -> List[Dict[str, Any]]:
    """Extract supplier names from 8-K Item 1.01/2.03 sections."""
    signals = []
    for m in ITEM_101_203.finditer(text[:50000]):
        block = text[m.start() : m.end() + 1500]
        for sm in SUPPLIER_NAMED.finditer(block):
            name = sm.group(1).strip()
            if len(name) > 5 and len(name) < 200:
                signals.append({"supplier_name": name, "signal_type": SignalType.new_supplier_named})
        for tm in TERMINATION.finditer(block):
            name = tm.group(1).strip()
            if len(name) > 5 and len(name) < 200:
                signals.append({"supplier_name": name, "signal_type": SignalType.supplier_removed})
    return signals


def layer_3_8k_material_contract(
    session: Session,
    ticker: str,
    filing_date: date,
    eight_k_text: str,
    source_filing: str = "8-K",
) -> int:
    """Parse 8-K text for Item 1.01/2.03 supplier changes. Returns count added."""
    added = 0
    for ev in _parse_8k_material_contract_suppliers(eight_k_text):
        existing = (
            session.query(SupplierSignal)
            .filter_by(
                ticker=ticker,
                detected_date=filing_date,
                signal_type=ev["signal_type"],
                supplier_name=ev["supplier_name"],
                source="8k_material_contract",
            )
            .first()
        )
        if not existing:
            session.add(
                SupplierSignal(
                    ticker=ticker,
                    detected_date=filing_date,
                    signal_type=ev["signal_type"],
                    supplier_name=ev["supplier_name"],
                    source="8k_material_contract",
                    context_text=None,
                    severity=SignalSeverity.informational,
                )
            )
            _ensure_supplier_registry(session, ev["supplier_name"])
            added += 1
    session.flush()
    return added


def _ensure_supplier_registry(session: Session, supplier_name: str) -> None:
    """Ensure supplier_registry has a row for this name (no score yet)."""
    if not supplier_name or len(supplier_name) < 2:
        return
    existing = session.query(SupplierRegistry).filter_by(supplier_name=supplier_name).first()
    if not existing:
        session.add(SupplierRegistry(supplier_name=supplier_name))
        session.flush()


# Layer 4: Census / Panjiva / ImportYeti — stub (no API key by default).
def layer_4_customs_import(session: Session, ticker: str, company_name: str) -> int:
    """Stub for customs/import data. Returns 0 until API integrated."""
    return 0


def run_supplier_detection_for_ticker(
    session: Session,
    ticker: str,
    transcript_text: Optional[str] = None,
    eight_k_text: Optional[str] = None,
    eight_k_filing_date: Optional[date] = None,
) -> int:
    """
    Run all four layers for a ticker. Caller can pass transcript and/or 8-K text.
    Layer 1 runs from existing risk_factor_delta. Returns total signals added.
    """
    total = 0
    total += _layer_1_from_risk_delta(session, ticker)
    if transcript_text:
        total += layer_2_transcript_scan(session, ticker, transcript_text, source="earnings_call")
    if eight_k_text and eight_k_filing_date:
        total += layer_3_8k_material_contract(
            session, ticker, eight_k_filing_date, eight_k_text, source_filing="8-K"
        )
    company = session.query(Company).filter_by(ticker=ticker).first()
    if company:
        total += layer_4_customs_import(session, ticker, company.name or ticker)
    return total
