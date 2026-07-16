"""
Market Lens — NLP Pipeline (Phase 6)
News sentiment (Claude Haiku), 10-K risk factor cosine similarity delta, supplier keyword scan.
"""
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
import os
import requests

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from market_lens.config import DATABASE_URL, NEWSAPI_KEY, MARKETAUX_API_KEY, DASHBOARD_BASE_URL
from market_lens.database.models import Base, Company, NewsSentiment, RiskFactorDelta, SupplierSignal, SignalType, SignalSeverity

SUPPLIER_KEYWORDS = [
    "transitioning our supply base",
    "qualifying a new supplier",
    "dual sourcing",
    "single source",
    "supply chain diversification",
    "moving away from",
    "new manufacturing partner",
]


def _engine_session():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    return engine, Session


def _get_sentiment_haiku(headline: str, description: str = "") -> tuple:
    """
    Score financial sentiment using Claude Haiku.
    Returns (label, score) where label is positive/neutral/negative
    and score is -1.0 to 1.0.
    """
    from market_lens.agent.llm_client import summarize_low_stakes
    import json
    text = f"{headline}. {description}".strip()[:500]
    try:
        result = summarize_low_stakes(
            system_prompt=(
                "You are a financial sentiment analyzer. "
                "Respond with JSON only, no other text. "
                "Format: {\"label\": \"positive\" or \"neutral\" or \"negative\", "
                "\"score\": number between -1.0 and 1.0}"
            ),
            user_content=(
                f"Rate the financial sentiment of this news for an equity investor: {text}"
            ),
            max_tokens=50,
        )
        import re as _re
        clean = result.strip()
        clean = _re.sub(r"```json|```", "", clean).strip()
        # Extract only the first JSON object found
        match = _re.search(r"\{.*?\}", clean, _re.DOTALL)
        clean = match.group(0) if match else clean
        data = json.loads(clean)
        label = data.get("label", "neutral")
        if isinstance(label, str):
            label = label.lower()
        score = float(data.get("score", 0.0))
        score = max(-1.0, min(1.0, score))
        return label, score
    except Exception as e:
        print(f"[WARN] Haiku sentiment failed: {e}")
        return "neutral", 0.0


def _sentiment_to_score(label: str, score: float) -> float:
    if label == "positive":
        return min(1.0, score)
    if label == "negative":
        return max(-1.0, -score)
    return 0.0


WATCHLIST_SECTOR_BATCHES = {
    "cybersecurity": ["ZS", "PANW", "FTNT", "TENB", "VRNS", "S", "NET"],
    "semiconductors": ["NXPI", "CALX", "IOT"],
    "transport_logistics": ["JBHT", "APTV", "SYY"],
    "audio_niche": ["DLB", "CTTAF", "ASAZY"],
    "etfs": ["QQQ", "SPY"],
}


