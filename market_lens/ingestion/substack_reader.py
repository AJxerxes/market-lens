"""
Market Lens — Substack RSS reader (Phase 20).

- Tracks curated Substack / research feeds.
- Ingests new posts via RSS and tags them with tickers/sectors using Claude Haiku.
- Cross-references with watchlist and populates a research radar for tickers
  not yet on the watchlist.
"""
from __future__ import annotations

from datetime import datetime, timezone, date
from typing import List, Dict, Any, Optional
import json

import feedparser
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_lens.config import DATABASE_URL
from market_lens.database.models import (
    Base,
    SubstackFeed,
    SubstackPost,
    ResearchRadar,
    Company,
    AgentSynthesisLog,
)
from market_lens.agent import llm_client


SEED_FEEDS: List[Dict[str, str]] = [
    # User-specified feeds
    {
        "feed_url": "https://asymmetricalbets.substack.com",
        "rss_url": "https://asymmetricalbets.substack.com/feed",
        "author_name": "KawzInvests + MichaelSikand",
        "thesis_focus": "thematic analysis, narrative alpha, multi-bagger equities",
    },
    {
        "feed_url": "https://outperformingthemarket.substack.com",
        "rss_url": "https://outperformingthemarket.substack.com/feed",
        "author_name": "Outperforming The Market",
        "thesis_focus": "growth stocks, retail-friendly analysis",
    },
    {
        "feed_url": "https://www.conks.plumbing",
        "rss_url": "https://www.conks.plumbing/feed",
        "author_name": "Conks",
        "thesis_focus": "independent deep dives",
    },
    {
        "feed_url": "https://mispricedassets.substack.com",
        "rss_url": "https://mispricedassets.substack.com/feed",
        "author_name": "Mispriced Assets",
        "thesis_focus": "value investing, mispricing signals",
    },
    {
        "feed_url": "https://www.junkbondinvestor.com",
        "rss_url": "https://www.junkbondinvestor.com/feed",
        "author_name": "Junk Bond Investor",
        "thesis_focus": "credit markets, high yield bonds",
    },
    {
        "feed_url": "https://thebearcave.substack.com",
        "rss_url": "https://thebearcave.substack.com/feed",
        "author_name": "The Bear Cave (Edwin Dorsey)",
        "thesis_focus": "short selling, corporate misconduct, fraud detection",
    },
    {
        "feed_url": "https://alphainacademia.substack.com",
        "rss_url": "https://alphainacademia.substack.com/feed",
        "author_name": "Alpha In Academia",
        "thesis_focus": "academic research applied to investing",
    },
    {
        "feed_url": "https://www.thelastbearstanding.com",
        "rss_url": "https://www.thelastbearstanding.com/feed",
        "author_name": "The Last Bear Standing",
        "thesis_focus": "macro, credit risk, market structure",
    },
    # Curated additions
    {
        "feed_url": "https://newsletter.doomberg.com",
        "rss_url": "https://newsletter.doomberg.com/feed",
        "author_name": "Doomberg",
        "thesis_focus": "energy geopolitics, AI infrastructure, commodities — aligns with Situational Awareness LP thesis",
    },
    {
        "feed_url": "https://www.citriniresearch.com",
        "rss_url": "https://www.citriniresearch.com/feed",
        "author_name": "Citrini Research",
        "thesis_focus": "thematic equity investing, global macro, cross-asset lateral thinking",
    },
    {
        "feed_url": "https://www.compoundingquality.net",
        "rss_url": "https://www.compoundingquality.net/feed",
        "author_name": "Compounding Quality",
        "thesis_focus": "high quality compounders, Buffett-style long term holds",
    },
    {
        "feed_url": "https://www.capitalflowsresearch.com",
        "rss_url": "https://www.capitalflowsresearch.com/feed",
        "author_name": "Capital Flows Research",
        "thesis_focus": "macro regime mapping, rates, credit, FX, equities",
    },
    {
        "feed_url": "https://jonahlupton.substack.com",
        "rss_url": "https://jonahlupton.substack.com/feed",
        "author_name": "Growth Stock Deep Dives (Jonah Lupton)",
        "thesis_focus": "undiscovered undervalued small caps with upcoming catalysts",
    },
    {
        "feed_url": "https://yetanothervalueblog.substack.com",
        "rss_url": "https://yetanothervalueblog.substack.com/feed",
        "author_name": "Yet Another Value Blog (Andrew Walker)",
        "thesis_focus": "special situations, quirky value, event-driven",
    },
    {
        "feed_url": "https://overlookedalpha.substack.com",
        "rss_url": "https://overlookedalpha.substack.com/feed",
        "author_name": "Overlooked Alpha",
        "thesis_focus": "under-the-radar stocks, misunderstood investment opportunities",
    },
    {
        "feed_url": "https://thetranscript.substack.com",
        "rss_url": "https://thetranscript.substack.com/feed",
        "author_name": "The Transcript",
        "thesis_focus": "earnings call quotes compiled weekly — management signals and economic commentary",
    },
    {
        "feed_url": "https://10kdiver.substack.com",
        "rss_url": "https://10kdiver.substack.com/feed",
        "author_name": "10-K Diver",
        "thesis_focus": "deep fundamental analysis, financial math, long-term compounders",
    },
    {
        "feed_url": "https://speedwellresearch.substack.com",
        "rss_url": "https://speedwellresearch.substack.com/feed",
        "author_name": "Speedwell Research",
        "thesis_focus": "small and mid cap deep dives, under-covered companies",
    },
    {
        "feed_url": "https://www.netinterest.co",
        "rss_url": "https://www.netinterest.co/feed",
        "author_name": "Net Interest (Marc Rubinstein)",
        "thesis_focus": "financials, banking, fintech — former hedge fund manager",
    },
    {
        "feed_url": "https://stenoResearch.substack.com",
        "rss_url": "https://stenoResearch.substack.com/feed",
        "author_name": "Stenos Signals",
        "thesis_focus": "independent macro and geopolitical research, cross-asset",
    },
]


