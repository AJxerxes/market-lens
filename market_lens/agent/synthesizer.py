"""
Agent brain synthesizer.

Uses Claude Sonnet via `llm_client.synthesize_material_change` to:
- Combine thesis, prior state snapshot, new data, and 90-day history.
- Decide whether changes are material vs noise.
- Produce a plain-English reasoning paragraph for alerts and logs.

This module does NOT send alerts directly; it returns text and flags
for the agent brain to act on.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from market_lens.agent import llm_client


def build_synthesis_system_prompt() -> str:
    """
    System prompt shared by all material-change synthesis calls.

    The caller is responsible for formatting the user content JSON.
    """
    return (
        "You are the reasoning core of a personal investment research agent. "
        "Your job is to decide whether new information is MATERIAL to the "
        "user's original investment thesis or merely noise. Always explain "
        "your reasoning in plain English, referencing specific facts. "
        "Be conservative about alerts: only treat changes as material when "
        "they reasonably threaten or strengthen the long-term thesis."
    )


def synthesize_change(
    company_ticker: str,
    thesis_text: str,
    prior_state: Dict[str, Any],
    new_data: Dict[str, Any],
    history_90d: Dict[str, Any],
) -> str:
    """
    Core API used by the agent brain.

    Arguments:
        company_ticker: Stock ticker being analyzed.
        thesis_text: User's original plain-English thesis/observation.
        prior_state: Snapshot from agent_memory before new data arrived.
        new_data: All signals that triggered this delta check.
        history_90d: Compressed 90-day signal history for pattern context.

    Returns:
        A plain-English paragraph (or two) explaining whether the change
        is material, why, and what to watch next.
    """
    # Explicit 4-part prompt (Phase 12): thesis, prior_state, new_data, history_90d.
    # For validation, run with a Dolby (DLB) 8-K event and confirm output references
    # the filing and materiality to the user's thesis.
    payload = {
        "ticker": company_ticker,
        "part_1_thesis": thesis_text,
        "part_2_prior_state": prior_state,
        "part_3_new_data": new_data,
        "part_4_history_90d": history_90d,
        "instructions": {
            "task": "assess_materiality",
            "input_structure": "Part 1 = user thesis; Part 2 = prior snapshot; Part 3 = new signals/delta; Part 4 = 90-day event history.",
            "requirements": [
                "Decide if new information is material to the thesis or noise.",
                "Reference concrete facts: filings (e.g. 8-K), prices, options flow, court cases, leadership changes, or supplier signals.",
                "Explain whether this continues an existing pattern or is a one-off event.",
                "Highlight what would change your mind (follow-up data to watch).",
            ],
            "output_format": "one or two paragraphs of plain English, no bullet points.",
        },
    }

    system_prompt = build_synthesis_system_prompt()
    user_content = json.dumps(payload, indent=2)

    return llm_client.synthesize_material_change(
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=900,
    )