def run_news_sentiment_batched(session) -> int:
    """
    Fetch news for all watchlist tickers using sector-batched requests.
    5 requests total instead of 1 per ticker. Stores results in news_sentiment.
    Returns total article count stored.
    """
    if not MARKETAUX_API_KEY:
        print("  [WARN] MARKETAUX_API_KEY not set, skipping news sentiment")
        return 0

    total_stored = 0

    for sector, tickers in WATCHLIST_SECTOR_BATCHES.items():
        symbols = ",".join(tickers)
        url = (
            f"https://api.marketaux.com/v1/news/all"
            f"?symbols={symbols}&filter_entities=true&limit=3&language=en"
            f"&api_token={MARKETAUX_API_KEY}"
        )
        try:
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                print(f"  [WARN] MarketAux {sector}: HTTP {r.status_code}")
                continue
            data = r.json()
            articles = data.get("data") or []
        except Exception as e:
            print(f"  [ERROR] MarketAux {sector}: {e}")
            continue

        for art in articles:
            title = art.get("title") or ""
            desc = art.get("description") or ""
            if not (title or desc):
                continue

            # Determine which watchlist tickers this article mentions
            mentioned = []
            entities = art.get("entities") or []
            for entity in entities:
                sym = (entity.get("symbol") or "").upper()
                if sym in tickers:
                    mentioned.append(sym)
            if not mentioned:
                mentioned = tickers  # fallback: tag all tickers in batch

            pub = art.get("published_at")
            if pub:
                try:
                    dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                except Exception:
                    dt = datetime.now(timezone.utc)
            else:
                dt = datetime.now(timezone.utc)

            try:
                label, score = _get_sentiment_haiku(title, desc)
            except Exception:
                label, score = "neutral", 0.0

            for ticker in mentioned:
                existing = session.query(NewsSentiment).filter_by(
                    ticker=ticker, headline=title[:500]
                ).first()
                if existing:
                    continue
                session.add(
                    NewsSentiment(
                        ticker=ticker,
                        article_date=dt,
                        headline=title[:500],
                        source=art.get("source"),
                        url=art.get("url"),
                        sentiment_score=score,
                        sentiment_label=label,
                    )
                )
                total_stored += 1

        session.flush()
        print(f"  [OK] MarketAux {sector}: {len(articles)} articles processed")

    return total_stored


def fetch_macro_news_snapshot() -> Dict[str, Any]:
    """
    Fetch macro news from MarketAux using topic filters.
    5 requests covering technology, energy, politics, finance, economy.
    Returns structured dict with articles grouped by theme.
    """
    if not MARKETAUX_API_KEY:
        return {"error": "MARKETAUX_API_KEY is not set"}

    macro_topics = {
        "technology": "technology",
        "energy": "energy",
        "geopolitics": "politics",
        "finance": "finance",
        "economy": "economy",
    }

    enriched: List[Dict[str, Any]] = []

    for theme_key, topic in macro_topics.items():
        url = (
            f"https://api.marketaux.com/v1/news/all"
            f"?topics={topic}&limit=3&language=en"
            f"&api_token={MARKETAUX_API_KEY}"
        )
        try:
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                continue
            data = r.json()
            articles = data.get("data") or []
        except Exception:
            continue

        for art in articles:
            title = art.get("title") or ""
            desc = art.get("description") or ""
            if not (title or desc):
                continue
            try:
                label, score = _get_sentiment_haiku(title, desc)
            except Exception:
                label, score = "neutral", 0.0
            pub = art.get("published_at")
            try:
                pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00")) if pub else None
            except Exception:
                pub_dt = None
            enriched.append(
                {
                    "title": title,
                    "description": desc,
                    "url": art.get("url"),
                    "source": art.get("source"),
                    "published_at": pub_dt.isoformat() if pub_dt else pub,
                    "theme": theme_key,
                    "sentiment_score": score,
                    "sentiment_label": label,
                }
            )

    grouped: Dict[str, Dict[str, Any]] = {}
    for art in enriched:
        theme = art["theme"]
        g = grouped.setdefault(theme, {"theme": theme, "articles": [], "avg_sentiment": 0.0})
        g["articles"].append(art)
    for theme, g in grouped.items():
        scores = [a["sentiment_score"] for a in g["articles"]]
        g["avg_sentiment"] = sum(scores) / len(scores) if scores else 0.0
        g["examples"] = [a["title"] for a in g["articles"][:3]]

    return {
        "themes": grouped,
        "articles": enriched,
    }