def _engine_session():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    return engine, Session()


def ensure_seed_feeds(session) -> None:
    """Pre-seed substack_feeds with curated list on first run."""
    for seed in SEED_FEEDS:
        existing = (
            session.query(SubstackFeed)
            .filter(SubstackFeed.feed_url == seed["feed_url"])
            .first()
        )
        if not existing:
            session.add(
                SubstackFeed(
                    feed_url=seed["feed_url"],
                    rss_url=seed["rss_url"],
                    author_name=seed["author_name"],
                    thesis_focus=seed["thesis_focus"],
                    active=True,
                )
            )
    session.flush()


def _parse_published(entry) -> Optional[datetime]:
    """Convert feedparser published/updated to aware datetime, if present."""
    for key in ("published_parsed", "updated_parsed"):
        dt_struct = getattr(entry, key, None) or entry.get(key)
        if dt_struct:
            try:
                return datetime(
                    dt_struct.tm_year,
                    dt_struct.tm_mon,
                    dt_struct.tm_mday,
                    dt_struct.tm_hour,
                    dt_struct.tm_min,
                    dt_struct.tm_sec,
                    tzinfo=timezone.utc,
                )
            except Exception:
                continue
    return None


def _call_claude_for_post(
    author_name: str,
    thesis_focus: str,
    title: str,
    summary: str,
) -> Dict[str, Any]:
    """
    Call Claude Haiku to extract tickers, sectors, and a one-sentence thesis.
    Returns a dict with keys: tickers, sectors, thesis.
    """
    system_prompt = (
        "You are an assistant that extracts investment tickers/sectors and a "
        "single concise thesis from research posts. You MUST respond with "
        "valid JSON only in the form: "
        '{"tickers": ["AAPL"], "sectors": ["Information Technology"], "thesis": "..."}. '
        "Include any of these sector/thematic tags when the post touches them: "
        "AI cybersecurity, automotive cybersecurity, zero trust, connected vehicle security, vehicle OTA, autonomous vehicle, "
        "plus standard GICS sectors (e.g. Information Technology, Industrials)."
    )
    base_prompt = (
        f"This investment research post is from {author_name} whose focus is {thesis_focus}. "
        f"Title: '{title}'. Summary: '{summary}'. "
        "1) List up to 5 ticker symbols or sector/thematic names this post most likely discusses or recommends. "
        "Use real ticker symbols where possible (e.g. AAPL not Apple). "
        "When the post touches AI security, zero trust, vehicle/AV security, or automotive cybersecurity, "
        "include sectors such as: AI cybersecurity, automotive cybersecurity, zero trust, connected vehicle security, vehicle OTA, autonomous vehicle. "
        "2) In exactly one sentence, what is the core investment thesis or signal in this post? "
        "Respond only as JSON: {\"tickers\": [], \"sectors\": [], \"thesis\": \"\"}"
    )
    raw = llm_client.summarize_low_stakes(system_prompt, base_prompt, max_tokens=400)

    # Try to parse JSON robustly (strip code fences or extra text)
    def _extract_json(text: str) -> Dict[str, Any]:
        try:
            return json.loads(text)
        except Exception:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except Exception:
                    pass
        return {"tickers": [], "sectors": [], "thesis": ""}

    parsed = _extract_json(raw or "")
    tickers = parsed.get("tickers") or []
    sectors = parsed.get("sectors") or []
    thesis = parsed.get("thesis") or ""

    # Normalize types to simple lists of strings
    tickers_out = [str(t).upper() for t in tickers if str(t).strip()]
    sectors_out = [str(s) for s in sectors if str(s).strip()]
    thesis_out = str(thesis).strip()

    return {
        "tickers": tickers_out,
        "sectors": sectors_out,
        "thesis": thesis_out,
    }


