"""
Centralized Claude client and model routing.

Rules (per spec):
- Use claude-sonnet-4-6 ONLY for:
  - Agent brain synthesis calls (materiality judgments).
  - Full recommendation card rationales.
- Use claude-haiku-4-5-20251001 for:
  - Sector digest summaries.
  - Congressional trade context paragraphs.
  - Supplier research summaries.
  - News sentiment / state-of-play paragraphs.

This module hides the model IDs behind simple helper functions so that
callers do not accidentally pick the wrong model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import anthropic

from market_lens import config


def _get_client() -> anthropic.Anthropic:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment")
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _build_message(
    client: anthropic.Anthropic,
    model: str,
    system_prompt: str,
    user_content: str,
    max_tokens: int = 800,
) -> str:
    """
    Low-level helper to send a single-turn message to Claude and
    return the text content.
    """
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": user_content,
            }
        ],
    )

    # Anthropic response content is a list of blocks; we expect a single text block.
    parts = getattr(resp, "content", []) or []
    for part in parts:
        if getattr(part, "type", None) == "text":
            return getattr(part, "text", "")
    # Fallback if schema differs
    return str(resp)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def synthesize_material_change(system_prompt: str, user_content: str, max_tokens: int = 900) -> str:
    """
    High-stakes, deep reasoning: always uses Claude Sonnet.

    Intended for:
    - Agent brain delta synthesis (noise vs material change).
    - Full recommendation card rationales.
    """
    client = _get_client()
    return _build_message(
        client=client,
        model=config.CLAUDE_SONNET_MODEL,
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=max_tokens,
    )


def summarize_low_stakes(system_prompt: str, user_content: str, max_tokens: int = 400) -> str:
    """
    Lower-stakes, higher-frequency summaries: always uses Claude Haiku.

    Intended for:
    - Sector digest one-liners.
    - Congressional trade context blurbs.
    - Supplier reliability research summaries.
    - News sentiment context paragraphs.
    """
    client = _get_client()
    return _build_message(
        client=client,
        model=config.CLAUDE_HAIKU_MODEL,
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=max_tokens,
    )


def call_claude_sonnet(system_prompt: str, user_text: str, max_tokens: int = 1000) -> str:
    """
    Convenience wrapper for high-stakes synthesis tasks using Claude Sonnet.

    Intended for:
    - Weekly / deep-dive digests.
    - Cross-signal synthesis where hallucinations are costly.
    """
    client = _get_client()
    return _build_message(
        client=client,
        model=config.CLAUDE_SONNET_MODEL,
        system_prompt=system_prompt,
        user_content=user_text,
        max_tokens=max_tokens,
    )