def run_negative_news_alerts(as_of: Optional[date] = None) -> None:
    """
    Scan news_sentiment for the last 24h and send a Telegram alert
    when a watchlist ticker has 3+ strongly negative articles.
    This is designed to be called once per day after the NLP pipeline.
    """
    from market_lens.alerts.notifier import send_telegram, format_telegram_alert

    as_of = as_of or date.today()
    start_dt = datetime(as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=1)

    engine, _Session = _engine_session()
    session = _Session()
    try:
        rows = (
            session.query(NewsSentiment.ticker, NewsSentiment.sentiment_score)
            .filter(NewsSentiment.article_date >= start_dt)
            .filter(NewsSentiment.article_date < end_dt)
            .all()
        )
        if not rows:
            return
        neg_counts: Dict[str, int] = {}
        for ticker, score in rows:
            if score is not None and score < -0.3:
                neg_counts[ticker] = neg_counts.get(ticker, 0) + 1
        for ticker, count in neg_counts.items():
            if count >= 3:
                signal_line = (
                    f"{ticker} — elevated negative news volume today. "
                    f"{count} articles with negative sentiment. Review recommended."
                )
                msg = format_telegram_alert("NEWS_ALERT", ticker, signal_line)
                ok, err = send_telegram(msg)
                if not ok:
                    print(f"[ALERT WARNING] Negative news alert failed for {ticker}: {err}")
    finally:
        session.close()
def run_risk_factor_delta(session, ticker: str, current_text: str, prior_text: str, current_date: date, prior_date: date) -> Optional[float]:
    """Compute cosine similarity between current and prior risk factor text. Store in risk_factor_delta."""
    if not current_text or not prior_text:
        return None
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vec = TfidfVectorizer(max_features=5000)
        m = vec.fit_transform([current_text[:50000], prior_text[:50000]])
        sim = cosine_similarity(m[0:1], m[1:2])[0][0]
    except Exception as e:
        print(f"  [WARN] risk factor similarity {ticker}: {e}")
        return None
    meaningful = sim < 0.85
    row = RiskFactorDelta(
        ticker=ticker,
        current_filing_date=current_date,
        prior_filing_date=prior_date,
        current_risk_text=current_text[:10000],
        prior_risk_text=prior_text[:10000],
        cosine_similarity=round(sim, 4),
        meaningful_change_flag=meaningful,
    )
    session.add(row)
    session.flush()
    return sim


def run_supplier_keyword_scan(session, ticker: str, transcript_text: str, source: str = "earnings_call") -> int:
    """Scan transcript for supplier keywords; store context in supplier_signals."""
    if not transcript_text:
        return 0
    text_lower = transcript_text.lower()
    count = 0
    for kw in SUPPLIER_KEYWORDS:
        if kw.lower() in text_lower:
            idx = text_lower.find(kw.lower())
            start = max(0, idx - 50)
            end = min(len(transcript_text), idx + len(kw) + 100)
            context = transcript_text[start:end]
            session.add(
                SupplierSignal(
                    ticker=ticker,
                    detected_date=date.today(),
                    signal_type=SignalType.supplier_risk_language,
                    context_text=context[:500],
                    source=source,
                    severity=SignalSeverity.informational,
                )
            )
            count += 1
    session.flush()
    return count


def run_nlp_pipeline(tickers: Optional[List[str]] = None) -> None:
    """Run news sentiment for all watchlist (batch once daily). Risk factor and supplier scan are called from edgar/transcript code."""
    engine, _SF = _engine_session(); session = _SF()
    Base.metadata.create_all(engine)
    try:
        if tickers is None:
            companies = session.query(Company).filter(Company.active == True).all()
            tickers = [(c.ticker, c.name or c.ticker) for c in companies]
        else:
            tickers = [(t, t) for t in tickers]
        try:
            n = run_news_sentiment_batched(session)
            print(f"  [OK] MarketAux batched sentiment: {n} articles stored")
        except Exception as e:
            print(f"  [ERROR] MarketAux batched sentiment: {e}")
        session.commit()
        # After storing news sentiment, run negative news alerts for today
        try:
            run_negative_news_alerts(date.today())
        except Exception as e:
            print(f"[WARN] Negative news alerts failed: {e}")
        print("[OK] NLP pipeline complete")
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    import sys
    tickers = sys.argv[1:] if len(sys.argv) > 1 else None
    print("Market Lens — NLP Pipeline")
    print("-------------------------")
    run_nlp_pipeline(tickers)


