"""
Market Lens Database Seeder
Creates tables and populates with initial watchlist companies.
"""
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from market_lens.config import DATABASE_URL
from market_lens.database.models import Base, Company, InstrumentType, AgentMemory

def create_tables(engine):
    """Create all database tables."""
    print("Creating database tables...")
    Base.metadata.create_all(engine)
    print("[OK] Tables created successfully")


def seed_watchlist(session):
    """Seed initial watchlist with four test companies."""
    print("\nSeeding initial watchlist...")
    
    seed_companies = [
        {
            "ticker": "ASAZY",
            "name": "Assa Abloy AB",
            "sector": "Industrials",
            "exchange": "OTC",
            "instrument_type": InstrumentType.otc_adr,
            "thesis_notes": "Dominant access control systems - HID card readers on every university door, office building, and government facility. Moat: installed base lock-in and switching costs.",
            "local_currency": "SEK",
            "fx_series_id": "DEXSDUS",  # USD/SEK from FRED
        },
        {
            "ticker": "DLB",
            "name": "Dolby Laboratories, Inc.",
            "sector": "Communication Services",
            "exchange": "NYSE",
            "instrument_type": InstrumentType.equity,
            "thesis_notes": "Audio licensing moat - every streaming service, movie theater, and device manufacturer pays royalties. Trading below 5-year average P/E despite stable cash flow.",
        },
        {
            "ticker": "SYY",
            "name": "Sysco Corporation",
            "sector": "Consumer Staples",
            "exchange": "NYSE",
            "instrument_type": InstrumentType.equity,
            "thesis_notes": "Dominant foodservice distributor - Sysco trucks deliver to nearly every restaurant. Recession-resistant with pricing power.",
        },
        {
            "ticker": "JBHT",
            "name": "J.B. Hunt Transport Services, Inc.",
            "sector": "Industrials",
            "exchange": "NASDAQ",
            "instrument_type": InstrumentType.equity,
            "thesis_notes": "Intermodal logistics leader - orange containers on every rail line. Benefits from driver shortage and fuel efficiency of rail vs truck.",
        },
    ]
    
    now_utc = datetime.now(timezone.utc)
    
    for company_data in seed_companies:
        # Check if already exists
        existing = session.query(Company).filter_by(ticker=company_data["ticker"]).first()
        if existing:
            print(f"  (skip) {company_data['ticker']} already exists")
            continue
        
        # Create company
        company = Company(
            ticker=company_data["ticker"],
            name=company_data["name"],
            sector=company_data["sector"],
            exchange=company_data["exchange"],
            instrument_type=company_data["instrument_type"],
            active=True,
            paused=False,
            watchlist_added_date=now_utc,
            thesis_notes=company_data.get("thesis_notes"),
            local_currency=company_data.get("local_currency"),
            fx_series_id=company_data.get("fx_series_id"),
        )
        session.add(company)
        session.flush()  # ensure company row exists before agent_memory (FK)

        # Create initial agent memory snapshot (empty state)
        memory = AgentMemory(
            ticker=company_data["ticker"],
            snapshot_date=now_utc,
            lynch_score=None,
            swing_score=None,
            sentiment_score=None,
            insider_net=None,
            recommendation_label=None,
            thesis_summary=company_data.get("thesis_notes"),
            signal_history_90d={"events": []},
        )
        session.add(memory)
        
        print(f"  [OK] Added {company_data['ticker']} ({company_data['name']}) as {company_data['instrument_type'].value}")
    
    session.commit()
    print("\n[OK] Watchlist seeded successfully")


def run_seed():
    """Main seeding function."""
    print("=" * 60)
    print("Market Lens Database Seeder")
    print("=" * 60)
    
    # Create engine
    engine = create_engine(DATABASE_URL, echo=False)
    
    # Create tables
    create_tables(engine)
    
    # Create session
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Seed watchlist
        seed_watchlist(session)
        
        print("\n" + "=" * 60)
        print("Seeding complete!")
        print("=" * 60)
        print("\nNext steps:")
        print("  1. Verify tables in pgAdmin")
        print("  2. Run Phase 2 to ingest price history")
        print("  3. Test NSSM service registration")
        
    except Exception as e:
        print(f"\n[ERROR] Seeding failed: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    run_seed()
