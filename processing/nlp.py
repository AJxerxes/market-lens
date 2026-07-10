"""
Market Lens — NLP Pipeline (Phase 6)
FinBERT sentiment on news, 10-K risk factor cosine similarity delta, supplier keyword scan.
"""
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
import os
import requests

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from market_lens.config import DATABASE_URL, NEWSAPI_KEY, WORKSPACE_ROOT
from market_lens.database.models import Base, Company, NewsSentiment, RiskFactorDelta, SupplierSignal, SignalType, SignalSeverity

MODELS_DIR = WORKSPACE_ROOT / "models"
FINBERT_MODEL = "ProsusAI/finbert"

SUPPLIER_KEYWORDS = [
    "transitioning our supply base",
    "qualifying a new supplier",
    "dual sourcing",
    "single source",
    "supply chain diversification",
    "moving away from",
    "new manufacturing partner",
]

# Cybersecurity topic search terms for NewsAPI daily pull. First 8 -> AI_cybersecurity, last 8 -> automotive_cybersecurity.
CYBERSECURITY_TERMS: List[tuple] = [
    ("AI cybersecurity", "AI_cybersecurity"),
    ("prompt injection attack", "AI_cybersecurity"),
    ("AI security breach", "AI_cybersecurity"),
    ("zero trust AI", "AI_cybersecurity"),
    ("deepfake fraud enterprise", "AI_cybersecurity"),
    ("AI generated phishing", "AI_cybersecurity"),
    ("model security", "AI_cybersecurity"),
    ("agentic security", "AI_cybersecurity"),
    ("automotive cybersecurity", "automotive_cybersecurity"),
    ("connected vehicle hack", "automotive_cybersecurity"),
    ("Waymo security", "automotive_cybersecurity"),
    ("Tesla cybersecurity", "automotive_cybersecurity"),
    ("vehicle OTA security", "automotive_cybersecurity"),
    ("autonomous vehicle attack surface", "automotive_cybersecurity"),
    ("NXP automotive", "automotive_cybersecurity"),
    ("software defined vehicle security", "automotive_cybersecurity"),
]


def _engine_session():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    return engine, Session()


def _get_finbert_pipeline():
    """Load FinBERT once; cache in models/."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from transformers import pipeline
        cache = str(MODELS_DIR / "finbert")
        if not Path(cache).exists():
            Path(cache).mkdir(parents=True, exist_ok=True)
        return pipeline("sentiment-analysis", model=FINBERT_MODEL, model_kwargs={"cache_dir": cache})
    except Exception as e:
        print(f"[WARN] FinBERT not available: {e}")
        return None


def _sentiment_to_score(label: str, score: float) -> float:
    if label == "positive":
        return min(1.0, score)
    if label == "negative":
        return max(-1.0, -score)
    return 0.0


def run_news_sentiment_for_ticker(session, ticker: str, company_name: str) -> int:
    """Fetch last 30 days news from NewsAPI, run FinBERT, store in news_sentiment. Returns count stored."""
    if not NEWSAPI_KEY:
        print("  [WARN] NEWSAPI_KEY not set, skipping news sentiment")
        return 0
    from_date = (date.today() - timedelta(days=30)).isoformat()
    url = (
        f"https://newsapi.org/v2/everything?q={company_name.replace(' ', '%20')}"
        f"&from={from_date}&sortBy=publishedAt&language=en&pageSize=20&apiKey={NEWSAPI_KEY}"
    )
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return 0
        data = r.json()
        articles = data.get("articles") or []
    except Exception as e:
        print(f"  [ERROR] NewsAPI {ticker}: {e}")
        return 0
    pipe = _get_finbert_pipeline()
    if not pipe:
        return 0
    count = 0
    for art in articles[:20]:
        title = art.get("title") or ""
        desc = art.get("description") or ""
        text_in = (title + " " + desc).strip()[:512]
        if not text_in:
            continue
        try:
            out = pipe(text_in)[0]
            label = out.get("label", "neutral").lower()
            score_raw = out.get("score", 0.5)
            score = _sentiment_to_score(label, score_raw)
        except Exception:
            continue
        pub = art.get("publishedAt")
        if pub:
            try:
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            except Exception:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)
        session.add(
            NewsSentiment(
                ticker=ticker,
                article_date=dt,
                headline=title[:500],
                source=art.get("source", {}).get("name"),
                url=art.get("url"),
                sentiment_score=score,
                sentiment_label=label,
            )
        )
        count += 1
        session.flush()
    return count


def run_news_sentiment_for_cybersecurity_terms(session) -> int:
    """Fetch last 30 days news from NewsAPI for each cybersecurity term; run FinBERT; store in news_sentiment with sector_tag. Returns total count stored."""
    if not NEWSAPI_KEY:
        print("  [WARN] NEWSAPI_KEY not set, skipping cybersecurity news")
        return 0
    from_date = (date.today() - timedelta(days=30)).isoformat()
    pipe = _get_finbert_pipeline()
    if not pipe:
        return 0
    total = 0
    for query_term, sector_tag in CYBERSECURITY_TERMS:
        url = (
            f"https://newsapi.org/v2/everything?q={query_term.replace(' ', '%20')}"
            f"&from={from_date}&sortBy=publishedAt&language=en&pageSize=20&apiKey={NEWSAPI_KEY}"
        )
        try:
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                continue
            data = r.json()
            articles = data.get("articles") or []
        except Exception as e:
            print(f"  [ERROR] NewsAPI cybersecurity '{query_term}': {e}")
            continue
        for art in articles[:20]:
            title = art.get("title") or ""
            desc = art.get("description") or ""
            text_in = (title + " " + desc).strip()[:512]
            if not text_in:
                continue
            try:
                out = pipe(text_in)[0]
                label = out.get("label", "neutral").lower()
                score_raw = out.get("score", 0.5)
                score = _sentiment_to_score(label, score_raw)
            except Exception:
                continue
            pub = art.get("publishedAt")
            if pub:
                try:
                    dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                except Exception:
                    dt = datetime.now(timezone.utc)
            else:
                dt = datetime.now(timezone.utc)
            session.add(
                NewsSentiment(
                    ticker=None,
                    article_date=dt,
                    headline=title[:500],
                    source=art.get("source", {}).get("name"),
                    url=art.get("url"),
                    sentiment_score=score,
                    sentiment_label=label,
                    sector_tag=sector_tag,
                )
            )
            total += 1
    session.flush()
    return total


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
    engine, Session = _engine_session()
    Base.metadata.create_all(engine)
    session = Session()
    try:
        if tickers is None:
            companies = session.query(Company).filter(Company.active == True).all()
            tickers = [(c.ticker, c.name or c.ticker) for c in companies]
        else:
            tickers = [(t, t) for t in tickers]
        for ticker, name in tickers:
            try:
                n = run_news_sentiment_for_ticker(session, ticker, name)
                print(f"  [OK] {ticker} news sentiment: {n} articles")
            except Exception as e:
                print(f"  [ERROR] {ticker}: {e}")
        try:
            n_cyber = run_news_sentiment_for_cybersecurity_terms(session)
            print(f"  [OK] cybersecurity topic news: {n_cyber} articles")
        except Exception as e:
            print(f"  [ERROR] cybersecurity news: {e}")
        session.commit()
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