def _process_feed(session, feed: SubstackFeed) -> None:
    """Fetch RSS for a single SubstackFeed and store any new posts."""
    parsed = feedparser.parse(feed.rss_url)
    if parsed.bozo:
        # Invalid or unreachable feed; skip silently
        return

    entries = parsed.entries or []
    now = datetime.now(timezone.utc)

    for entry in entries:
        post_url = getattr(entry, "link", None) or entry.get("link")
        if not post_url:
            continue

        existing = (
            session.query(SubstackPost)
            .filter(SubstackPost.post_url == post_url)
            .first()
        )
        if existing:
            continue

        title = getattr(entry, "title", None) or entry.get("title") or ""
        summary = getattr(entry, "summary", None) or entry.get("summary") or ""
        published_dt = _parse_published(entry) or now

        # Respect paywalls: if summary looks truncated/empty, pass only title with note
        summary_for_llm = summary
        if not summary_for_llm or len(summary_for_llm) < 40:
            summary_for_llm = (
                "Full content is paywalled or truncated. Only the title is available."
            )

        try:
            extracted = _call_claude_for_post(
                author_name=feed.author_name,
                thesis_focus=feed.thesis_focus or "",
                title=title,
                summary=summary_for_llm,
            )
        except Exception:
            extracted = {"tickers": [], "sectors": [], "thesis": ""}

        tickers = extracted.get("tickers") or []
        sectors = extracted.get("sectors") or []
        thesis = extracted.get("thesis") or ""

        post = SubstackPost(
            feed_id=feed.id,
            title=title,
            summary=summary,
            published_date=published_dt,
            post_url=post_url,
            extracted_tickers=tickers,
            extracted_sectors=sectors,
            claude_one_sentence_thesis=thesis,
            watchlist_crossref_flag=False,
            processed_at=now,
        )
        session.add(post)

        # Sector-based cross-ref: if Haiku tagged with watchlist-relevant sectors, flag and log for agent brain
        SUBSTACK_WATCHLIST_SECTORS = {
            "AI cybersecurity", "automotive cybersecurity", "zero trust",
            "connected vehicle security", "vehicle OTA", "autonomous vehicle",
        }
        sectors_normalized = {str(s).strip() for s in sectors}
        if sectors_normalized & SUBSTACK_WATCHLIST_SECTORS:
            post.watchlist_crossref_flag = True
            desc = (
                f"{feed.author_name} published a post tagged with sector(s) {list(sectors_normalized & SUBSTACK_WATCHLIST_SECTORS)}: "
                f"{thesis or title}"
            )
            session.add(
                AgentSynthesisLog(
                    ticker=None,
                    trigger_type="substack_sector_mention",
                    description=desc[:2000],
                )
            )

        # Cross-reference tickers with watchlist
        if tickers:
            watchlist_companies = (
                session.query(Company)
                .filter(Company.active == True)
                .filter(Company.ticker.in_(tickers))
                .all()
            )
            if watchlist_companies:
                post.watchlist_crossref_flag = True
                for c in watchlist_companies:
                    desc = (
                        f"{feed.author_name} published a post mentioning {c.ticker}: "
                        f"{thesis or title}"
                    )
                    session.add(
                        AgentSynthesisLog(
                            ticker=c.ticker,
                            trigger_type="substack_mention",
                            description=desc[:2000],
                        )
                    )

            # For non-watchlist tickers, populate research_radar
            watchlist_tickers = {c.ticker for c in watchlist_companies}
            mention_date = published_dt.date()
            for t in tickers:
                if t in watchlist_tickers:
                    continue
                # Avoid duplicates for the same author/ticker/date
                existing_rr = (
                    session.query(ResearchRadar)
                    .filter(
                        ResearchRadar.ticker == t,
                        ResearchRadar.mentioned_by == feed.author_name,
                        ResearchRadar.mention_date == mention_date,
                    )
                    .first()
                )
                if existing_rr:
                    continue
                session.add(
                    ResearchRadar(
                        ticker=t,
                        mentioned_by=feed.author_name,
                        mention_date=mention_date,
                        thesis_snippet=(thesis or title)[:500],
                        added_to_watchlist=False,
                    )
                )

    feed.last_fetched = now


def run_substack_ingestion() -> None:
    """
    Entry point for APScheduler:
    - Ensure tables exist and seed feeds.
    - For each active feed, fetch new posts and process them.
    """
    engine, session = _engine_session()
    Base.metadata.create_all(engine)
    try:
        ensure_seed_feeds(session)
        feeds = session.query(SubstackFeed).filter(SubstackFeed.active == True).all()
        for feed in feeds:
            _process_feed(session, feed)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_substack_ingestion_for_single_feed(feed_id: int) -> None:
    """Ingest posts for a single feed ID (used from the dashboard Add Feed form)."""
    engine, session = _engine_session()
    Base.metadata.create_all(engine)
    try:
        feed = session.query(SubstackFeed).filter(SubstackFeed.id == feed_id).first()
        if not feed or not feed.active:
            return
        _process_feed(session, feed)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    print("Market Lens — Substack Reader")
    print("-----------------------------")
    run_substack_ingestion()
    print("[OK] Substack ingestion complete.")

