"""
Recommendation engine.

Generates the final recommendation card for a company:
- Uses precomputed scores and valuation metrics from the database.
- Calls Claude Sonnet via llm_client for the plain-English rationale.

This module focuses on assembling inputs and calling the LLM; it does
not handle scheduling or alerts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_lens import config
from market_lens.agent import llm_client
from market_lens.database.models import Company, Score


_engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=_engine)


@dataclass
class RecommendationCard:
    ticker: str
    name: str
    current_price: Optional[float]
    fair_value_low: Optional[float]
    fair_value_high: Optional[float]
    lynch_score: Optional[float]
    swing_score: Optional[float]
    recommendation_label: Optional[str]
    swing_label: Optional[str]
    rationale_text: str


def _build_recommendation_system_prompt() -> str:
    return (
        "You are an investment analyst assistant. Given structured metrics "
        "about a company and the user's long-term investment philosophy, "
        "write a concise, specific rationale for the recommendation. "
        "Avoid generic platitudes and focus on concrete drivers like "
        "revenue growth, margins, leverage, insider activity, valuation "
        "vs history/sector, leadership stability, and supplier risks."
    )


def _build_recommendation_payload(company: Company, score: Score, current_price: Optional[float]) -> Dict[str, Any]:
    return {
        "ticker": company.ticker,
        "name": company.name,
        "current_price": current_price,
        "scores": {
            "lynch_score": score.lynch_score,
            "swing_score": score.swing_score,
            "recommendation_label": score.recommendation_label.value if score.recommendation_label else None,
            "swing_label": score.swing_label.value if score.swing_label else None,
        },
        "valuation": {
            "dcf_fair_value_low": score.dcf_fair_value_low,
            "dcf_fair_value_mid": getattr(score, "dcf_fair_value_mid", None),
            "dcf_fair_value_high": score.dcf_fair_value_high,
            "comps_target": score.comps_target,
            "mean_reversion_target": score.mean_reversion_target,
        },
        "thesis_notes": company.thesis_notes,
    }


def generate_recommendation_card(ticker: str, current_price: Optional[float]) -> Optional[RecommendationCard]:
    """
    Load the latest scores for a ticker, call Claude Sonnet for rationale,
    and return a RecommendationCard dataclass.
    """
    session = SessionLocal()
    try:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return None

        score = (
            session.query(Score)
            .filter(Score.ticker == ticker)
            .order_by(Score.score_date.desc())
            .first()
        )
        if not score:
            return None

        payload = _build_recommendation_payload(company, score, current_price)
        system_prompt = _build_recommendation_system_prompt()
        user_content = json.dumps(payload, indent=2)

        rationale = llm_client.synthesize_material_change(
            system_prompt=system_prompt,
            user_content=user_content,
            max_tokens=700,
        )

        return RecommendationCard(
            ticker=ticker,
            name=company.name,
            current_price=current_price,
            fair_value_low=score.dcf_fair_value_low,
            fair_value_high=score.dcf_fair_value_high,
            lynch_score=score.lynch_score,
            swing_score=score.swing_score,
            recommendation_label=score.recommendation_label.value if score.recommendation_label else None,
            swing_label=score.swing_label.value if score.swing_label else None,
            rationale_text=rationale,
        )
    finally:
        session.close()


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "DLB"
    session = SessionLocal()
    try:
        company = session.query(Company).filter(Company.ticker == ticker).first()
        price = float(company.current_price) if company and company.current_price else None
        if price is None:
            price = 0.0
        card = generate_recommendation_card(ticker, price)
        if card:
            print("Rationale:", card.rationale_text)
        else:
            print("No card generated.")
    finally:
        session.close()
