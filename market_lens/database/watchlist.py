"""
Market Lens Dynamic Watchlist Manager
Add/remove/pause any ticker at runtime with auto-classification and historical backfill.
"""
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import yfinance as yf

from market_lens import config
from market_lens.database.models import Company, InstrumentType, AgentMemory


class WatchlistManager:
    """Manages dynamic watchlist operations."""
    
    def __init__(self, db_session: Optional[Session] = None):
        """Initialize with optional DB session."""
        if db_session:
            self.session = db_session
            self._owns_session = False
        else:
            engine = create_engine(config.DATABASE_URL)
            Session = sessionmaker(bind=engine)
            self.session = Session()
            self._owns_session = True
    
    def __del__(self):
        """Clean up session if we own it."""
        if self._owns_session and hasattr(self, 'session'):
            self.session.close()
    
    def search_ticker(self, query: str) -> Dict[str, Any]:
        """
        Search for ticker by symbol or company name.
        
        Args:
            query: Ticker symbol or company name
            
        Returns:
            Dict with 'matches' list and optional 'resolved_ticker'
        """
        query = query.strip()
        upper_query = query.upper()
        
        # If looks like a ticker (2-5 uppercase letters), validate directly
        if len(query) <= 5 and upper_query.isalpha():
            try:
                ticker_obj = yf.Ticker(upper_query)
                info = ticker_obj.info
                
                if info and 'symbol' in info:
                    return {
                        "matches": [{
                            "ticker": info.get('symbol', upper_query),
                            "name": info.get('longName', info.get('shortName', 'Unknown')),
                            "sector": info.get('sector', 'Unknown'),
                            "exchange": info.get('exchange', 'Unknown'),
                            "quote_type": info.get('quoteType', 'EQUITY'),
                        }],
                        "resolved_ticker": info.get('symbol', upper_query),
                        "needs_confirmation": False,
                    }
            except Exception as e:
                print(f"Error validating ticker {query}: {e}")
        
        # Company name search - preferred: FMP search endpoints, fallback to yfinance
        matches: List[Dict[str, Any]] = []

        # Try Financial Modeling Prep search (symbol/name) if API key is available
        if config.FMP_API_KEY:
            try:
                resp = requests.get(
                    "https://financialmodelingprep.com/api/v3/search",
                    params={"query": query, "limit": 3, "apikey": config.FMP_API_KEY},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json() or []
                    for item in data[:3]:
                        matches.append({
                            "ticker": (item.get("symbol") or "").upper(),
                            "name": item.get("name") or item.get("symbol") or "",
                            "sector": item.get("sector") or "Unknown",
                            "exchange": item.get("exchangeShortName") or item.get("stockExchange", ""),
                            "quote_type": "EQUITY",
                        })
            except Exception as e:
                print(f"FMP search failed for '{query}': {e}")

            # If symbol search returned nothing, fall back to FMP name search
            if not matches:
                try:
                    resp2 = requests.get(
                        "https://financialmodelingprep.com/api/v3/search-name",
                        params={"query": query, "limit": 3, "apikey": config.FMP_API_KEY},
                        timeout=10,
                    )
                    if resp2.status_code == 200:
                        data2 = resp2.json() or []
                        for item in data2[:3]:
                            matches.append({
                                "ticker": (item.get("symbol") or "").upper(),
                                "name": item.get("name") or item.get("symbol") or "",
                                "sector": item.get("sector") or "Unknown",
                                "exchange": item.get("exchangeShortName") or item.get("stockExchange", ""),
                                "quote_type": "EQUITY",
                            })
                except Exception as e:
                    print(f"FMP search-name failed for '{query}': {e}")

        # Fallback to a lightweight yfinance lookup if FMP produced nothing
        if not matches:
            try:
                ticker_obj = yf.Ticker(query)
                info = ticker_obj.info
                
                if info and 'symbol' in info:
                    matches.append({
                        "ticker": info.get('symbol', query).upper(),
                        "name": info.get('longName', info.get('shortName', 'Unknown')),
                        "sector": info.get('sector', 'Unknown'),
                        "exchange": info.get('exchange', 'Unknown'),
                        "quote_type": info.get('quoteType', 'EQUITY'),
                    })
            except Exception as e:
                print(f"Error searching for {query} via yfinance: {e}")
        
        if matches:
            # For name-based search, require user confirmation even if only one match
            return {
                "matches": matches,
                "resolved_ticker": matches[0]["ticker"],
                "needs_confirmation": True,
            }
        
        # No matches from FMP or yfinance
        base_error = f"No results found for '{query}'"
        if not config.FMP_API_KEY:
            base_error += " (FMP_API_KEY not set; only limited yfinance lookup is available.)"
        return {
            "matches": [],
            "resolved_ticker": None,
            "needs_confirmation": False,
            "error": base_error,
        }
    
    def classify_instrument(self, ticker: str) -> Dict[str, Any]:
        """
        Auto-classify instrument type from yfinance metadata.
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Dict with 'instrument_type', 'confidence', and metadata
        """
        try:
            ticker_obj = yf.Ticker(ticker)
            info = ticker_obj.info
            
            if not info or 'symbol' not in info:
                return {
                    "instrument_type": None,
                    "confidence": "uncertain",
                    "error": "Unable to fetch ticker information"
                }
            
            quote_type = info.get('quoteType', '').upper()
            exchange = info.get('exchange', '').upper()
            name = info.get('longName', info.get('shortName', ''))
            
            # Classification logic
            if quote_type == 'ETF':
                # Check if inverse ETF
                inverse_keywords = ['inverse', 'short', 'bear', 'ultra short', 'proshares short']
                is_inverse = any(kw in name.lower() for kw in inverse_keywords)
                
                return {
                    "instrument_type": InstrumentType.inverse_etf if is_inverse else InstrumentType.etf,
                    "confidence": "high",
                    "name": name,
                    "sector": info.get('category', 'Unknown'),
                    "exchange": exchange,
                }
            
            elif quote_type == 'MUTUALFUND':
                return {
                    "instrument_type": InstrumentType.mutual_fund,
                    "confidence": "high",
                    "name": name,
                    "sector": info.get('category', 'Unknown'),
                    "exchange": exchange,
                }
            
            elif quote_type in ['EQUITY', 'STOCK']:
                # Check if OTC ADR
                if 'OTC' in exchange or exchange in ['PINK', 'OTCBB', 'OTCQB', 'OTCQX']:
                    # Check if ADR (foreign company)
                    country = info.get('country', '')
                    if country and country != 'United States':
                        return {
                            "instrument_type": InstrumentType.otc_adr,
                            "confidence": "high",
                            "name": name,
                            "sector": info.get('sector', 'Unknown'),
                            "exchange": exchange,
                            "country": country,
                            "currency": info.get('currency', 'USD'),
                        }
                
                # Regular equity
                return {
                    "instrument_type": InstrumentType.equity,
                    "confidence": "high",
                    "name": name,
                    "sector": info.get('sector', 'Unknown'),
                    "exchange": exchange,
                }
            
            # Uncertain classification
            return {
                "instrument_type": None,
                "confidence": "uncertain",
                "quote_type": quote_type,
                "name": name,
                "exchange": exchange,
            }
            
        except Exception as e:
            return {
                "instrument_type": None,
                "confidence": "error",
                "error": str(e)
            }
    
    def add_ticker(
        self,
        ticker: str,
        thesis_notes: Optional[str] = None,
        instrument_type: Optional[InstrumentType] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Add ticker to watchlist with auto-classification and backfill.
        
        Args:
            ticker: Stock ticker symbol
            thesis_notes: User's Lynch observation (optional)
            instrument_type: Override auto-classification (optional)
            force: Skip confirmation if classification uncertain
            
        Returns:
            Dict with status and company info
        """
        ticker = ticker.upper().strip()
        
        # Check if already exists
        existing = self.session.query(Company).filter_by(ticker=ticker).first()
        if existing:
            if existing.active:
                return {
                    "status": "already_exists",
                    "ticker": ticker,
                    "message": f"{ticker} is already on the watchlist"
                }
            else:
                # Reactivate
                existing.active = True
                existing.paused = False
                existing.updated_at = datetime.now(timezone.utc)
                if self._owns_session:
                    self.session.commit()
                else:
                    self.session.flush()
                return {
                    "status": "reactivated",
                    "ticker": ticker,
                    "message": f"{ticker} reactivated on watchlist"
                }
        
        # Classify instrument type
        if not instrument_type:
            classification = self.classify_instrument(ticker)
            
            if classification["confidence"] == "uncertain" and not force:
                return {
                    "status": "needs_confirmation",
                    "ticker": ticker,
                    "classification": classification,
                    "message": "Please confirm instrument type before adding"
                }
            
            if classification["confidence"] == "error":
                return {
                    "status": "error",
                    "ticker": ticker,
                    "error": classification.get("error", "Classification failed")
                }
            
            instrument_type = classification["instrument_type"]
            metadata = classification
        else:
            # Use provided type, fetch basic metadata
            try:
                ticker_obj = yf.Ticker(ticker)
                info = ticker_obj.info
                metadata = {
                    "name": info.get('longName', info.get('shortName', ticker)),
                    "sector": info.get('sector', 'Unknown'),
                    "exchange": info.get('exchange', 'Unknown'),
                }
            except Exception as e:
                return {
                    "status": "error",
                    "ticker": ticker,
                    "error": f"Failed to fetch ticker info: {e}"
                }
        
        # Create company record
        now_utc = datetime.now(timezone.utc)
        
        company = Company(
            ticker=ticker,
            name=metadata.get("name", ticker),
            legal_name=metadata.get("legal_name", metadata.get("name", ticker)),
            sector=metadata.get("sector"),
            exchange=metadata.get("exchange"),
            instrument_type=instrument_type,
            active=True,
            paused=False,
            watchlist_added_date=now_utc,
            thesis_notes=thesis_notes,
            local_currency=metadata.get("currency") if instrument_type == InstrumentType.otc_adr else None,
        )
        self.session.add(company)
        # Ensure company row exists before inserting AgentMemory (FK on ticker)
        self.session.flush()
        
        # Create initial agent memory snapshot
        memory = AgentMemory(
            ticker=ticker,
            snapshot_date=now_utc,
            thesis_summary=thesis_notes,
            signal_history_90d={"events": []},
        )
        self.session.add(memory)
        
        if self._owns_session:
            self.session.commit()
        else:
            self.session.flush()
        
        # Queue historical backfill (stub for Phases 2–3).
        # The scheduler in agent.py will look for newly-added tickers
        # and trigger price/EDGAR/news/leadership/supplier backfills.
        print(
            f"[BACKFILL QUEUED] {ticker} - price history, "
            f"fundamentals, EDGAR filings, insider activity"
        )
        
        return {
            "status": "added",
            "ticker": ticker,
            "name": company.name,
            "instrument_type": instrument_type.value,
            "message": f"Successfully added {ticker} to watchlist"
        }
    
    def remove_ticker(self, ticker: str, permanent: bool = False) -> Dict[str, Any]:
        """
        Remove ticker from watchlist (soft delete by default).
        
        Args:
            ticker: Stock ticker symbol
            permanent: If True, delete from database (not recommended)
            
        Returns:
            Dict with status
        """
        ticker = ticker.upper().strip()
        
        company = self.session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return {
                "status": "not_found",
                "ticker": ticker,
                "message": f"{ticker} not found in watchlist"
            }
        
        if permanent:
            self.session.delete(company)
            self.session.commit()
            return {
                "status": "deleted",
                "ticker": ticker,
                "message": f"{ticker} permanently deleted from database"
            }
        else:
            company.active = False
            company.updated_at = datetime.now(timezone.utc)
            self.session.commit()
            return {
                "status": "removed",
                "ticker": ticker,
                "message": f"{ticker} removed from watchlist (data retained)"
            }
    
    def pause_ticker(self, ticker: str) -> Dict[str, Any]:
        """Pause monitoring without removing from watchlist."""
        ticker = ticker.upper().strip()
        
        company = self.session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return {
                "status": "not_found",
                "ticker": ticker,
                "message": f"{ticker} not found in watchlist"
            }
        
        company.paused = True
        company.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        
        return {
            "status": "paused",
            "ticker": ticker,
            "message": f"{ticker} monitoring paused"
        }
    
    def resume_ticker(self, ticker: str) -> Dict[str, Any]:
        """Resume monitoring a paused ticker."""
        ticker = ticker.upper().strip()
        
        company = self.session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return {
                "status": "not_found",
                "ticker": ticker,
                "message": f"{ticker} not found in watchlist"
            }
        
        company.paused = False
        company.active = True
        company.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        
        return {
            "status": "resumed",
            "ticker": ticker,
            "message": f"{ticker} monitoring resumed"
        }
    
    def list_watchlist(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        """Get all watchlist companies."""
        query = self.session.query(Company)
        
        if not include_inactive:
            query = query.filter_by(active=True)
        
        companies = query.all()
        
        return [{
            "ticker": c.ticker,
            "name": c.name,
            "sector": c.sector,
            "instrument_type": c.instrument_type.value,
            "active": c.active,
            "paused": c.paused,
            "added_date": c.watchlist_added_date.isoformat(),
            "thesis_notes": c.thesis_notes,
        } for c in companies]


# Convenience functions for CLI usage
def add_ticker_cli(ticker: str, thesis: Optional[str] = None):
    """CLI helper to add ticker."""
    manager = WatchlistManager()
    result = manager.add_ticker(ticker, thesis_notes=thesis)
    print(f"\n{result['message']}")
    return result


def remove_ticker_cli(ticker: str):
    """CLI helper to remove ticker."""
    manager = WatchlistManager()
    result = manager.remove_ticker(ticker)
    print(f"\n{result['message']}")
    return result


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python watchlist.py add TICKER [thesis notes]")
        print("  python watchlist.py remove TICKER")
        print("  python watchlist.py list")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "add" and len(sys.argv) >= 3:
        ticker = sys.argv[2]
        thesis = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else None
        add_ticker_cli(ticker, thesis)
    
    elif command == "remove" and len(sys.argv) >= 3:
        ticker = sys.argv[2]
        remove_ticker_cli(ticker)
    
    elif command == "list":
        manager = WatchlistManager()
        companies = manager.list_watchlist()
        print("\nActive Watchlist:")
        print("-" * 80)
        for c in companies:
            print(f"{c['ticker']:8} | {c['name']:40} | {c['instrument_type']}")
        print("-" * 80)
        print(f"Total: {len(companies)} companies")
    
    else:
        print("Invalid command")
        sys.exit(1)


def get_module_activation_profile(instrument_type: InstrumentType) -> Dict[str, bool]:
    """
    Return which major modules should be active for a given instrument type.

    This is used by the agent brain to decide which ingestion and
    analysis jobs to run.
    """
    if instrument_type == InstrumentType.equity or instrument_type == InstrumentType.otc_adr:
        return {
            "prices": True,
            "fundamentals": True,
            "valuation": True,
            "technicals": True,
            "options": True,
            "leadership": True,
            "suppliers": True,
            "ptab": True,
            "court_dockets": True,
        }
    if instrument_type == InstrumentType.etf or instrument_type == InstrumentType.inverse_etf:
        return {
            "prices": True,
            "fundamentals": False,
            "valuation": False,
            "technicals": True,
            "options": True,
            "leadership": False,
            "suppliers": False,
            "ptab": False,
            "court_dockets": False,
        }
    if instrument_type == InstrumentType.mutual_fund:
        return {
            "prices": True,  # NAV history
            "fundamentals": False,
            "valuation": False,
            "technicals": False,
            "options": False,
            "leadership": False,
            "suppliers": False,
            "ptab": False,
            "court_dockets": False,
        }
    # Safe default: conservative activation
    return {
        "prices": True,
        "fundamentals": False,
        "valuation": False,
        "technicals": True,
        "options": False,
        "leadership": False,
        "suppliers": False,
        "ptab": False,
        "court_dockets": False,
    }
